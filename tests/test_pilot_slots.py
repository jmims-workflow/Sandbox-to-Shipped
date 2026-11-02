"""Pilot slots: only so many tools can be in pilot at once, enforced on the server."""

import re
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from sts.config import Settings
from sts.models import Tool
from sts.rules import (
    Checklist,
    DecisionForm,
    NewTool,
    extend_trial,
    msg_slots_full,
    slot_count,
    slots_line,
    validate_decision,
)
from sts.web import create_app

from .conftest import DEFAULT_OUTPUTS, DEMO_DIR, as_reviewer, fake_client

TODAY = date(2027, 3, 10)
FULL = "All 3 pilot slots are in use. Ship or retire a pilot first, or choose Not now."


def tool(tid, status="being_tried", ends=TODAY + timedelta(days=20)):
    return Tool(id=tid, name=tid.title(), purpose="p", owner_name="A", owner_team="B", teams=["Sales"],
                status=status, allowed_info=["public_only"], trial_ends=ends if status == "being_tried" else None)


def approval(outcome="approve"):
    return DecisionForm(
        outcome=outcome, reason="Yes.", what_would_change="Nothing.", limits="A limit.",
        checklist=Checklist(already_exists="no", sends_without_check="no", uses_customer_details="no",
                            security_check="not_needed"),
        new_tool=NewTool(name="New", purpose="Does it.", owner_name="A", owner_team="B", owner_agreed=True,
                         allowed_info=["public_only"], trial_ends=TODAY + timedelta(days=60)),
    )


def test_every_pilot_uses_a_slot_including_past_its_end_date():
    tools = [tool("a"), tool("b", ends=TODAY - timedelta(days=30)), tool("c", "approved"), tool("d", "retired"),
             tool("e", "approved_with_limits")]
    slots = slot_count(tools, 3)
    assert slots["used"] == 2 and [t.id for t in slots["pilots"]] == ["a", "b"] and not slots["full"]
    assert slots_line(slots) == "Pilot slots: 2 of 3 used."
    slots = slot_count(tools + [tool("f", ends=TODAY - timedelta(days=1))], 3)
    assert slots["full"] and slots_line(slots) == "Pilot slots: 3 of 3 used. Ship or retire a pilot to make room."


def test_shipping_or_retiring_frees_a_slot():
    tools = [tool("a"), tool("b"), tool("c")]
    assert slot_count(tools, 3)["full"]
    tools[0].status = "approved"
    assert not slot_count(tools, 3)["full"]
    tools[0].status = "being_tried"
    tools[1].status = "retired"
    assert not slot_count(tools, 3)["full"]


@pytest.mark.parametrize("outcome", ["approve", "approve_with_limits"])
def test_approvals_refused_when_full(outcome):
    full = [tool("a"), tool("b"), tool("c")]
    errors = validate_decision(approval(outcome), full, today=TODAY, pilot_slots=3)
    assert errors == {"outcome": FULL}
    assert validate_decision(approval(outcome), full[:2], today=TODAY, pilot_slots=3) == {}
    assert validate_decision(approval(outcome), full, today=TODAY, pilot_slots=4) == {}
    assert msg_slots_full(3) == FULL


@pytest.mark.parametrize("outcome", ["use_existing", "not_approved", "not_now"])
def test_other_outcomes_allowed_when_full(outcome):
    form = approval(outcome)
    form.existing_tool_id = "a"
    form.revisit_on = TODAY + timedelta(days=30)
    assert validate_decision(form, [tool("a"), tool("b"), tool("c")], today=TODAY, pilot_slots=3) == {}


def test_extending_is_allowed_when_full():
    pilots = [tool("a"), tool("b"), tool("c")]
    assert slot_count(pilots, 3)["full"]
    extend_trial(pilots[0], pilots[0].trial_ends + timedelta(days=30), TODAY)
    assert pilots[0].trial_extended and pilots[0].status == "being_tried"


def test_demo_review_queue_shows_3_of_3_with_links(demo_client):
    as_reviewer(demo_client)
    html = demo_client.get("/review").text
    assert "Pilot slots: 3 of 3 used. Ship or retire a pilot to make room." in html
    card = html[html.index("slots-card"):html.index("needs-h")]
    for tid in ("event-follow-up-notes", "partner-outreach-drafts", "translation-helper"):
        assert f'href="/tools/{tid}"' in card
    # Partner Outreach Drafts is past its end date and still uses a slot.
    assert "(pilot ended)" in card


def test_demo_decision_form_disables_approvals(demo_client):
    as_reviewer(demo_client)
    html = demo_client.get("/review/r-1047").text
    assert FULL in html
    for key in ("approve", "approve_with_limits"):
        assert re.search(rf'name="outcome" value="{key}" disabled>', html), key
    for key in ("use_existing", "not_approved", "not_now"):
        assert re.search(rf'name="outcome" value="{key}">', html), key


@pytest.fixture
def full_live(tmp_path):
    settings = Settings(requested_mode="live", api_key="k", data_dir=tmp_path / "data", demo_dir=DEMO_DIR)
    client, _ = fake_client(dict(DEFAULT_OUTPUTS))
    from sts.provider import ClaudeProvider
    app = create_app(settings, provider=ClaudeProvider("k", "m", client=client))
    app.state.store.load_demo(app.state.demo)
    c = TestClient(app)
    c.cookies.set("sts_name", "Jordan Ellis")
    as_reviewer(c)
    return app, c


def approve_post(**extra):
    return {"action": "send", "outcome": "approve", "already_exists": "no", "sends_without_check": "no",
            "uses_customer_details": "yes", "security_check": "passed", "reason": "Approved.",
            "what_would_change": "Nothing.", "tool_name": "Social Post Drafter", "tool_purpose": "Drafts posts.",
            "tool_owner_name": "Lena Ortiz", "tool_owner_team": "Field Marketing", "tool_allowed_info": "public_only",
            "owner_agreed": "yes", "tool_trial_ends": (date.today() + timedelta(days=60)).isoformat(), **extra}


def test_live_approval_refused_on_the_server_when_full(full_live):
    app, c = full_live
    store = app.state.store
    assert Settings().pilot_slots == 3
    # Posting the approval directly, as if the page had let it through.
    r = c.post("/review/r-1047", data=approve_post(), follow_redirects=False)
    assert r.status_code == 400 and FULL in r.text
    assert store.get_request("r-1047").status == "waiting"
    assert not any(t.from_request == "r-1047" for t in store.list_tools())
    r = c.post("/review/r-1047", data=approve_post(outcome="approve_with_limits", limits="Only drafts."),
               follow_redirects=False)
    assert r.status_code == 400


def test_live_extend_works_when_full_and_retiring_makes_room(full_live):
    app, c = full_live
    store = app.state.store
    end = store.get_tool("translation-helper").trial_ends
    r = c.post("/tools/translation-helper/extend", data={"new_end": (end + timedelta(days=20)).isoformat()},
               follow_redirects=False)
    assert r.status_code == 303 and store.get_tool("translation-helper").trial_extended
    r = c.post("/tools/partner-outreach-drafts/retire", data={"retire_reason": "The team moved on."},
               follow_redirects=False)
    assert r.status_code == 303
    assert "Pilot slots: 2 of 3 used." in c.get("/review").text
    r = c.post("/review/r-1047", data=approve_post(), follow_redirects=False)
    assert r.status_code == 303
    assert "Pilot slots: 3 of 3 used." in c.get("/review").text


def test_setting_reads_from_the_environment(monkeypatch):
    monkeypatch.setenv("STS_PILOT_SLOTS", "5")
    assert Settings.from_env().pilot_slots == 5
    monkeypatch.setenv("STS_PILOT_SLOTS", "lots")
    assert Settings.from_env().pilot_slots == 3


def test_env_example_lists_pilot_slots():
    from sts.config import ROOT
    assert "STS_PILOT_SLOTS=3" in (ROOT / ".env.example").read_text()
