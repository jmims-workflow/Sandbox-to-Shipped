"""Live mode with a fake Claude client. Nothing here calls the real API."""

from fastapi.testclient import TestClient

from .conftest import as_reviewer

NEW_REQUEST = {"task": "Turn my call notes into a short follow-up email", "team": "Sales",
               "how_often": "few_week", "who_uses": "my_team", "info": ["customer_contact"],
               "sends_without_check": "no", "keeps_elsewhere": "no", "ai_service": "claude"}


def seed(app):
    store = app.state.store
    store.load_demo(app.state.demo)
    return store


def test_first_visit_asks_for_a_name(live_app):
    c = TestClient(live_app)
    r = c.get("/tools", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/welcome")
    r = c.post("/welcome", data={"name": "Sam Rivera", "next": "/tools"}, follow_redirects=False)
    assert r.headers["location"] == "/tools"
    assert "sts_name=" in r.headers["set-cookie"]
    assert c.get("/health").text == "ok"


def test_submit_saves_request_with_claude_title_and_matches(live_app, live_client):
    seed(live_app)
    r = live_client.post("/", data=NEW_REQUEST, follow_redirects=False)
    assert r.status_code == 303
    rid = r.headers["location"].split("/requests/")[1].split("?")[0]
    req = live_app.state.store.get_request(rid)
    assert req.title == "Short follow-up emails"
    assert req.requester_name == "Avery Test"
    assert req.matches[0]["tool_id"] == "call-recap-writer"
    assert req.status == "waiting"
    assert "Live: runs on Claude" in live_client.get(r.headers["location"]).text
    assert "Short follow-up emails" in live_client.get("/requests").text


def test_reviewer_approves_and_new_tool_starts_being_tried(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    data = {
        "action": "send", "outcome": "approve", "already_exists": "no", "sends_without_check": "no",
        "uses_customer_details": "no", "security_check": "not_needed", "reason": "Approved.",
        "what_would_change": "Nothing.", "tool_name": "Social Post Drafter", "tool_purpose": "Drafts posts.",
        "tool_owner_name": "Lena Ortiz", "tool_owner_team": "Field Marketing", "tool_allowed_info": "public_only",
        "tool_trial_ends": "2027-02-01",
    }
    r = live_client.post("/review/r-1047", data=data)
    assert r.status_code == 400 and "Check that the owner has agreed" in r.text
    data["owner_agreed"] = "yes"
    r = live_client.post("/review/r-1047", data=data, follow_redirects=False)
    assert r.status_code == 303
    tool = store.get_tool("social-post-drafter")
    assert tool.status == "being_tried" and tool.from_request == "r-1047"
    assert store.get_request("r-1047").status == "decided"
    d = store.decision_for("r-1047")
    assert d.outcome == "approve" and d.decided_by == "Avery Test"


def test_security_check_needed_blocks_approval_in_the_app(live_app, live_client):
    seed(live_app)
    as_reviewer(live_client)
    r = live_client.post("/review/r-1046", data={
        "action": "send", "outcome": "approve", "already_exists": "no", "sends_without_check": "no",
        "uses_customer_details": "yes", "security_check": "needed", "reason": "r", "what_would_change": "w",
    })
    assert r.status_code == 400
    assert "Finish the security check before approving." in r.text


def test_draft_from_claude_does_not_choose_the_outcome(live_app, live_client):
    seed(live_app)
    as_reviewer(live_client)
    r = live_client.post("/review/r-1048", data={"action": "draft", "outcome": "not_approved"})
    assert "Drafted reason text." in r.text
    assert 'value="not_approved" checked' in r.text
    call = live_app.state.fake_messages.calls[-1]
    assert "Not approved as requested" in call["messages"][0]["content"]


def test_save_for_later_and_question_flow(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    live_client.post("/review/r-1048", data={"action": "save", "outcome": "use_existing", "reason": "Draft"})
    req = store.get_request("r-1048")
    assert req.status == "in_review" and req.draft["reason"] == "Draft"
    assert "Reviewer picked it up" in [e["label"] for e in req.timeline]
    live_client.cookies.set("sts_viewer", "requester")
    r = live_client.post("/requests/r-1042/ask", data={"question": "Can Support keep using it after the trial?"},
                         follow_redirects=False)
    assert r.status_code == 303
    as_reviewer(live_client)
    assert "Can Support keep using it after the trial?" in live_client.get("/review/r-1042").text
    live_client.post("/review/r-1042", data={"action": "handled"})
    assert all(q["handled"] for q in store.get_request("r-1042").questions)


def test_ship_it_and_retire_in_the_app(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    live_client.post("/tools/translation-helper/check", data={
        "kept_using": "regularly", "went_wrong": "Nothing", "how_tested": "Tried it on ten pages."})
    live_client.post("/tools/translation-helper/ship", data={"to_status": "approved"})
    assert store.get_tool("translation-helper").status == "approved"
    live_client.post("/tools/partner-outreach-drafts/retire",
                     data={"retire_reason": "Call Recap Writer covers it.", "replaced_by": "call-recap-writer"})
    t = store.get_tool("partner-outreach-drafts")
    assert t.status == "retired" and t.replaced_by == "call-recap-writer"
    live_client.cookies.set("sts_viewer", "requester")
    r = live_client.post("/tools/proposal-drafter/retire", data={"retire_reason": "Not needed."})
    assert r.status_code == 403
    assert store.get_tool("proposal-drafter").status == "approved_with_limits"


def test_edit_owner_needs_agreement(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    form = {"name": "Call Recap Writer", "purpose": "Turns call notes into a follow-up email.",
            "owner_name": "New Person", "owner_team": "Sales", "teams": "Sales", "allowed_info": "customer_contact"}
    r = live_client.post("/tools/call-recap-writer/edit", data=form)
    assert r.status_code == 400
    form["owner_agreed"] = "yes"
    live_client.post("/tools/call-recap-writer/edit", data=form)
    assert store.get_tool("call-recap-writer").owner_name == "New Person"
