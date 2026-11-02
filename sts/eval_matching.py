"""The matching evaluation: run the labeled cases through the app's match check and report.

The cases are in evals/matching_cases.yaml. Each case goes through the same provider function
the app uses for the match check (find_matches), with the same inventory, past decisions and
open requests the app would send, loaded from demo/ the same way the app loads them. The only
Claude call is still ClaudeProvider.find_matches in sts/provider.py; this module wraps the
client so it can also keep the raw answer (before the app's filter), the response time and the
token counts.

Measure, don't tune: nothing here changes how matching works. See evals/README.md.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import ROOT, Settings
from .demo_data import DemoData, load_demo_data
from .eval_scoring import PRICE_NOTE, CaseRun, summarize
from .matching import eligible_tools
from .models import INFO_KINDS
from .provider import ClaudeProvider, ClaudeUnavailable, DemoProvider
from .rules import open_requests_for_match, past_decisions_for_match
from .store import DemoStore

CASES_PATH = ROOT / "evals" / "matching_cases.yaml"
RESULTS_DIR = ROOT / "evals" / "results"
CATEGORIES = (
    "clear_match", "look_alike", "no_match", "restricted_tool", "in_pilot_tool",
    "retired_tool", "open_duplicate", "past_decision", "injection",
)
# Not a name in the demo data, so no open request is left out as "your own request".
EVAL_REQUESTER = "Evaluation requester"
Kind = Literal["claude", "baseline", "stand-in"]


# ---- The case file -----------------------------------------------------------------------


class Injection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_ids: list[str] = Field(default_factory=list)
    request_ids: list[str] = Field(default_factory=list)
    phrases: list[str] = Field(default_factory=list)


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    category: Literal[CATEGORIES]  # type: ignore[valid-type]
    task: str = Field(min_length=1)
    info: list[str] = Field(min_length=1)
    expected_tools: list[str]
    possible_ok: list[str] = Field(default_factory=list)
    expected_related_decision: Optional[str]
    expected_related_request: Optional[str]
    note: str = Field(min_length=1)
    injection: Optional[Injection] = None


class CasesFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Raised whenever a label changes; each change is listed under "Label changes" in evals/README.md.
    version: int = Field(ge=1)
    cases: list[Case] = Field(min_length=1)


class CaseFileError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


@dataclass
class World:
    """What the match check is sent: the same inventory, past decisions and open requests as the app."""

    inventory: list
    past: list[dict]
    open_requests: list[dict]


def load_world(demo_dir: Optional[Path] = None, data: Optional[DemoData] = None) -> World:
    data = data or load_demo_data(demo_dir or Settings().demo_dir)
    store = DemoStore(data)
    return World(
        inventory=store.list_tools(),
        past=past_decisions_for_match(store),
        open_requests=open_requests_for_match(store, EVAL_REQUESTER),
    )


def case_file_hash(path: Path = CASES_PATH) -> str:
    """The first 12 characters of the file's SHA-256, so a report can be tied to one version of the set."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def case_file_version(path: Path = CASES_PATH) -> int:
    """The case set's version number, from the version field at the top of the file."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return CasesFile.model_validate(raw).version


def load_cases(path: Path = CASES_PATH, world: Optional[World] = None) -> list[Case]:
    """Read and check the case file. Problems name the case and the field."""
    path = Path(path)
    name = path.name
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CaseFileError([f"{name}: can't be read ({exc.__class__.__name__})"])
    try:
        parsed = CasesFile.model_validate(raw)
    except ValidationError as exc:
        problems = []
        for err in exc.errors():
            loc = list(err["loc"])
            where = ""
            if len(loc) >= 2 and loc[0] == "cases" and isinstance(loc[1], int):
                items = (raw or {}).get("cases") or []
                cid = items[loc[1]].get("id") if loc[1] < len(items) and isinstance(items[loc[1]], dict) else None
                where = f"case {cid or '#' + str(loc[1] + 1)}"
                loc = loc[2:]
            field_name = ".".join(str(x) for x in loc) or "file"
            problems.append(f"{name}: {where + ', ' if where else ''}{field_name}: {err['msg']}")
        raise CaseFileError(problems)

    world = world or load_world()
    tools = {t.id: t for t in world.inventory}
    allowed = {t.id for t in eligible_tools(world.inventory)}
    past_ids = {d["id"] for d in world.past}
    open_ids = {r["id"] for r in world.open_requests}
    problems = []
    seen = set()
    for c in parsed.cases:
        where = f"{name}: case {c.id}"
        if c.id in seen:
            problems.append(f"{where}, id: used more than once")
        seen.add(c.id)
        for kind in c.info:
            if kind not in INFO_KINDS:
                problems.append(f"{where}, info: {kind!r} is not an information kind")
        for fname in ("expected_tools", "possible_ok"):
            for tid in getattr(c, fname):
                if tid not in tools:
                    problems.append(f"{where}, {fname}: no tool {tid!r} in the inventory")
                elif tid not in allowed:
                    problems.append(f"{where}, {fname}: {tid!r} is {tools[tid].status} and is never offered")
        overlap = set(c.expected_tools) & set(c.possible_ok)
        if overlap:
            problems.append(f"{where}, possible_ok: {sorted(overlap)} are already in expected_tools")
        if c.expected_related_decision and c.expected_related_decision not in past_ids:
            problems.append(f"{where}, expected_related_decision: {c.expected_related_decision!r} is not a decided request")
        if c.expected_related_request and c.expected_related_request not in open_ids:
            problems.append(f"{where}, expected_related_request: {c.expected_related_request!r} is not an open or Not now request")
        if (c.category == "injection") != (c.injection is not None):
            problems.append(f"{where}, injection: needed for injection cases, and only for them")
    if problems:
        raise CaseFileError(problems)
    return parsed.cases


# ---- Running -------------------------------------------------------------------------------


class _RecordingMessages:
    def __init__(self, inner: Any, log: list):
        self._inner = inner
        self._log = log

    def parse(self, **kwargs):
        response = self._inner.parse(**kwargs)
        self._log.append(response)
        return response


class RecordingClient:
    """Wraps a Claude client and keeps every response, so the raw answer and token counts can be read.

    It passes each call through unchanged. It never reads or stores the key.
    """

    def __init__(self, client: Any):
        self.responses: list = []
        self.beta = type("Beta", (), {})()
        self.beta.messages = _RecordingMessages(client.beta.messages, self.responses)


def make_claude_client(api_key: str) -> Any:
    import anthropic

    return anthropic.Anthropic(api_key=api_key)


@dataclass
class Runner:
    kind: Kind
    model: str
    find_matches: Callable[..., Any]
    recorder: Optional[RecordingClient] = None
    notes: list[str] = field(default_factory=list)


def make_runner(settings: Settings, baseline: bool) -> Runner:
    """The baseline word match, the stand-in for Claude, or real Claude. Ignores STS_MODE.

    Raises ValueError, with a message saying why, when the settings can't be used.
    """
    if baseline:
        demo = DemoProvider({}, [])  # No recordings, so every case uses the simple word match.
        return Runner("baseline", "word match", demo.find_matches)
    if settings.fake_claude:
        if settings.api_key:
            raise ValueError("STS_FAKE_CLAUDE can't be used while ANTHROPIC_API_KEY is set, so a real key is "
                             "never mixed with the stand-in. Unset one of them.")
        from .fake_claude import fake_client

        client, _ = fake_client()
        recorder = RecordingClient(client)
        claude = ClaudeProvider(api_key="", model=settings.model, client=recorder)
        return Runner("stand-in", "stand-in for Claude (no model)", claude.find_matches, recorder)
    if not settings.api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set. Run with --baseline for the word match (no key needed), "
                         "or see evals/README.md for running it with the key from Secret Manager.")
    recorder = RecordingClient(make_claude_client(settings.api_key))
    claude = ClaudeProvider(api_key=settings.api_key, model=settings.model, client=recorder)
    return Runner("claude", settings.model, claude.find_matches, recorder)


def _get(obj: Any, name: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def run_case(case: Case, run_no: int, runner: Runner, world: World) -> CaseRun:
    before = len(runner.recorder.responses) if runner.recorder else 0
    start = time.perf_counter()
    result = CaseRun(case_id=case.id, run=run_no, model=runner.model)
    try:
        outcome = runner.find_matches(case.task, case.info, world.inventory, world.past, world.open_requests)
    except ClaudeUnavailable as exc:
        result.seconds = time.perf_counter() - start
        result.error = str(exc) or "Claude could not answer"
        return result
    result.seconds = time.perf_counter() - start
    result.tools = [m["tool_id"] for m in outcome.matches]
    result.confidences = [m["confidence"] for m in outcome.matches]
    result.reasons = [m.get("reason", "") for m in outcome.matches]
    result.related_decision = (outcome.related or {}).get("request_id")
    result.related_request = (outcome.related_request or {}).get("request_id")
    for rel in (outcome.related, outcome.related_request):
        if rel and rel.get("reason"):
            result.reasons.append(rel["reason"])

    response = runner.recorder.responses[-1] if runner.recorder and len(runner.recorder.responses) > before else None
    if response is None:
        # The word match: nothing is filtered, so the raw answer is what came back.
        result.raw_tool_ids = list(result.tools)
        result.raw_related_decision = result.related_decision
        result.raw_related_request = result.related_request
        return result
    parsed = _get(response, "parsed_output")
    raw_matches = list(_get(parsed, "matches", []) or [])
    result.raw_tool_ids = [str(_get(m, "tool_id", "")) for m in raw_matches]
    result.raw_related_decision = _get(_get(parsed, "related_decision"), "request_id")
    result.raw_related_request = _get(_get(parsed, "related_request"), "request_id")
    for m in raw_matches:
        reason = str(_get(m, "reason", "") or "")
        if reason and reason not in result.reasons:
            result.reasons.append(reason)
    for rel in (_get(parsed, "related_decision"), _get(parsed, "related_request")):
        reason = str(_get(rel, "reason", "") or "")
        if reason and reason not in result.reasons:
            result.reasons.append(reason)
    allowed_tools = {t.id for t in eligible_tools(world.inventory)}
    result.disallowed_ids = [t for t in result.raw_tool_ids if t not in allowed_tools]
    if result.raw_related_decision and result.raw_related_decision not in {d["id"] for d in world.past}:
        result.disallowed_ids.append(result.raw_related_decision)
    if result.raw_related_request and result.raw_related_request not in {r["id"] for r in world.open_requests}:
        result.disallowed_ids.append(result.raw_related_request)
    usage = _get(response, "usage")
    result.input_tokens = int(_get(usage, "input_tokens", 0) or 0)
    result.output_tokens = int(_get(usage, "output_tokens", 0) or 0)
    served = _get(response, "model")
    if isinstance(served, str) and served:
        result.model = served
    return result


def run_all(cases: list[Case], runner: Runner, world: World, repeats: int = 1,
            progress: Optional[Callable[[str], None]] = None) -> list[CaseRun]:
    runs = []
    for n in range(1, repeats + 1):
        for case in cases:
            runs.append(run_case(case, n, runner, world))
            if progress:
                progress(f"  {case.id} run {n}: {', '.join(runs[-1].tools) or 'no tool'}")
    return runs


# ---- The report ----------------------------------------------------------------------------

HOW_TO_READ = """## How to read this

- The set is small (about 30 cases) and was written by the person who built the app, so it reflects their judgment about what should match. Read the notes, and change a label only if it is wrong.
- These results come from a few runs on one day. Claude's answers can vary from run to run; use `--repeats` to see how much.
- It measures this app's matching against this one fictional inventory and set of requests. It is not a general benchmark of Claude or of any other app.
- A person still decides every request. A wrong suggestion costs the requester a look at a tool that doesn't fit, and the reviewer still checks."""


LABEL_CHANGES_LINE = '- Label changes: see "Label changes" in evals/README.md for every label changed and why.'


def _frac(n: int, d: int) -> str:
    return f"{n} of {d} ({round(100 * n / d)}%)" if d else "none"


def _pct(n: int, d: int) -> str:
    return f"{round(100 * n / d)}%" if d else "n/a"


def report_path(out_dir: Path, kind: Kind, today: date, version: Optional[int] = None) -> Path:
    """matching-<date>-v<version>-<kind>.md. Reports from before the case set had a version have no -v part."""
    tag = f"v{version}-" if version is not None else ""
    return Path(out_dir) / f"matching-{today.isoformat()}-{tag}{kind}.md"


def find_baseline(out_dir: Path, cases_hash: str) -> Optional[dict]:
    """The newest baseline results with the same case set, if any."""
    for path in sorted(Path(out_dir).glob("matching-*-baseline.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("cases_hash") == cases_hash:
            data["_file"] = path.name
            return data
    return None


def _title(kind: Kind) -> str:
    return {
        "claude": "Matching evaluation: Claude",
        "baseline": "Matching evaluation: baseline word match",
        "stand-in": "Matching evaluation: stand-in for Claude (testing only, not real results)",
    }[kind]


def build_report(cases: list[Case], runs: list[CaseRun], summary: dict, *, kind: Kind, model: str,
                 repeats: int, cases_hash: str, today: date, baseline: Optional[dict] = None,
                 cases_version: Optional[int] = None) -> str:
    by_id = {c.id: c for c in cases}
    o = summary["overall"]
    lines = [f"# {_title(kind)}", ""]
    lines += [
        f"- Date: {today.isoformat()}",
        f"- Model: {model}",
        f"- Cases: {len(cases)}",
        f"- Repeats: {repeats}",
        f"- Case set: evals/matching_cases.yaml, "
        f"{'version ' + str(cases_version) + ', ' if cases_version is not None else ''}hash {cases_hash}",
        LABEL_CHANGES_LINE,
        "",
        "## Summary",
        "",
        f"- Top suggestion right in {_frac(o['correct_top'], o['runs'])} runs; an expected tool was found "
        f"in {_frac(o['found'], o['expects_tool'])} runs that needed one.",
        f"- {o['false']} false suggestions ({o['false_close']} called a close match) and {o['missed']} misses "
        f"where a tool was expected and none was suggested.",
        f"- Asked before right in {_frac(o['decision']['correct'], o['runs'])} runs; I need this too right in "
        f"{_frac(o['request']['correct'], o['runs'])} runs.",
    ]
    if o["errors"]:
        lines.append(f"- {o['errors']} runs had no answer from Claude and count as no suggestion.")
    lines += ["", "## By category", "",
              "| Category | Runs | Top right | Found | False (close) | Missed | Decision right | Request right |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for cat, t in list(summary["categories"].items()) + [("all", o)]:
        name = "**All**" if cat == "all" else cat
        found = _pct(t["found"], t["expects_tool"]) if t["expects_tool"] else "n/a"
        lines.append(
            f"| {name} | {t['runs']} | {_pct(t['correct_top'], t['runs'])} | {found} | {t['false']} ({t['false_close']}) "
            f"| {t['missed']} | {_pct(t['decision']['correct'], t['runs'])} | {_pct(t['request']['correct'], t['runs'])} |"
        )
    lines += ["", "Related slots in detail (all runs):", "",
              "| Slot | Correct | Missed | Wrongly suggested |", "| --- | --- | --- | --- |",
              f"| Asked before (past decision) | {o['decision']['correct']} | {o['decision']['missed']} | {o['decision']['wrong']} |",
              f"| I need this too (open request) | {o['request']['correct']} | {o['request']['missed']} | {o['request']['wrong']} |"]

    lines += ["", "## Compared with the baseline word match", ""]
    if kind == "baseline":
        lines.append("This is the baseline.")
    elif baseline is None:
        lines.append("No baseline report for this case set was found. Run `sts eval-matching --baseline` to make one.")
    else:
        b = baseline["summary"]["overall"]
        lines += [f"Baseline: {baseline['_file']}.", "",
                  "| Measure | This run | Baseline |", "| --- | --- | --- |",
                  f"| Top suggestion right | {_pct(o['correct_top'], o['runs'])} | {_pct(b['correct_top'], b['runs'])} |",
                  f"| Expected tool found | {_pct(o['found'], o['expects_tool'])} | {_pct(b['found'], b['expects_tool'])} |",
                  f"| False suggestions | {o['false']} | {b['false']} |",
                  f"| Misses | {o['missed']} | {b['missed']} |",
                  f"| Asked before right | {_pct(o['decision']['correct'], o['runs'])} | {_pct(b['decision']['correct'], b['runs'])} |",
                  f"| I need this too right | {_pct(o['request']['correct'], o['runs'])} | {_pct(b['request']['correct'], b['runs'])} |",
                  "", "| Category | Top right here | Top right baseline |", "| --- | --- | --- |"]
        for cat, t in summary["categories"].items():
            bt = baseline["summary"]["categories"].get(cat)
            lines.append(f"| {cat} | {_pct(t['correct_top'], t['runs'])} | "
                         f"{_pct(bt['correct_top'], bt['runs']) if bt else 'n/a'} |")

    run_by_key = {(r.case_id, r.run): r for r in runs}
    misses, falses, related_wrong = [], [], []
    for s in summary["scored"]:
        c = by_id[s["case_id"]]
        r = run_by_key[(s["case_id"], s["run"])]
        tag = f"**{c.id}** ({c.category}, run {s['run']})"
        got = ", ".join(f"{t} ({conf})" for t, conf in zip(r.tools, r.confidences)) or "nothing"
        if not s["tools"]["correct_top"] or s["tools"]["missed"]:
            misses.append(f"- {tag}: expected {', '.join(c.expected_tools) or 'no tool'}, got {got}. {c.note}")
        if s["tools"]["false"]:
            close = f" ({len(s['tools']['false_close'])} close)" if s["tools"]["false_close"] else ""
            falses.append(f"- {tag}: suggested {', '.join(s['tools']['false'])}{close}. {c.note}")
        for slot, exp, got_rel in (("decision", c.expected_related_decision, r.related_decision),
                                   ("request", c.expected_related_request, r.related_request)):
            if s[slot] != "correct":
                label = "Asked before" if slot == "decision" else "I need this too"
                related_wrong.append(f"- {tag}: {label} expected {exp or 'none'}, got {got_rel or 'none'}. {c.note}")
    lines += ["", "## Wrong top suggestions and misses", ""] + (misses or ["None."])
    lines += ["", "## False suggestions", ""] + (falses or ["None."])
    lines += ["", "## Wrong or missed related requests and decisions", ""] + (related_wrong or ["None."])

    inj = summary["injection"]
    lines += ["", "## Injection cases", "",
              f"Injected text was followed in {_frac(inj['followed'], inj['runs'])} injection runs, and an injected "
              f"id reached the screen in {inj['shown']}. Across all runs, {summary['disallowed_attempted']} ids "
              f"came back that the app's filter removed ({inj['disallowed_attempted']} of them in injection cases).", "",
              "| Case | Run | Injected ids in the raw answer | Reached the screen | Phrases found | Ids the filter removed |",
              "| --- | --- | --- | --- | --- | --- |"]
    for d in inj["details"]:
        lines.append(f"| {d['case_id']} | {d['run']} | {', '.join(d['attempted']) or 'none'} | "
                     f"{', '.join(d['shown']) or 'none'} | {', '.join(d['phrase_hits']) or 'none'} | {d['disallowed_attempted']} |")

    sec = summary["seconds"]
    tok = summary["tokens"]
    cost = summary["cost"]
    cost_text = "no price on file for this model" if cost is None else f"${cost:.4f} ({PRICE_NOTE})"
    lines += ["", "## Consistency", ""]
    if summary["consistency"] is None:
        lines.append("One run per case, so consistency wasn't measured. Use `--repeats 3` to measure it.")
    else:
        lines.append(f"The top suggestion was the same in every run for {round(100 * summary['consistency'])}% of cases.")
    lines += ["", "## Response time, tokens and cost", "",
              f"- Response time: median {sec['median']:.2f} seconds, slowest {sec['slowest']:.2f} seconds."]
    if kind == "baseline":
        lines.append("- No Claude calls, so no tokens and no cost.")
    else:
        lines += [f"- Tokens: {tok['input']:,} input, {tok['output']:,} output.",
                  f"- Estimated cost: {cost_text}."]
    lines += ["", HOW_TO_READ, ""]
    return "\n".join(lines)


def write_results(out_dir: Path, kind: Kind, today: date, markdown: str, payload: dict,
                  version: Optional[int] = None) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = report_path(out_dir, kind, today, version)
    js = md.with_suffix(".json")
    md.write_text(markdown, encoding="utf-8")
    js.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    return md, js


def evaluate(cases: list[Case], runner: Runner, world: World, *, repeats: int, out_dir: Path,
             cases_hash: str, cases_version: Optional[int] = None, today: Optional[date] = None,
             progress: Optional[Callable[[str], None]] = None) -> tuple[str, Path, Path]:
    today = today or date.today()
    runs = run_all(cases, runner, world, repeats, progress)
    summary = summarize(cases, runs)
    baseline = None if runner.kind == "baseline" else find_baseline(out_dir, cases_hash)
    markdown = build_report(cases, runs, summary, kind=runner.kind, model=runner.model, repeats=repeats,
                            cases_hash=cases_hash, today=today, baseline=baseline, cases_version=cases_version)
    payload = {
        "title": _title(runner.kind),
        "kind": runner.kind,
        "date": today.isoformat(),
        "model": runner.model,
        "repeats": repeats,
        "cases_hash": cases_hash,
        "cases_version": cases_version,
        "cases": [c.model_dump() for c in cases],
        "runs": [r.to_dict() for r in runs],
        "summary": {k: v for k, v in summary.items() if k != "scored"},
        "scored": summary["scored"],
    }
    md, js = write_results(out_dir, runner.kind, today, markdown, payload, cases_version)
    return markdown, md, js
