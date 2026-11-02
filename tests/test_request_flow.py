"""Request details as labeled rows, Claude's read stays with reviewers, review days, pilot wording,
the security questions and early warnings on Request a tool, and the security item for reviewers."""

import re
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from sts.config import Settings
from sts.models import Tool
from sts.rules import MSG_PASSED_ONLY, MSG_SECURITY, ready_count, ready_items
from sts.security import WARN_SENDS, WARN_SENSITIVE
from sts.web import create_app

from .conftest import DEMO_DIR, as_requester, as_reviewer, visible_text

ALL_NO = {"sends_without_check": "no", "keeps_elsewhere": "no", "ai_service": "claude"}
BASE = {"task": "Turn my call notes into a short follow-up email", "team": "Sales", "how_often": "few_week",
        "who_uses": "my_team"}


def text_of(html):
    return " ".join(visible_text(html).split())


def seed(app):
    store = app.state.store
    store.load_demo(app.state.demo)
    return store


def details(html):
    return dict(re.findall(r"<div><dt>([^<]+)</dt><dd>(.*?)</dd></div>", html, re.S))


# ---- Labeled request details -------------------------------------------------------------


def test_review_card_shows_labeled_rows(demo_client):
    as_reviewer(demo_client)
    html = demo_client.get("/review/r-1047").text
    card = html[html.index('aria-labelledby="req-title"'):html.index("claude-read-h")]
    assert '<dl class="facts details-list">' in card
    rows = details(card)
    assert rows["Requested by"] == "Owen Pratt, Marketing"
    assert rows["How often"] == "A few times a month"
    assert rows["Who would use it"] == "My team"
    assert rows["Information it uses"] == "Customer names or contact details<br>Public information only"
    # Nothing runs together in one line any more.
    assert "Owen Pratt. Marketing." not in card


def test_what_happens_next_shows_labeled_rows_after_the_steps(demo_client):
    html = demo_client.post("/", data={**BASE, "info": "public_only"}).text
    rows = details(html)
    assert {"Requested by", "How often", "Who would use it", "Information it uses"} <= set(rows)
    text = text_of(html)
    assert "Reviewers usually answer within 5 working days." in text
    # The steps come first, then "Your request". Claude's read is never on this page.
    assert html.index("What happens next") < html.index("Your request")
    assert "claude-read-h" not in html and "Only reviewers see this" not in text


def test_review_days_comes_from_the_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("STS_REVIEW_DAYS", "3")
    settings = Settings.from_env()
    assert settings.review_days == 3
    settings.demo_dir = DEMO_DIR
    html = TestClient(create_app(settings)).post("/", data={**BASE, "info": "public_only"}).text
    assert "Reviewers usually answer within 3 working days." in html
    monkeypatch.setenv("STS_REVIEW_DAYS", "soon")
    assert Settings.from_env().review_days == 5
    monkeypatch.delenv("STS_REVIEW_DAYS")
    assert Settings.from_env().review_days == 5


def test_env_example_lists_the_new_settings():
    from sts.config import ROOT

    text = (ROOT / ".env.example").read_text()
    for line in ("STS_REVIEW_DAYS=5", "STS_DAILY_CLAUDE_CALLS=100", "STS_VISITOR_CLAUDE_CALLS_PER_HOUR=10"):
        assert line in text
    assert "preview" in text


def test_no_requester_page_in_live_mode_shows_claudes_read(live_app, live_client):
    store = seed(live_app)
    r = live_client.post("/", data={**BASE, "info": "customer_contact", **ALL_NO}, follow_redirects=False)
    rid = r.headers["location"].split("/requests/")[1].split("?")[0]
    assert store.get_request(rid).size_up["bullets"]  # Claude's read was saved for reviewers.
    as_requester(live_client)
    bullets = [b["text"] for req in store.list_requests() if req.size_up for b in req.size_up["bullets"]]
    pages = ["/", "/requests", f"/requests/{rid}", f"/requests/{rid}?submitted=1", "/tools", "/decided",
             "/how-it-works"] + [f"/requests/{x.id}" for x in store.list_requests()]
    for page in pages:
        html = live_client.get(page).text
        assert "Claude&#39;s read" not in html and "Claude's read" not in html, page
        assert "claude-read-h" not in html, page
        for text in bullets:
            assert text not in html, page
    as_reviewer(live_client)
    assert "claude-read-h" in live_client.get(f"/review/{rid}").text


# ---- Pilot instead of being tried ---------------------------------------------------------------

ALL_PAGES = ["/", "/requests", "/tools", "/tools?status=all", "/tools?status=being_tried", "/decided", "/how-it-works",
             "/review", "/review/r-1045", "/review/r-1047", "/review/r-1049"] + \
            [f"/tools/{t}" for t in ("translation-helper", "partner-outreach-drafts", "webinar-invite-writer",
                                     "proposal-drafter", "subject-line-tester", "insight-dashboard-explainer")] + \
            [f"/requests/r-{n}" for n in range(1041, 1050)]


@pytest.mark.parametrize("viewer", ["requester", "reviewer"])
def test_being_tried_never_appears_in_rendered_pages(demo_client, viewer):
    demo_client.cookies.set("sts_viewer", viewer)
    for page in ALL_PAGES:
        r = demo_client.get(page)
        if r.status_code == 403:
            continue
        assert not re.search(r"being\s+tried", visible_text(r.text), re.I), page
        assert "sandbox" not in visible_text(r.text).lower().replace("sandbox to shipped", ""), page


def test_pilot_wording_on_the_tool_pages(demo_client):
    as_reviewer(demo_client)
    html = demo_client.get("/tools/translation-helper").text
    assert "In pilot" in html and "Pilot ends" in html and "Extend the pilot</button>" in html
    html = demo_client.get("/tools/partner-outreach-drafts").text
    assert "Pilot ended" in html
    review = demo_client.post("/review/r-1048", data={"action": "draft", "outcome": "use_existing"}).text
    assert "Being tried" not in review and "Pilot ends" in review


def test_claude_is_told_to_say_pilot(live_app, live_client):
    seed(live_app)
    live_client.post("/api/matches", data={"task": "translate pages"})
    call = live_app.state.fake_messages.calls[-1]
    assert '"status": "In pilot"' in call["messages"][0]["content"]
    assert "never\n\"being tried\"" in call["system"] or 'never "being tried"' in " ".join(call["system"].split())


# ---- The form: questions, warnings and submitting ---------------------------------------------


def test_questions_and_reviewers_look_for_on_request_a_tool(demo_client):
    html = demo_client.get("/?example=follow-up-emails").text
    assert "A few questions for security" in html
    for q in ("Would it send anything to customers or the public without a person checking first?",
              "Would it keep information anywhere other than tools Northstar already approved?",
              "Which AI service would it use?"):
        assert q in html
    assert '<option value="claude"' in html and '<option value="meridian"' in html
    assert '<option value="something_else"' in html and '<option value="not_sure"' in html
    assert re.search(r'<details class="card look-for">\s*<summary>What reviewers look for</summary>', html)
    look = html[html.index("What reviewers look for"):]
    assert "Sensitive personal information (student records, health details, government IDs): always reviewed by a " \
           "person on the security team." in look
    assert "start as a pilot" in look
    # One form: the request, the questions and the match panel's note all submit together.
    start = html.index('<form id="request-form"')
    form = html[start:html.index("</form>", start)]
    assert 'name="whats_missing"' in form and 'name="ai_service"' in form and 'name="task"' in form
    assert "Not quite right? Say what's missing (optional, sent with your request)." in form


def test_questions_are_required_for_non_public_information(demo_client):
    r = demo_client.post("/", data={**BASE, "info": "internal_notes"})
    assert r.status_code == 400
    assert "Answer this question for security." in r.text and "Choose the AI service" in r.text
    r = demo_client.post("/", data={**BASE, "info": "public_only"})
    assert r.status_code == 200


def test_both_early_warnings_show_and_submitting_still_works(demo_client):
    data = {**BASE, "info": ["customer_contact", "sensitive_personal"], **ALL_NO, "sends_without_check": "yes"}
    html = demo_client.post("/", data={**data, "action": "check"}).text
    for key, msg in (("sends_without_check", WARN_SENDS), ("info", WARN_SENSITIVE)):
        el = re.search(rf'<p class="early-warning" id="warn-{key}" role="status"[^>]*>(.*?)</p>', html, re.S).group(1)
        assert msg.replace("'", "&#39;") in el
    # No warnings without the answers that trigger them, but the elements are there for screen readers.
    quiet = demo_client.post("/", data={**BASE, "info": "customer_contact", **ALL_NO, "action": "check"}).text
    assert re.search(r'id="warn-info" role="status"[^>]*></p>', quiet)
    # Submitting still works after both warnings.
    r = demo_client.post("/", data=data)
    assert r.status_code == 200 and "what would happen next" in r.text
    assert "A person from security will review this, because it uses sensitive personal information." in r.text


def test_live_saves_the_security_result_with_the_request(live_app, live_client):
    store = seed(live_app)
    r = live_client.post("/", data={**BASE, "info": "customer_contact", **ALL_NO, "ai_service": "something_else"},
                         follow_redirects=False)
    rid = r.headers["location"].split("/requests/")[1].split("?")[0]
    saved = store.get_request(rid)
    assert saved.security_answers == {**ALL_NO, "ai_service": "something_else"}
    assert saved.security_result["result"] == "person"
    assert "Something else" in saved.security_result["reasons"][0]
    as_reviewer(live_client)
    html = live_client.get("/review").text
    assert "A person from security will review this." in html
    card = live_client.get(f"/review/{rid}").text
    assert "Security check: a person from security will review this" in card
    assert re.search(r'name="security_check" value="needed" checked', card)
    assert 'value="passed"' not in card


def test_public_only_request_has_no_answers_saved(live_app, live_client):
    store = seed(live_app)
    r = live_client.post("/", data={**BASE, "info": "public_only", "sends_without_check": "yes"},
                         follow_redirects=False)
    rid = r.headers["location"].split("/requests/")[1].split("?")[0]
    assert store.get_request(rid).security_answers == {}
    assert store.get_request(rid).security_result == {"result": "not_needed", "reasons": []}


# ---- Reviewers: the checklist's security item ----------------------------------------------------


def approve(**extra):
    return {"action": "send", "outcome": "approve", "already_exists": "no", "sends_without_check": "no",
            "uses_customer_details": "yes", "reason": "Approved.", "what_would_change": "Nothing.",
            "tool_name": "Social Post Drafter", "tool_purpose": "Drafts posts.", "tool_owner_name": "Lena Ortiz",
            "tool_owner_team": "Field Marketing", "tool_allowed_info": "public_only", "owner_agreed": "yes",
            "tool_trial_ends": (date.today() + timedelta(days=60)).isoformat(), **extra}


def test_demo_checklist_fills_the_security_item(demo_client):
    as_reviewer(demo_client)
    assert re.search(r'name="security_check" value="passed" checked', demo_client.get("/review/r-1047").text)
    html = demo_client.get("/review/r-1046").text
    assert re.search(r'name="security_check" value="needed" checked', html)
    assert "was answered Not sure" in html
    html = demo_client.get("/review/r-1049").text
    assert re.search(r'name="security_check" value="needed" checked', html)
    assert "Security check: a person from security will review this" in html


def test_reviewer_can_change_passed_automatically_to_needed(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    r = live_client.post("/review/r-1047", data=approve(security_check="needed"))
    assert r.status_code == 400 and MSG_SECURITY in r.text
    assert store.get_request("r-1047").status == "waiting"
    r = live_client.post("/review/r-1047", data=approve(security_check="passed"), follow_redirects=False)
    assert r.status_code == 303
    assert store.get_tool("social-post-drafter").security_check == "passed"
    assert store.decision_for("r-1047").checklist["security_check"] == "passed"


def test_passed_automatically_only_for_requests_that_passed(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    r = live_client.post("/review/r-1046", data=approve(security_check="passed"))
    assert r.status_code == 400 and MSG_PASSED_ONLY.replace("'", "&#39;") in r.text
    assert store.get_request("r-1046").status == "waiting"


def test_ready_to_ship_accepts_passed_automatically():
    tool = Tool(id="t", name="T", purpose="p", owner_name="A", owner_team="B", teams=["Sales"], status="being_tried",
                allowed_info=["internal_notes"], trial_ends=date.today(), security_check="passed", ready_check={},
                journey=[])
    security = next(i for i in ready_items(tool) if i.key == "security")
    assert security.done and ready_count(tool) == 2
    tool.security_check = "needed"
    assert not next(i for i in ready_items(tool) if i.key == "security").done


def test_tool_page_explains_passed_automatically(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    live_client.post("/review/r-1047", data=approve(security_check="passed"))
    html = live_client.get("/tools/social-post-drafter").text
    assert "2 of 4 ready" in html
    assert "Passed automatically against security's rules" in html
