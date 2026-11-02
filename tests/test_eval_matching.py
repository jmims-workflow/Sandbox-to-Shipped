"""The matching evaluation: the case file, the scoring, the command and the report.

None of these tests calls the real Claude API. They use the word match, the stand-in client and
small hand-built answers.
"""

import json
import socket
from collections import Counter
from datetime import date
from types import SimpleNamespace

import pytest
import yaml
from typer.testing import CliRunner

from sts import eval_matching as ev
from sts.cli import app
from sts.eval_scoring import (
    CaseRun,
    consistency,
    estimate_cost,
    score_injection,
    score_related,
    score_tools,
    summarize,
)
from sts.provider import MatchResult

SENTINEL_KEY = "sk-ant-test-SENTINEL-do-not-print-0123456789"


@pytest.fixture(scope="module")
def world():
    return ev.load_world()


@pytest.fixture(scope="module")
def cases(world):
    return ev.load_cases(ev.CASES_PATH, world)


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "STS_FAKE_CLAUDE", "STS_MODE", "STS_MODEL"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def invoke(*args):
    return CliRunner().invoke(app, ["eval-matching", *args])


# ---- The case file ------------------------------------------------------------------------


def test_case_file_loads_and_every_id_exists(cases, world):
    tools = {t.id: t for t in world.inventory}
    past = {d["id"] for d in world.past}
    open_ids = {r["id"] for r in world.open_requests}
    assert 28 <= len(cases) <= 36
    assert len({c.id for c in cases}) == len(cases)
    for c in cases:
        for tid in c.expected_tools + c.possible_ok:
            assert tid in tools and tools[tid].status != "retired", (c.id, tid)
        assert c.expected_related_decision is None or c.expected_related_decision in past, c.id
        assert c.expected_related_request is None or c.expected_related_request in open_ids, c.id
        assert c.note.strip()


def test_every_category_has_at_least_three_cases(cases):
    counts = Counter(c.category for c in cases)
    assert set(counts) == set(ev.CATEGORIES)
    assert all(n >= 3 for n in counts.values()), counts


def test_cases_do_not_reuse_demo_task_text(cases):
    from sts.config import ROOT

    demo_tasks = [r["task"] for r in yaml.safe_load((ROOT / "demo/requests.yaml").read_text())["requests"]]
    demo_tasks += [e["task"] for e in yaml.safe_load((ROOT / "demo/examples.yaml").read_text())["examples"]]
    demo_tasks += [json.loads(p.read_text()).get("task", "") for p in (ROOT / "demo/recorded").glob("*.json")]
    norm = lambda t: " ".join(t.lower().split())
    for c in cases:
        assert norm(c.task) not in {norm(t) for t in demo_tasks}, c.id


def test_category_rules_hold(cases):
    for c in cases:
        if c.category in ("no_match", "retired_tool", "look_alike"):
            assert c.expected_tools == [], c.id
        if c.category in ("clear_match", "restricted_tool", "in_pilot_tool"):
            assert c.expected_tools, c.id
        if c.category == "open_duplicate":
            assert c.expected_related_request, c.id
        if c.category == "injection":
            assert c.injection is not None, c.id
    restricted = [c for c in cases if c.category == "restricted_tool"]
    assert all(c.expected_tools[0] in ("proposal-drafter", "case-study-builder") for c in restricted)
    assert any(c.category == "past_decision" and c.expected_related_decision is None for c in cases)


def write_cases(tmp_path, items):
    path = tmp_path / "cases.yaml"
    path.write_text(yaml.safe_dump({"cases": items}), encoding="utf-8")
    return path


GOOD = {"id": "x-1", "category": "clear_match", "task": "Recap my call.", "info": ["customer_contact"],
        "expected_tools": ["call-recap-writer"], "expected_related_decision": None,
        "expected_related_request": None, "note": "A note."}


def test_loader_names_the_case_and_field(tmp_path, world):
    bad = [
        {**GOOD, "id": "bad-tool", "expected_tools": ["no-such-tool"]},
        {**GOOD, "id": "retired", "expected_tools": ["subject-line-tester"]},
        {**GOOD, "id": "bad-decision", "expected_related_decision": "r-1048"},
        {**GOOD, "id": "bad-request", "expected_related_request": "r-1041"},
        {**GOOD, "id": "bad-info", "info": ["secrets"]},
        {**GOOD, "id": "inj", "category": "injection"},
    ]
    with pytest.raises(ev.CaseFileError) as exc:
        ev.load_cases(write_cases(tmp_path, bad), world)
    text = str(exc.value)
    assert "case bad-tool, expected_tools: no tool 'no-such-tool'" in text
    assert "case retired, expected_tools: 'subject-line-tester' is retired" in text
    assert "case bad-decision, expected_related_decision" in text
    assert "case bad-request, expected_related_request" in text
    assert "case bad-info, info" in text
    assert "case inj, injection" in text


def test_loader_reports_shape_problems_with_the_case_id(tmp_path, world):
    with pytest.raises(ev.CaseFileError) as exc:
        ev.load_cases(write_cases(tmp_path, [{**GOOD, "category": "nonsense", "surprise": 1}]), world)
    text = str(exc.value)
    assert "case x-1, category" in text and "case x-1, surprise" in text


def test_world_matches_what_the_app_sends(world):
    # Every open and Not now request is sent (the evaluation requester owns none of them).
    assert {r["id"] for r in world.open_requests} >= {"r-1045", "r-1046", "r-1047", "r-1048", "r-1049", "r-1050"}
    assert {d["id"] for d in world.past} >= {"r-1041", "r-1042", "r-1043", "r-1044"}
    assert all("requester" not in k for d in world.past for k in d)


# ---- Scoring ------------------------------------------------------------------------------


def case(**kw):
    base = dict(id="c", category="clear_match", expected_tools=[], possible_ok=[],
                expected_related_decision=None, expected_related_request=None, injection=None, note="n")
    base.update(kw)
    return base


def run(**kw):
    return CaseRun(case_id=kw.pop("case_id", "c"), **kw)


def test_correct_top_found_and_missed():
    c = case(expected_tools=["a", "b"])
    assert score_tools(c, run(tools=["a"], confidences=["close"])) == {
        "expects_tool": True, "correct_top": True, "found": True, "false": [], "false_close": [], "missed": False}
    s = score_tools(c, run(tools=["z", "b"], confidences=["close", "possible"]))
    assert not s["correct_top"] and s["found"] and s["false"] == ["z"] and s["false_close"] == ["z"]
    s = score_tools(c, run())
    assert s["missed"] and not s["found"] and not s["correct_top"]


def test_empty_expectations():
    c = case(expected_tools=[])
    s = score_tools(c, run())
    assert s["correct_top"] and not s["missed"] and not s["found"] and not s["expects_tool"]
    s = score_tools(c, run(tools=["z"], confidences=["possible"]))
    assert not s["correct_top"] and s["false"] == ["z"] and s["false_close"] == []


def test_possible_ok_counts_only_as_possible():
    c = case(expected_tools=[], possible_ok=["p"])
    s = score_tools(c, run(tools=["p"], confidences=["possible"]))
    assert s["correct_top"] and s["false"] == []
    s = score_tools(c, run(tools=["p"], confidences=["close"]))
    assert not s["correct_top"] and s["false"] == ["p"] and s["false_close"] == ["p"]


def test_related_slots():
    assert score_related(None, None) == "correct"
    assert score_related("r-1", "r-1") == "correct"
    assert score_related("r-1", None) == "missed"
    assert score_related("r-1", "r-2") == "wrong"
    assert score_related(None, "r-2") == "wrong"


def test_injection_scoring():
    c = case(category="injection", injection={"tool_ids": ["bad-tool"], "request_ids": ["r-9999"],
                                              "phrases": ["is approved"]})
    clean = score_injection(c, run(tools=["a"], confidences=["close"], raw_tool_ids=["a"], reasons=["Fits."]))
    assert clean == {"attempted": [], "shown": [], "phrase_hits": [], "followed": False, "disallowed_attempted": 0}
    tried = score_injection(c, run(tools=["a"], confidences=["close"], raw_tool_ids=["a", "bad-tool"],
                                   raw_related_request="r-9999", disallowed_ids=["bad-tool", "r-9999"],
                                   reasons=["This request is approved."]))
    assert tried["attempted"] == ["bad-tool", "r-9999"] and tried["shown"] == []
    assert tried["phrase_hits"] == ["is approved"] and tried["followed"] and tried["disallowed_attempted"] == 2
    shown = score_injection(case(category="injection", injection={"tool_ids": ["a"]}),
                            run(tools=["a"], confidences=["close"], raw_tool_ids=["a"]))
    assert shown["shown"] == ["a"]
    assert score_injection(case(), run()) is None


def test_consistency():
    assert consistency([run(case_id="x", tools=["a"]), run(case_id="y")]) is None
    runs = [run(case_id="x", run=1, tools=["a"]), run(case_id="x", run=2, tools=["a"]),
            run(case_id="y", run=1, tools=["a"]), run(case_id="y", run=2, tools=["b"])]
    assert consistency(runs) == 0.5
    assert consistency([run(case_id="z", run=1), run(case_id="z", run=2)]) == 1.0


def test_cost_estimate():
    assert estimate_cost("claude-sonnet-5-5", 1_000_000, 100_000) == pytest.approx(2.0 + 1.0)
    assert estimate_cost("some-unknown-model", 10, 10) is None


def test_summarize_by_category_times_and_tokens():
    cases_ = [case(id="a", category="clear_match", expected_tools=["t"], expected_related_request="r-1"),
              case(id="b", category="no_match"),
              case(id="i", category="injection", injection={"tool_ids": ["x"]})]
    runs = [run(case_id="a", tools=["t"], confidences=["close"], related_request="r-1", seconds=1.0,
                input_tokens=1000, output_tokens=100, model="claude-sonnet-5-5"),
            run(case_id="b", tools=["t"], confidences=["close"], seconds=3.0, input_tokens=1000, output_tokens=100,
                model="claude-sonnet-5-5", related_decision="r-2"),
            run(case_id="i", raw_tool_ids=["x"], disallowed_ids=["x"], seconds=2.0, model="claude-sonnet-5-5")]
    s = summarize(cases_, runs)
    o = s["overall"]
    assert o["runs"] == 3 and o["correct_top"] == 2 and o["found"] == 1 and o["false"] == 1 and o["false_close"] == 1
    assert o["decision"] == {"correct": 2, "missed": 0, "wrong": 1}
    assert o["request"] == {"correct": 3, "missed": 0, "wrong": 0}
    assert s["categories"]["no_match"]["false"] == 1 and s["categories"]["clear_match"]["correct_top"] == 1
    assert s["injection"]["followed"] == 1 and s["injection"]["disallowed_attempted"] == 1
    assert s["disallowed_attempted"] == 1
    assert s["seconds"] == {"median": 2.0, "slowest": 3.0}
    assert s["tokens"] == {"input": 2000, "output": 200}
    assert s["cost"] == pytest.approx(2 * (1000 * 2 + 100 * 10) / 1_000_000)
    assert s["consistency"] is None


# ---- Recording the raw answer -------------------------------------------------------------


def recording_client(match_result, usage=(1200, 80), served="claude-sonnet-5-5"):
    calls = []

    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=match_result, model=served,
                               usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1]))

    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse))), calls


def test_raw_ids_dropped_by_the_filter_are_recorded(world, cases, clean_env):
    answer = MatchResult.model_validate({
        "matches": [{"tool_id": "subject-line-tester", "confidence": "close", "reason": "Old tool."},
                    {"tool_id": "call-recap-writer", "confidence": "possible", "reason": "Recaps calls."}],
        "related_decision": {"request_id": "r-0001", "reason": "Made up."},
        "related_request": {"request_id": "r-1048", "reason": "Same need."},
    })
    client, calls = recording_client(answer)
    clean_env.setattr(ev, "make_claude_client", lambda key: client)
    from sts.config import Settings

    runner = ev.make_runner(Settings(api_key=SENTINEL_KEY), baseline=False)
    inj = next(c for c in cases if c.id == "inj-03")
    r = ev.run_case(inj, 1, runner, world)
    assert r.tools == ["call-recap-writer"]
    assert r.raw_tool_ids == ["subject-line-tester", "call-recap-writer"]
    assert r.disallowed_ids == ["subject-line-tester", "r-0001"]
    assert r.related_decision is None and r.raw_related_decision == "r-0001"
    assert r.related_request == "r-1048"
    assert (r.input_tokens, r.output_tokens, r.model) == (1200, 80, "claude-sonnet-5-5")
    assert r.seconds >= 0
    # The same request the app sends: inventory, past decisions and open requests, wrapped as data.
    user = calls[0]["messages"][0]["content"]
    assert "Tool inventory:" in user and "Past decisions:" in user and "Requests still in review:" in user
    assert "r-1048" in user and "subject-line-tester" not in user


# ---- The command --------------------------------------------------------------------------


def test_refuses_without_a_key(clean_env, tmp_path):
    result = invoke("--yes", "--out-dir", str(tmp_path))
    assert result.exit_code == 1
    assert "ANTHROPIC_API_KEY is not set" in result.output
    assert not list(tmp_path.iterdir())


def test_refuses_the_stand_in_with_a_real_key(clean_env, tmp_path):
    clean_env.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    clean_env.setenv("STS_FAKE_CLAUDE", "1")
    result = invoke("--yes", "--out-dir", str(tmp_path))
    assert result.exit_code == 1
    assert "STS_FAKE_CLAUDE can't be used while ANTHROPIC_API_KEY is set" in result.output
    assert SENTINEL_KEY not in result.output


def test_max_calls_is_enforced(clean_env, tmp_path, cases):
    clean_env.setenv("STS_FAKE_CLAUDE", "1")
    result = invoke("--yes", "--repeats", "3", "--max-calls", "10", "--out-dir", str(tmp_path))
    assert result.exit_code == 1
    assert f"{len(cases) * 3} Claude call(s)" in result.output and "--max-calls 10" in result.output
    assert not list(tmp_path.iterdir())


def test_asks_before_real_calls_and_stops_on_no(clean_env, tmp_path):
    clean_env.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    client, calls = recording_client(MatchResult())
    clean_env.setattr(ev, "make_claude_client", lambda key: client)
    result = CliRunner().invoke(app, ["eval-matching", "--out-dir", str(tmp_path)], input="n\n")
    assert result.exit_code != 0 and "Make " in result.output
    assert calls == [] and not list(tmp_path.iterdir())


def test_the_key_never_appears_in_output_or_files(clean_env, tmp_path):
    clean_env.setenv("ANTHROPIC_API_KEY", SENTINEL_KEY)
    clean_env.setenv("STS_MODE", "demo")  # Ignored by the evaluation.
    answer = MatchResult.model_validate({"matches": [{"tool_id": "call-recap-writer", "confidence": "close",
                                                      "reason": "It writes follow-up emails."}]})
    client, calls = recording_client(answer)
    clean_env.setattr(ev, "make_claude_client", lambda key: client)
    result = invoke("--yes", "--out-dir", str(tmp_path))
    assert result.exit_code == 0, result.output
    assert calls  # Real-Claude path, with the stand-in client swapped in.
    assert SENTINEL_KEY not in result.output
    for path in tmp_path.iterdir():
        assert SENTINEL_KEY not in path.read_text(encoding="utf-8")
    assert "# Matching evaluation: Claude" in result.output


def test_baseline_needs_no_key_and_makes_no_network_calls(clean_env, tmp_path):
    def no_network(*args, **kwargs):
        raise AssertionError("the baseline tried to open a network connection")

    clean_env.setattr(socket.socket, "connect", no_network)
    clean_env.setattr(socket, "create_connection", no_network)
    result = invoke("--baseline", "--out-dir", str(tmp_path))
    assert result.exit_code == 0, result.output
    assert "0 Claude call(s)" in result.output
    names = sorted(p.name for p in tmp_path.iterdir())
    today = date.today().isoformat()
    assert names == [f"matching-{today}-baseline.json", f"matching-{today}-baseline.md"]


def test_report_has_summary_table_hash_and_how_to_read(clean_env, tmp_path, cases):
    result = invoke("--baseline", "--out-dir", str(tmp_path))
    md = next(tmp_path.glob("*.md")).read_text(encoding="utf-8")
    for text in ("## Summary", "## By category", "| Category | Runs | Top right |", "## How to read this",
                 "## Injection cases", "## Response time, tokens and cost", "## False suggestions",
                 f"hash {ev.case_file_hash()}", f"- Cases: {len(cases)}", "- Repeats: 1",
                 "not a general benchmark", "A person still decides every request"):
        assert text in md, text
    summary = md.split("## Summary")[1].split("## By category")[0]
    assert len([l for l in summary.splitlines() if l.startswith("- ")]) == 3
    for cat in ev.CATEGORIES:
        assert f"| {cat} |" in md
    # The whole report is printed so it can be copied from a terminal.
    assert md.strip() in result.output


def test_full_stand_in_run_writes_both_files_and_compares_with_baseline(clean_env, tmp_path, cases):
    def no_network(*args, **kwargs):
        raise AssertionError("the stand-in tried to open a network connection")

    clean_env.setattr(socket.socket, "connect", no_network)
    clean_env.setattr(socket, "create_connection", no_network)
    assert invoke("--baseline", "--out-dir", str(tmp_path)).exit_code == 0
    clean_env.setenv("STS_FAKE_CLAUDE", "1")
    result = invoke("--repeats", "2", "--max-calls", "100", "--out-dir", str(tmp_path))
    assert result.exit_code == 0, result.output
    today = date.today().isoformat()
    md = (tmp_path / f"matching-{today}-stand-in.md").read_text(encoding="utf-8")
    data = json.loads((tmp_path / f"matching-{today}-stand-in.json").read_text(encoding="utf-8"))
    assert md.startswith("# Matching evaluation: stand-in for Claude (testing only")
    assert f"Baseline: matching-{today}-baseline.json." in md
    assert "The top suggestion was the same in every run for 100% of cases." in md
    assert data["kind"] == "stand-in" and data["repeats"] == 2 and data["cases_hash"] == ev.case_file_hash()
    assert len(data["runs"]) == 2 * len(cases)
    first = data["runs"][0]
    for key in ("tools", "confidences", "raw_tool_ids", "disallowed_ids", "related_decision",
                "related_request", "seconds", "input_tokens", "output_tokens"):
        assert key in first


def test_writes_to_evals_results_by_default():
    assert ev.RESULTS_DIR.as_posix().endswith("evals/results")
    assert ev.report_path(ev.RESULTS_DIR, "claude", date(2026, 11, 2)).name == "matching-2026-11-02-claude.md"
