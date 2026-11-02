import shutil

import pytest

from sts.demo_data import DemoDataError, check_demo_data, load_demo_data

from .conftest import DEMO_DIR


def copy_demo(tmp_path):
    target = tmp_path / "demo"
    shutil.copytree(DEMO_DIR, target)
    return target


def test_demo_data_is_valid():
    assert check_demo_data(DEMO_DIR) == []
    data = load_demo_data(DEMO_DIR)
    assert len(data.tools) == 10 and len(data.requests) == 11
    assert {d.outcome for d in data.decisions} == {"approve", "approve_with_limits", "use_existing", "not_approved",
                                                   "not_now"}


def test_bad_tool_status_names_file_and_field(tmp_path):
    demo = copy_demo(tmp_path)
    p = demo / "tools.yaml"
    p.write_text(p.read_text().replace("status: retired", "status: gone", 1))
    problems = check_demo_data(demo)
    assert any(x.startswith("demo/tools.yaml, tools[9].status") for x in problems), problems


def test_missing_limits_is_explained(tmp_path):
    demo = copy_demo(tmp_path)
    p = demo / "tools.yaml"
    p.write_text(p.read_text().replace("    limits: Prices come from the price sheet, never typed in by hand.\n", "", 1))
    problems = check_demo_data(demo)
    assert any("demo/tools.yaml, tools[1]" in x and "limits is required" in x for x in problems), problems


def test_bad_recorded_match_names_file(tmp_path):
    demo = copy_demo(tmp_path)
    p = demo / "recorded" / "r-1048.json"
    p.write_text(p.read_text().replace('"confidence": "close"', '"confidence": "certain"'))
    problems = check_demo_data(demo)
    assert any(x.startswith("demo/recorded/r-1048.json, matches[0].confidence") for x in problems), problems


def test_unknown_tool_in_recorded_file(tmp_path):
    demo = copy_demo(tmp_path)
    p = demo / "recorded" / "r-1048.json"
    p.write_text(p.read_text().replace('"tool_id": "call-recap-writer"', '"tool_id": "ghost-tool"'))
    with pytest.raises(DemoDataError) as exc:
        load_demo_data(demo)
    assert "ghost-tool" in str(exc.value)


def test_broken_yaml_is_reported(tmp_path):
    demo = copy_demo(tmp_path)
    (demo / "requests.yaml").write_text("requests: [unclosed")
    assert any("demo/requests.yaml" in x and "not valid YAML" in x for x in check_demo_data(demo))


# ---- Demo dates are offsets from today --------------------------------------------

from datetime import date, timedelta  # noqa: E402

from sts.demo_data import relative_date  # noqa: E402
from sts.rules import needs_decision, ready_count, review_due, trial_ended  # noqa: E402


@pytest.mark.parametrize("text,expected", [
    ("today", date(2026, 11, 2)), ("yesterday", date(2026, 11, 1)), ("3 days ago", date(2026, 10, 30)),
    ("in 2 weeks", date(2026, 11, 16)), ("1 day ago", date(2026, 11, 1)), ("last month", date(2026, 10, 2)),
    ("in 4 months", date(2027, 3, 2)), ("In 1 Week", date(2026, 11, 9)),
])
def test_relative_dates(text, expected):
    assert relative_date(text, date(2026, 11, 2)) == expected


@pytest.mark.parametrize("today", [date(2026, 11, 2), date(2027, 6, 30), date.today()])
def test_demo_dates_are_relative_to_today(today):
    data = load_demo_data(DEMO_DIR, today=today)
    assert data.as_of == today
    reqs = {r.id: r for r in data.requests}
    tools = {t.id: t for t in data.tools}
    assert reqs["r-1048"].submitted_at.date() == today
    assert reqs["r-1047"].submitted_at.date() == today - timedelta(days=3)
    decided = {d.request_id: d for d in data.decisions}
    assert decided["r-1044"].decided_at.date() == today - timedelta(days=6)
    assert tools["translation-helper"].trial_ends == today + timedelta(days=14)
    assert tools["partner-outreach-drafts"].trial_ends == today - timedelta(days=3)
    assert tools["webinar-invite-writer"].journey[1]["date"] == (today - timedelta(days=90)).isoformat()
    # The examples look the same on any day.
    assert ready_count(tools["translation-helper"]) == 2
    assert ready_count(tools["partner-outreach-drafts"]) == 3
    assert trial_ended(tools["partner-outreach-drafts"], today)
    assert not trial_ended(tools["translation-helper"], today)
    assert review_due(tools["proposal-drafter"], today)
    flagged = [(i["tool"].id, i["flag"]) for i in needs_decision(data.tools, today)]
    assert flagged == [("partner-outreach-drafts", "trial_ended"), ("proposal-drafter", "review_due")]


def test_demo_files_have_no_fixed_dates():
    import re

    for path in [DEMO_DIR / "tools.yaml", DEMO_DIR / "requests.yaml"]:
        assert not re.search(r"\b20\d\d-\d\d-\d\d\b", path.read_text()), path


def test_fixed_date_in_demo_file_is_explained(tmp_path):
    demo = copy_demo(tmp_path)
    p = demo / "requests.yaml"
    p.write_text(p.read_text().replace("submitted_at: today", "submitted_at: 2026-11-02", 1))
    problems = check_demo_data(demo)
    assert any("requests[0].submitted_at" in x and "offset" in x for x in problems), problems


def test_bad_offset_is_explained(tmp_path):
    demo = copy_demo(tmp_path)
    p = demo / "tools.yaml"
    p.write_text(p.read_text().replace("trial_ends: in 2 weeks", "trial_ends: soonish", 1))
    problems = check_demo_data(demo)
    assert any("trial_ends" in x and "3 days ago" in x for x in problems), problems


def test_security_check_comes_from_the_decision_that_created_the_tool():
    tools = {t.id: t for t in load_demo_data(DEMO_DIR).tools}
    assert tools["proposal-drafter"].security_check == "done"  # r-1043's decision
    assert tools["webinar-invite-writer"].security_check == "not_needed"  # r-1041's decision
