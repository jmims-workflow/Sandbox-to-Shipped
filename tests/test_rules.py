from datetime import date, datetime

import pytest

from sts.demo_data import load_demo_data
from sts.rules import (
    MSG_SECURITY,
    MSG_SENDS_WARNING,
    Checklist,
    DecisionForm,
    NewTool,
    ToolChangeError,
    build_decision,
    build_new_tool,
    copy_request_fields,
    prefill_checklist,
    retire_tool,
    ship_tool,
    validate_decision,
    warnings_for,
)

from .conftest import DEMO_DIR

DATA = load_demo_data(DEMO_DIR)
TOOLS = DATA.tools
REQ = {r.id: r for r in DATA.requests}


def good_checklist(**kw):
    c = Checklist(already_exists="no", sends_without_check="no", uses_customer_details="no", security_check="not_needed")
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def new_tool(**kw):
    nt = NewTool(name="Recap Tool", purpose="Writes recaps.", owner_name="Dana", owner_team="Sales Enablement",
                 owner_agreed=True, allowed_info=["public_only"], trial_ends=date(2027, 1, 1))
    for k, v in kw.items():
        setattr(nt, k, v)
    return nt


def form(**kw):
    f = DecisionForm(outcome="not_approved", checklist=good_checklist(), reason="Because.",
                     what_would_change="A drafted version.", new_tool=new_tool())
    for k, v in kw.items():
        setattr(f, k, v)
    return f


def test_valid_decision_has_no_errors():
    assert validate_decision(form(), TOOLS) == {}


@pytest.mark.parametrize("field", ["outcome", "reason", "what_would_change"])
def test_outcome_reason_and_change_are_required(field):
    errors = validate_decision(form(**{field: ""}), TOOLS)
    assert field in errors


def test_checklist_must_be_answered():
    errors = validate_decision(form(checklist=Checklist()), TOOLS)
    assert {"already_exists", "sends_without_check", "uses_customer_details"} <= set(errors)


def test_use_existing_requires_a_tool_from_the_inventory():
    assert "existing_tool_id" in validate_decision(form(outcome="use_existing"), TOOLS)
    assert "existing_tool_id" in validate_decision(form(outcome="use_existing", existing_tool_id="nope"), TOOLS)
    assert "existing_tool_id" in validate_decision(
        form(outcome="use_existing", existing_tool_id="subject-line-tester"), TOOLS
    )
    assert validate_decision(form(outcome="use_existing", existing_tool_id="call-recap-writer"), TOOLS) == {}


def test_approve_with_limits_requires_limits():
    assert "limits" in validate_decision(form(outcome="approve_with_limits"), TOOLS)
    assert validate_decision(form(outcome="approve_with_limits", limits="Only public pages."), TOOLS) == {}


@pytest.mark.parametrize("outcome", ["approve", "approve_with_limits"])
def test_approval_blocked_while_security_check_needed(outcome):
    f = form(outcome=outcome, limits="x", checklist=good_checklist(security_check="needed"))
    assert validate_decision(f, TOOLS)["security_check"] == MSG_SECURITY
    f.checklist.security_check = "done"
    assert validate_decision(f, TOOLS) == {}


def test_not_approved_is_allowed_while_security_check_needed():
    f = form(checklist=good_checklist(security_check="needed"))
    assert validate_decision(f, TOOLS) == {}


@pytest.mark.parametrize("outcome", ["approve", "approve_with_limits"])
def test_approval_requires_owner_agreement(outcome):
    f = form(outcome=outcome, limits="x", new_tool=new_tool(owner_agreed=False))
    assert "owner_agreed" in validate_decision(f, TOOLS)


def test_sends_without_check_warns_but_does_not_block():
    f = form(outcome="approve", checklist=good_checklist(sends_without_check="yes"))
    assert warnings_for(f) == [MSG_SENDS_WARNING]
    assert validate_decision(f, TOOLS) == {}
    assert warnings_for(form()) == []


def test_text_limit_applies_to_reason():
    errors = validate_decision(form(reason="x" * 5001), TOOLS)
    assert "5,000" in errors["reason"]


def test_new_tools_start_as_being_tried():
    f = form(outcome="approve")
    tool = build_new_tool(f, REQ["r-1048"], {t.id for t in TOOLS})
    assert tool.status == "being_tried"
    assert tool.from_request == "r-1048"
    assert tool.trial_ends == date(2027, 1, 1)
    f = form(outcome="approve_with_limits", limits="Prices from the sheet.")
    assert build_new_tool(f, REQ["r-1048"], set()).status == "being_tried"


def test_new_tool_ids_do_not_clash():
    f = form(outcome="approve", new_tool=new_tool(name="Call Recap Writer"))
    assert build_new_tool(f, REQ["r-1048"], {"call-recap-writer"}).id == "call-recap-writer-2"


def test_decision_tracks_claude_draft_and_edits():
    f = form(reason="Edited text.", drafted_reason="Drafted text.")
    d = build_decision(f, REQ["r-1048"], "Jordan Ellis", datetime(2026, 11, 2))
    assert d.reason_drafted_by_claude and d.reason_edited
    f = form(reason="Drafted text.", drafted_reason="Drafted text.")
    d = build_decision(f, REQ["r-1048"], "Jordan Ellis", datetime(2026, 11, 2))
    assert d.reason_drafted_by_claude and not d.reason_edited


READY_ANSWERS = {"kept_using": "regularly", "went_wrong": "Nothing", "how_tested": "Tried it on ten pages."}


def test_ship_it():
    tool = next(t for t in TOOLS if t.id == "translation-helper").model_copy(deep=True)
    tool.ready_check = dict(READY_ANSWERS)
    ship_tool(tool, "approved")
    assert tool.status == "approved" and tool.trial_ends is None
    tool = next(t for t in TOOLS if t.id == "partner-outreach-drafts").model_copy(deep=True)
    tool.ready_check = dict(READY_ANSWERS)
    with pytest.raises(ToolChangeError):
        ship_tool(tool, "approved_with_limits", "")
    ship_tool(tool, "approved_with_limits", "Internal notes only.")
    assert tool.status == "approved_with_limits" and tool.limits == "Internal notes only."


def test_ship_it_only_from_being_tried():
    tool = next(t for t in TOOLS if t.id == "call-recap-writer").model_copy()
    with pytest.raises(ToolChangeError):
        ship_tool(tool, "approved")


def test_retire_with_and_without_replacement():
    tool = next(t for t in TOOLS if t.id == "proposal-drafter").model_copy(deep=True)
    retire_tool(tool, "Nobody uses it any more.")
    assert tool.status == "retired" and tool.replaced_by is None
    tool = next(t for t in TOOLS if t.id == "translation-helper").model_copy(deep=True)
    with pytest.raises(ToolChangeError):
        retire_tool(tool, "Moved to a new tool.", "not-a-tool", TOOLS)
    retire_tool(tool, "Moved to a new tool.", "call-recap-writer", TOOLS)
    assert tool.status == "retired" and tool.replaced_by == "call-recap-writer"


def test_start_new_request_copies_the_right_fields():
    r = REQ["r-1044"]
    data = copy_request_fields(r)
    assert data == {
        "task": r.task, "team": r.team, "how_often": r.how_often, "who_uses": r.who_uses,
        "info": r.info, "copied_from": "r-1044",
    }
    assert "requester_name" not in data and "extra" not in data


def test_checklist_prefill_from_request():
    c = prefill_checklist(REQ["r-1048"])
    assert c.uses_customer_details == "yes"
    assert c.already_exists == "yes"
    assert prefill_checklist(REQ["r-1046"]).security_check == "needed"
    assert prefill_checklist(REQ["r-1045"]).uses_customer_details == "no"
