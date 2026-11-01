"""The ready to ship check, extending, retiring, reviews and each tool's journey."""

from datetime import date, datetime, timedelta

import pytest

from sts.models import Request, Tool
from sts.rules import (
    MSG_STOPPED,
    DecisionForm,
    NewTool,
    ToolChangeError,
    build_new_tool,
    can_ship,
    extend_trial,
    mark_reviewed,
    needs_decision,
    ready_count,
    record_security_check,
    retire_tool,
    review_due,
    save_ready_answers,
    ship_tool,
    trial_ended,
    valid_test_link,
)

TODAY = date(2026, 11, 2)


def tried(**kw) -> Tool:
    data = dict(id="t", name="Test Tool", purpose="Does a thing.", owner_name="Ana", owner_team="Marketing",
                teams=["Marketing"], status="being_tried", allowed_info=["public_only"],
                trial_ends=TODAY + timedelta(days=10), owner_agreed=True, security_check="not_needed",
                ready_check={}, journey=[])
    data.update(kw)
    return Tool(**data)


def approved(**kw) -> Tool:
    data = dict(status="approved", trial_ends=None, next_review="October 2026")
    data.update(kw)
    return tried(**data)


def answer(tool, kept="regularly", wrong="Nothing", tested="Ran it on ten real briefs.", link=""):
    save_ready_answers(tool, kept, wrong, tested, link)
    return tool


def kinds(tool):
    return [e["kind"] for e in tool.journey]


# ---- Ship it: the promotion gate ----------------------------------------------------


def test_ship_it_blocked_until_all_four_items_are_done():
    tool = tried(owner_agreed=False, security_check="needed")
    assert ready_count(tool) == 0
    with pytest.raises(ToolChangeError, match="0 of 4 ready"):
        ship_tool(tool, "approved", today=TODAY)
    tool.owner_agreed = True
    with pytest.raises(ToolChangeError, match="1 of 4 ready"):
        ship_tool(tool, "approved", today=TODAY)
    record_security_check(tool, True, TODAY, "Checked by security.", TODAY)
    with pytest.raises(ToolChangeError, match="2 of 4 ready"):
        ship_tool(tool, "approved", today=TODAY)
    save_ready_answers(tool, "sometimes", "Nothing", "", "")
    with pytest.raises(ToolChangeError, match="3 of 4 ready"):
        ship_tool(tool, "approved", today=TODAY)
    assert tool.status == "being_tried" and not can_ship(tool)
    save_ready_answers(tool, "sometimes", "Nothing", "Ran it on ten real briefs.", "")
    assert can_ship(tool)
    ship_tool(tool, "approved", today=TODAY)
    assert tool.status == "approved"


def test_kept_using_needs_the_anything_go_wrong_answer():
    tool = tried()
    with pytest.raises(ToolChangeError) as exc:
        save_ready_answers(tool, "regularly", "", "", "")
    assert "went_wrong" in exc.value.errors
    assert "Nothing" in exc.value.errors["went_wrong"]
    with pytest.raises(ToolChangeError) as exc:
        save_ready_answers(tool, "", "It broke once.", "", "")
    assert "kept_using" in exc.value.errors
    assert ready_count(tool) == 2


def test_no_approval_when_the_team_stopped_using_it():
    tool = answer(tried(), kept="stopped", wrong="Nobody opened it after week two.")
    assert ready_count(tool) == 3 and not can_ship(tool)
    for status in ("approved", "approved_with_limits"):
        with pytest.raises(ToolChangeError) as exc:
            ship_tool(tool, status, "Only public pages.", today=TODAY)
        assert str(exc.value) == MSG_STOPPED
    assert MSG_STOPPED == "A tool the team stopped using isn't ready to ship. Extend the trial or retire it."
    # Extend and retire are still open.
    extend_trial(tool, TODAY + timedelta(days=20), TODAY)
    retire_tool(tool, "The team stopped using it.", today=TODAY)
    assert tool.status == "retired"


def test_limits_required_for_approved_with_limits():
    tool = answer(tried())
    with pytest.raises(ToolChangeError, match="limits"):
        ship_tool(tool, "approved_with_limits", "   ", today=TODAY)
    with pytest.raises(ToolChangeError):
        ship_tool(tool, "retired", today=TODAY)
    ship_tool(tool, "approved_with_limits", "Public pages only.", today=TODAY)
    assert tool.status == "approved_with_limits" and tool.limits == "Public pages only."


def test_only_being_tried_tools_ship():
    with pytest.raises(ToolChangeError):
        ship_tool(answer(tried()).model_copy(update={"status": "approved"}), "approved", today=TODAY)


@pytest.mark.parametrize("link", ["https://example.com/results", "http://tests.northstar.example/run/8"])
def test_test_result_links_accept_http_and_https(link):
    assert valid_test_link(link)
    tool = answer(tried(), link=link)
    assert tool.ready_check["test_link"] == link and ready_count(tool) == 4


@pytest.mark.parametrize("link", ["ftp://example.com/results", "javascript:alert(1)", "www.example.com",
                                  "https://", "file:///etc/passwd", "mailto:a@example.com",
                                  "https://exa mple.com"])
def test_test_result_links_reject_anything_else(link):
    assert not valid_test_link(link)
    with pytest.raises(ToolChangeError) as exc:
        answer(tried(), link=link)
    assert "test_link" in exc.value.errors


def test_security_check_can_be_recorded_on_the_tool():
    tool = tried(security_check="needed")
    with pytest.raises(ToolChangeError) as exc:
        record_security_check(tool, False, None, "", TODAY)
    assert {"security_done", "security_date", "security_note"} <= set(exc.value.errors)
    with pytest.raises(ToolChangeError) as exc:
        record_security_check(tool, True, TODAY + timedelta(days=1), "Fine.", TODAY)
    assert "security_date" in exc.value.errors
    record_security_check(tool, True, TODAY - timedelta(days=2), "Checked how notes are stored.", TODAY)
    assert tool.security_check == "done"
    assert tool.ready_check["security_note"] == "Checked how notes are stored."
    with pytest.raises(ToolChangeError):
        record_security_check(tool, True, TODAY, "Again.", TODAY)


# ---- Extend the trial ------------------------------------------------------------------


def test_trial_extended_only_once_and_by_no_more_than_60_days():
    tool = tried()
    end = tool.trial_ends
    with pytest.raises(ToolChangeError, match="60 days"):
        extend_trial(tool, end + timedelta(days=61), TODAY)
    with pytest.raises(ToolChangeError, match="after the current end date"):
        extend_trial(tool, end, TODAY)
    with pytest.raises(ToolChangeError):
        extend_trial(tool, None, TODAY)
    extend_trial(tool, end + timedelta(days=60), TODAY)
    assert tool.trial_ends == end + timedelta(days=60) and tool.trial_extended
    with pytest.raises(ToolChangeError, match="already extended once"):
        extend_trial(tool, tool.trial_ends + timedelta(days=1), TODAY)


def test_ended_trial_can_be_extended_to_a_future_date():
    tool = tried(trial_ends=TODAY - timedelta(days=3))
    with pytest.raises(ToolChangeError, match="after today"):
        extend_trial(tool, TODAY, TODAY)
    extend_trial(tool, TODAY + timedelta(days=30), TODAY)
    assert not trial_ended(tool, TODAY)


def test_only_being_tried_tools_can_be_extended():
    with pytest.raises(ToolChangeError):
        extend_trial(approved(), TODAY + timedelta(days=5), TODAY)


# ---- Retire -------------------------------------------------------------------------------


@pytest.mark.parametrize("reason", ["", "   ", "\n"])
def test_retire_needs_a_reason(reason):
    tool = tried()
    with pytest.raises(ToolChangeError) as exc:
        retire_tool(tool, reason, today=TODAY)
    assert "retire_reason" in exc.value.errors and tool.status == "being_tried"


def test_retire_works_at_any_status_and_keeps_one_line():
    for tool in (tried(), approved(), approved().model_copy(update={"status": "approved_with_limits"})):
        retire_tool(tool, "Replaced by a\nnewer tool.", today=TODAY)
        assert tool.status == "retired"
        assert tool.journey[-1]["note"] == "Replaced by a newer tool."
    with pytest.raises(ToolChangeError):
        retire_tool(tool, "Again.", today=TODAY)


# ---- Trial ended and Review due -------------------------------------------------------------


@pytest.mark.parametrize("offset,ended", [(-30, True), (-1, True), (0, False), (1, False)])
def test_trial_ended_at_the_date_edges(offset, ended):
    tool = tried(trial_ends=TODAY + timedelta(days=offset))
    assert trial_ended(tool, TODAY) is ended


def test_trial_ended_only_for_being_tried():
    assert not trial_ended(approved(trial_ends=TODAY - timedelta(days=5)), TODAY)


@pytest.mark.parametrize("month,due", [
    ("September 2026", True), ("October 2026", True), ("November 2026", False), ("December 2026", False),
    ("2026-10", True), ("2026-11", False), ("not a month", False), (None, False),
])
def test_review_due_at_the_month_edges(month, due):
    assert review_due(approved().model_copy(update={"next_review": month}), TODAY) is due


def test_review_due_on_the_first_and_last_day_of_a_month():
    tool = approved().model_copy(update={"next_review": "November 2026"})
    assert not review_due(tool, date(2026, 11, 1))
    assert not review_due(tool, date(2026, 11, 30))
    assert review_due(tool, date(2026, 12, 1))
    assert review_due(approved().model_copy(update={"next_review": "December 2026"}), date(2027, 1, 1))


def test_review_due_only_for_approved_tools():
    assert not review_due(tried(next_review="January 2020"), TODAY)
    assert not review_due(approved().model_copy(update={"status": "retired"}), TODAY)


def test_needs_decision_lines():
    tools = [tried(id="a", name="A", teams=["Partnerships"], trial_ends=TODAY - timedelta(days=3)),
             tried(id="b", name="B", trial_ends=TODAY),
             approved(id="c", name="C", owner_name="Marcus Bell", owner_team="Sales Operations")]
    items = needs_decision(tools, TODAY)
    assert [(i["tool"].id, i["flag"]) for i in items] == [("a", "trial_ended"), ("c", "review_due")]
    assert items[0]["line"] == "Being tried by Partnerships. Trial ended 3 days ago."
    assert items[1]["line"] == "Approved. Owner Marcus Bell, Sales Operations. Review was due in October 2026."
    tools[0].trial_ends = TODAY - timedelta(days=1)
    assert needs_decision(tools, TODAY)[0]["line"].endswith("Trial ended yesterday.")


# ---- Mark reviewed ----------------------------------------------------------------------------


def test_mark_reviewed_sets_the_next_review_six_months_later_by_default():
    tool = approved()
    assert review_due(tool, TODAY)
    mark_reviewed(tool, "yes", "", None, TODAY)
    assert tool.next_review == "May 2027"
    assert not review_due(tool, TODAY)
    assert tool.journey[-1] == {"kind": "reviewed", "date": "2026-11-02", "note": "Still in use: Yes."}


def test_mark_reviewed_with_a_chosen_month_and_a_change():
    tool = approved()
    mark_reviewed(tool, "no", "Move it to the Sales team.", date(2027, 2, 1), TODAY)
    assert tool.next_review == "February 2027"
    assert tool.journey[-1]["note"] == "Still in use: No. To change: Move it to the Sales team."


def test_mark_reviewed_needs_an_answer_and_a_later_month():
    with pytest.raises(ToolChangeError) as exc:
        mark_reviewed(approved(), "", "", None, TODAY)
    assert "still_in_use" in exc.value.errors
    with pytest.raises(ToolChangeError) as exc:
        mark_reviewed(approved(), "yes", "", date(2026, 11, 1), TODAY)
    assert "next_review_month" in exc.value.errors
    with pytest.raises(ToolChangeError):
        mark_reviewed(tried(), "yes", "", None, TODAY)


# ---- Journey ------------------------------------------------------------------------------------


def test_journey_events_are_added_for_each_change():
    req = Request(id="r-9", title="Recaps", task="Write recaps", team="Marketing", how_often="rarely",
                  who_uses="just_me", requester_name="Sam", submitted_at=datetime(2026, 10, 1, 9))
    form = DecisionForm(outcome="approve", new_tool=NewTool(
        name="Recap Tool", purpose="Writes recaps.", owner_name="Dana", owner_team="Marketing",
        owner_agreed=True, allowed_info=["public_only"], trial_ends=TODAY + timedelta(days=10)))
    tool = build_new_tool(form, req, set(), TODAY)
    assert kinds(tool) == ["requested", "being_tried"]
    assert tool.journey[0]["date"] == "2026-10-01" and tool.journey[1]["date"] == "2026-11-02"
    assert tool.security_check == "not_needed" and tool.ready_check == {}

    tool.security_check = "needed"
    record_security_check(tool, True, TODAY, "Checked.", TODAY)
    extend_trial(tool, tool.trial_ends + timedelta(days=14), TODAY)
    answer(tool)
    ship_tool(tool, "approved", today=TODAY)
    mark_reviewed(tool, "yes", "", None, TODAY)
    retire_tool(tool, "Not used any more.", today=TODAY)
    assert kinds(tool) == ["requested", "being_tried", "security_done", "extended", "shipped", "reviewed", "retired"]
    assert all(e["date"] for e in tool.journey)


def test_failed_changes_add_no_journey_events():
    tool = tried()
    for change in (lambda: ship_tool(tool, "approved", today=TODAY),
                   lambda: extend_trial(tool, TODAY + timedelta(days=500), TODAY),
                   lambda: retire_tool(tool, "", today=TODAY)):
        with pytest.raises(ToolChangeError):
            change()
    assert tool.journey == []
