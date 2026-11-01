import re
import socket
from datetime import date, timedelta

import pytest

from sts.config import Settings

from sts.rules import long_date

from .conftest import DEMO_DIR, as_requester, as_reviewer, visible_text

BANNED = ["intake", "triage", "ticket", "workflow", "governance", "PII", "LLM", "model", "prompt", "deny", "denied"]
REQUESTER_PAGES = ["/", "/requests", "/requests/r-1044", "/requests/r-1048", "/requests/r-1045", "/requests/r-1042",
                   "/requests/r-1041", "/requests/r-1043", "/tools", "/tools?status=all", "/tools/call-recap-writer",
                   "/tools/subject-line-tester", "/decided", "/how-it-works", "/?from=r-1044",
                   "/tools/webinar-invite-writer", "/tools/partner-outreach-drafts", "/tools/translation-helper",
                   "/tools/proposal-drafter"]
REVIEWER_PAGES = ["/review", "/review/r-1046", "/review/r-1047", "/review/r-1044", "/review/r-1045",
                  "/tools/translation-helper", "/tools/proposal-drafter/edit", "/decided",
                  "/tools/partner-outreach-drafts", "/tools/proposal-drafter", "/tools/webinar-invite-writer",
                  "/tools/call-recap-writer", "/tools/subject-line-tester", "/tools", "/how-it-works"]


def test_health(demo_client):
    r = demo_client.get("/health")
    assert r.status_code == 200 and r.text == "ok"


def test_home_shows_call_recap_writer_as_close_match_for_the_example(demo_client):
    html = demo_client.get("/").text
    assert "Call Recap Writer" in html
    assert "Close match. Claude is fairly sure." in html
    assert "Claude only suggests. A person reviews every request." in html
    assert "turn my notes into a follow-up email" in html  # prefilled example


def test_other_text_uses_word_match_with_label(demo_client):
    r = demo_client.post("/", data={"action": "check", "task": "Write invite and reminder emails for a webinar"})
    assert "Webinar Invite Writer" in r.text
    assert "Demo uses a simple word match. Live mode asks Claude." in r.text


def test_nothing_matches_message(demo_client):
    r = demo_client.post("/api/matches", data={"task": "Plan the office holiday party menu"})
    assert "Nothing we have looks like this yet." in r.text


def test_possible_match_is_labeled_less_sure(demo_client):
    r = demo_client.post("/", data={"action": "check", "task": "Write a reminder for an event"})
    if "Possible match" in r.text:
        assert "Claude is less sure" in r.text


def test_not_approved_request_shows_reason_and_what_would_change(demo_client):
    html = demo_client.get("/requests/r-1044").text
    assert "Not approved as requested" in html
    assert "We don&#39;t approve tools that send to customers on their own." in html or \
        "We don't approve tools that send to customers on their own." in html
    assert "What would change the answer" in html
    assert "A version that drafts the reply for a rep to check and send" in html
    assert "Request a different version" in html
    # Demo dates are offsets from today: r-1044 was decided 6 days ago.
    assert f"Decided {long_date(date.today() - timedelta(days=6))} by the AI review group" in html


def test_request_a_different_version_copies_answers(demo_client):
    html = demo_client.get("/?from=r-1044").text
    assert "When someone fills in the demo request form" in html
    assert 'name="copied_from" value="r-1044"' in html
    assert re.search(r'value="every_day" checked', html)
    assert re.search(r'value="several_teams" checked', html)


def test_reviewer_sees_checklist_and_recorded_draft(demo_client):
    as_reviewer(demo_client)
    html = demo_client.get("/review").text
    assert "Does an approved tool already do this?" in html
    assert "Claude&#39;s read" in html or "Claude's read" in html
    assert "answering each customer question in the order it was asked" in html
    r = demo_client.post("/review/r-1048", data={"action": "draft", "outcome": "use_existing",
                                                 "existing_tool_id": "call-recap-writer"})
    assert "Good news: Call Recap Writer already does this" in r.text
    assert "Drafted by Claude from your checklist. Edit it before sending." in r.text
    # Same thing without a page reload.
    j = demo_client.post("/api/review/r-1048/draft", data={"outcome": "use_existing"}).json()
    assert j["what_would_change"] == "If it doesn't answer customer questions in order, tell us and we'll reopen this."


def test_draft_needs_an_outcome_first(demo_client):
    as_reviewer(demo_client)
    j = demo_client.post("/api/review/r-1048/draft", data={}).json()
    assert "Choose an outcome first" in j["error"]


def test_send_and_tool_changes_are_disabled_in_demo(demo_client):
    as_reviewer(demo_client)
    html = demo_client.get("/review/r-1048").text
    assert re.search(r'value="send" disabled', html)
    assert "Demo mode doesn" in html
    r = demo_client.post("/review/r-1048", data={"action": "send", "outcome": "not_approved"})
    assert r.status_code == 400
    r = demo_client.post("/tools/translation-helper/ship", data={"to_status": "approved"})
    assert r.status_code == 400 and "Demo mode doesn" in r.text
    r = demo_client.post("/requests/r-1044/ask", data={"question": "Why?"})
    assert r.status_code == 400


def test_sends_warning_shown_above_decision(demo_client):
    as_reviewer(demo_client)
    r = demo_client.post("/review/r-1048", data={"action": "draft", "sends_without_check": "yes"})
    assert re.search(r'id="sends-warning"[^>]*role="status">', r.text)
    assert "doesn&#39;t approve tools that send to customers on their own" in r.text or \
        "doesn't approve tools that send to customers on their own" in r.text


def test_decided_before_shows_all_four_outcomes_and_no_requester_names(demo_client):
    html = demo_client.get("/decided").text
    for label in ["Approved", "Approved with limits", "Use a tool we have", "Not approved as requested"]:
        assert label in html
    for name in ["Priya Raman", "Mei Tanaka", "Carlos Mendes", "Owen Pratt", "Nora Lindqvist", "Priya"]:
        assert name not in html
    assert "We never show who asked." in html


def test_decided_before_filters(demo_client):
    html = demo_client.get("/decided?outcome=use_existing").text
    assert "Translate help center articles" in html and "Webinar recap emails" not in html
    html = demo_client.get("/decided?q=pricing").text
    assert "Fill in proposal pricing" in html and "Translate help center" not in html


def test_inventory_filters_and_count(demo_client):
    html = demo_client.get("/tools").text
    assert "Showing 8 of 9 tools. 6 ready to use, 2 being tried." in html
    assert "Subject Line Tester" not in html
    html = demo_client.get("/tools?status=all").text
    assert "Subject Line Tester" in html
    html = demo_client.get("/tools?status=being_tried").text
    ends = long_date(date.today() + timedelta(days=14))
    assert f"Being tried by International Marketing until {ends}" in html
    html = demo_client.get("/tools?info=public_only&team=Marketing").text
    assert "Webinar Invite Writer" in html and "Call Recap Writer" not in html


def test_sidebar_navigation_by_viewer(demo_client):
    html = demo_client.get("/tools").text
    assert 'href="/tools" class="nav-link" aria-current="page"' in html
    assert "Request a tool" in html and "Review queue" not in html
    assert "Demo: sample data" in html
    as_reviewer(demo_client)
    html = demo_client.get("/review").text
    assert "Review queue" in html and "My requests" not in html
    assert 'class="badge"' in html
    assert "<details class=\"mobile-menu\">" in html


def test_viewing_as_switch_sets_cookie(demo_client):
    r = demo_client.post("/viewing-as", data={"role": "reviewer", "next": "/tools"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/tools"
    assert "sts_viewer=reviewer" in r.headers["set-cookie"]


def test_review_queue_is_for_reviewers(demo_client):
    as_requester(demo_client)
    assert demo_client.get("/review").status_code == 403


def test_text_limit_message(demo_client):
    r = demo_client.post("/", data={"task": "x" * 5001, "team": "Sales", "how_often": "rarely",
                                    "who_uses": "just_me", "info": "public_only"})
    assert r.status_code == 400
    assert "Please keep it under 5,000 characters" in r.text


def test_submit_in_demo_shows_what_happens_next(demo_client):
    r = demo_client.post("/", data={"task": "Write invite and reminder emails for a webinar", "team": "Marketing",
                                    "how_often": "few_month", "who_uses": "my_team", "info": "public_only"})
    assert r.status_code == 200
    assert "Here&#39;s what happens next" in r.text or "Here's what happens next" in r.text
    assert "nothing was saved" in r.text
    assert "Claude" in r.text


@pytest.mark.parametrize("viewer,pages", [("requester", REQUESTER_PAGES), ("reviewer", REVIEWER_PAGES)])
def test_no_banned_words_in_rendered_pages(demo_client, viewer, pages):
    demo_client.cookies.set("sts_viewer", viewer)
    for page in pages:
        r = demo_client.get(page)
        assert r.status_code == 200, page
        text = visible_text(r.text)
        for word in BANNED:
            assert not re.search(rf"\b{word}\b", text, re.IGNORECASE), f"{word!r} on {page}"


def test_no_banned_words_in_review_states(demo_client):
    as_reviewer(demo_client)
    pages = [
        demo_client.post("/review/r-1048", data={"action": "draft", "outcome": "use_existing", "sends_without_check": "yes"}),
        demo_client.post("/review/r-1048", data={"action": "send", "outcome": "approve"}),
        demo_client.post("/", data={"task": "Write invite and reminder emails for a webinar", "team": "Marketing",
                                    "how_often": "few_month", "who_uses": "my_team", "info": "public_only"}),
        demo_client.post("/", data={"action": "check", "task": "auto-reply to demo requests"}),
        demo_client.post("/tools/translation-helper/ship", data={"to_status": "approved"}),
    ]
    for r in pages:
        text = visible_text(r.text)
        for word in BANNED:
            assert not re.search(rf"\b{word}\b", text, re.IGNORECASE), word


def test_demo_makes_no_network_calls_and_saves_nothing(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from sts.web import create_app

    def no_network(*args, **kwargs):
        raise AssertionError("demo mode tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    data_dir = tmp_path / "data"
    # Demo stays demo even when a key is present.
    settings = Settings(requested_mode="demo", api_key="sk-present", data_dir=data_dir, demo_dir=DEMO_DIR)
    client = TestClient(create_app(settings))
    client.get("/")
    client.post("/api/matches", data={"task": "turn notes into an email"})
    client.post("/", data={"task": "Write invite emails", "team": "Marketing", "how_often": "rarely",
                           "who_uses": "just_me", "info": "public_only"})
    as_reviewer(client)
    client.post("/review/r-1048", data={"action": "draft", "outcome": "use_existing"})
    client.post("/review/r-1048", data={"action": "send", "outcome": "not_approved", "reason": "x",
                                        "what_would_change": "y"})
    client.post("/review/r-1048", data={"action": "save"})
    client.post("/tools/translation-helper/retire", data={})
    assert not data_dir.exists() or not any(data_dir.iterdir())
    # Data is unchanged.
    html = client.get("/tools/translation-helper").text
    assert "Being tried" in html
    assert "Waiting" in client.get("/review/r-1048").text


def test_live_without_key_falls_back_to_demo_with_notice(tmp_path):
    from fastapi.testclient import TestClient

    from sts.web import create_app

    settings = Settings(requested_mode="live", api_key="", data_dir=tmp_path / "d", demo_dir=DEMO_DIR)
    assert settings.mode == "demo"
    html = TestClient(create_app(settings)).get("/").text
    assert "Live mode is turned on, but no API key is set." in html
    assert "Demo: sample data" in html
    assert not (tmp_path / "d").exists()


def test_key_never_reaches_the_browser(tmp_path, live_client):
    for page in ["/", "/tools", "/decided", "/how-it-works"]:
        assert "test-key" not in live_client.get(page).text
