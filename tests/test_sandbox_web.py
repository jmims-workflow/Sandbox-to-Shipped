"""The sandbox features in the running app: demo examples, the server-side gate and live changes."""

import re
from datetime import date, timedelta

import pytest

from sts.rules import add_months, format_month, long_date

from .conftest import as_requester, as_reviewer, visible_text

TODAY = date.today()
SANDBOX = "Being tried is the sandbox: a small group uses it, with an end date, before it&#39;s shipped to everyone."
REQUESTER_NAMES = ["Priya Raman", "Mei Tanaka", "Carlos Mendes", "Owen Pratt", "Nora Lindqvist"]
GOOD_ANSWERS = {"kept_using": "regularly", "went_wrong": "Nothing", "how_tested": "Ran it on ten real pages."}


def text_of(html):
    return " ".join(visible_text(html).split())


def ship_button(html):
    return re.search(r"<button[^>]*>Ship it</button>", html).group(0)


def seed(app):
    store = app.state.store
    store.load_demo(app.state.demo)
    return store


# ---- Demo examples ----------------------------------------------------------------------


def test_translation_helper_shows_2_of_4_ready_with_ship_it_disabled(demo_client):
    as_reviewer(demo_client)
    html = demo_client.get("/tools/translation-helper").text
    assert "Ready to ship?" in html and "2 of 4 ready" in html
    assert "disabled" in ship_button(html)
    assert "Ship it opens when all 4 items are ready." in html
    text = text_of(html)
    for item in ["Owner agreed to own it", "Security check done or not needed", "The team kept using it",
                 "How it was tested"]:
        assert item in text
    assert html.count("<span>Not done</span>") == 2 and html.count("<span>Done</span>") == 2
    assert f"Trial ends {long_date(TODAY + timedelta(days=14))}" in html
    assert SANDBOX in html


def test_partner_outreach_is_3_of_4_and_needs_a_decision(demo_client):
    as_reviewer(demo_client)
    html = demo_client.get("/tools/partner-outreach-drafts").text
    assert "3 of 4 ready" in html and "disabled" in ship_button(html)
    assert "label-trial-ended" in html and "Trial ended" in html
    review = demo_client.get("/review").text
    card = review[review.index("Needs a decision"):review.index("Requests to review")]
    assert "Partner Outreach Drafts" in card and "Trial ended" in card
    assert "Being tried by Partnerships. Trial ended 3 days ago." in card
    assert 'href="/tools/partner-outreach-drafts"' in card


def test_trial_ended_shows_to_everyone(demo_client):
    as_requester(demo_client)
    assert "label-trial-ended" in demo_client.get("/tools/partner-outreach-drafts").text
    inventory = demo_client.get("/tools").text
    assert "label-trial-ended" in inventory
    assert "Ready to ship?" not in demo_client.get("/tools/partner-outreach-drafts").text


def test_proposal_drafter_shows_review_due_to_reviewers_only(demo_client):
    as_requester(demo_client)
    assert "Review due" not in demo_client.get("/tools/proposal-drafter").text
    assert "Review due" not in demo_client.get("/tools").text
    as_reviewer(demo_client)
    html = demo_client.get("/tools/proposal-drafter").text
    assert "label-review-due" in html and "Review due" in html
    assert "Still in use?" in html and "Anything to change? (optional)" in html
    assert f'value="{add_months(TODAY, 6):%Y-%m}"' in html
    review = demo_client.get("/review").text
    card = review[review.index("Needs a decision"):review.index("Requests to review")]
    assert "Proposal Drafter" in card and "Review due" in card
    assert f"Review was due in {format_month(add_months(TODAY, -1))}." in card
    assert "label-review-due" in demo_client.get("/tools").text


def test_webinar_invite_writer_shows_its_journey_and_how_it_earned_approval(demo_client):
    html = demo_client.get("/tools/webinar-invite-writer").text
    assert "Its journey" in html and "How it earned approval" in html
    journey = html[html.index("Its journey"):]
    assert '<ol class="timeline journey">' in journey
    steps = re.findall(r"<li>\s*<strong>([^<]+)</strong>", journey)
    assert steps == ["Requested", "Started being tried", "Shipped"]
    assert 'href="/decided?q=Webinar%20recap%20emails#decision-r-1041"' in journey
    assert long_date(TODAY - timedelta(days=97)) in journey and long_date(TODAY - timedelta(days=48)) in journey
    assert "By Field Marketing, for six weeks." in journey
    text = text_of(html)
    assert "Yes, regularly" in text
    assert "Two invites went out with the wrong time zone in the first week. Fixed by adding the time zone to the event brief." in text
    assert ("Ran it on the last eight webinar briefs and compared the invites with what we sent by hand. "
            "All eight were usable after small edits.") in text
    assert "Not needed. It's okay to use with public information only." in text or \
        "Not needed. It&#39;s okay to use with public information only." in html
    # The journey's Shipped step shows the ready to ship answers.
    shipped = journey[journey.index("<strong>Shipped</strong>"):]
    assert "Ready to ship answers" in shipped and "Yes, regularly" in shipped


def test_decided_before_has_anchors_for_journey_links(demo_client):
    assert 'id="decision-r-1041"' in demo_client.get("/decided").text


def test_every_demo_tool_has_a_journey(demo_client):
    for tool in demo_client.app.state.store.list_tools():
        assert tool.journey, tool.id
        html = demo_client.get(f"/tools/{tool.id}").text
        assert '<ol class="timeline journey">' in html


def test_inventory_names_the_sandbox_under_the_status_filter(demo_client):
    html = demo_client.get("/tools").text
    status = html.index('id="status"')
    assert html.index(SANDBOX) > status
    assert 'aria-describedby="sandbox-hint"' in html


def test_how_it_works_shows_the_new_path_and_principle(demo_client):
    text = text_of(demo_client.get("/how-it-works").text)
    path = ["Request", "Check what exists", "Reviewer decides", "Being tried the sandbox", "Ready to ship check",
            "Approved"]
    positions = [text.index(step) for step in path]
    assert positions == sorted(positions)
    assert "every tool starts in the sandbox and is shipped only when it has earned it" in text
    assert "Shipped means it earned it." in text
    assert text.index("Owners agree to be owners.") < text.index("Shipped means it earned it.")


def test_badge_counts_waiting_requests_plus_tools_that_need_a_decision(demo_client):
    as_reviewer(demo_client)
    store = demo_client.app.state.store
    waiting = sum(r.status == "waiting" for r in store.list_requests())
    html = demo_client.get("/review").text
    assert waiting == 3
    assert re.findall(r'class="badge"[^>]*>(\d+)<', html)[0] == str(waiting + 2)
    assert 'aria-label="5 waiting or needing a decision"' in html


def test_demo_disables_every_tool_change_but_still_shows_the_check(demo_client):
    as_reviewer(demo_client)
    for tool_id in ("translation-helper", "proposal-drafter"):
        html = demo_client.get(f"/tools/{tool_id}").text
        for name in ("Ship it", "Extend the trial", "Retire", "Mark reviewed", "Save answers"):
            button = re.search(rf"<button[^>]*>{name}</button>", html)
            if button:
                assert "disabled" in button.group(0), (tool_id, name)
        assert "Demo mode doesn&#39;t save changes to tools." in html
    html = demo_client.get("/tools/translation-helper").text
    assert "2 of 4 ready" in html and "Extend the trial</button>" in html and "Retire</button>" in html
    posts = {
        "translation-helper": [("ship", {"to_status": "approved"}), ("extend", {"new_end": TODAY.isoformat()}),
                               ("retire", {"retire_reason": "x"}), ("check", GOOD_ANSWERS),
                               ("security", {"security_done": "yes"})],
        "proposal-drafter": [("reviewed", {"still_in_use": "yes"})],
    }
    for tool_id, actions in posts.items():
        for action, data in actions:
            r = demo_client.post(f"/tools/{tool_id}/{action}", data=data)
            assert r.status_code == 400 and "Demo mode doesn" in r.text, action
    assert "2 of 4 ready" in demo_client.get("/tools/translation-helper").text


def test_tool_changes_are_for_reviewers(demo_client):
    as_requester(demo_client)
    for action in ("ship", "extend", "retire", "check", "security", "reviewed"):
        assert demo_client.post(f"/tools/translation-helper/{action}", data={}).status_code == 403


# ---- Asked before ------------------------------------------------------------------------


def test_prefilled_example_shows_no_asked_before_card(demo_client):
    html = demo_client.get("/").text
    assert "Call Recap Writer" in html
    assert "Asked before" not in html


@pytest.mark.parametrize("path", ["/", "/api/matches"])
def test_auto_reply_request_shows_asked_before(demo_client, path):
    r = demo_client.post(path, data={"action": "check", "task": "auto-reply to demo requests"})
    html = r.text
    card = html[html.index("Asked before"):]
    assert "Reply to inbound demo requests automatically" in card
    assert "Not approved as requested" in card
    assert "We don&#39;t approve tools that send to customers on their own." in card
    assert "What would change the answer" in card and "A version that drafts the reply" in card
    assert 'href="/decided?q=Reply%20to%20inbound%20demo%20requests%20automatically#decision-r-1044"' in card
    for name in REQUESTER_NAMES + ["the AI review group", "Jordan Ellis"]:
        assert name not in html


def test_asked_before_sits_below_the_tool_matches(demo_client):
    html = demo_client.post("/", data={"action": "check", "task": "Write invite and reminder emails for a webinar"}).text
    assert html.index("Webinar Invite Writer") < html.index("Asked before")
    assert "Webinar recap emails" in html


# ---- Live: the server enforces the rules ------------------------------------------------


def test_server_refuses_ship_it_when_the_check_is_incomplete(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    r = live_client.post("/tools/translation-helper/ship", data={"to_status": "approved"})
    assert r.status_code == 400 and "2 of 4 ready" in r.text
    assert store.get_tool("translation-helper").status == "being_tried"
    r = live_client.post("/tools/partner-outreach-drafts/ship", data={"to_status": "approved"})
    assert r.status_code == 400 and "3 of 4 ready" in r.text
    assert store.get_tool("partner-outreach-drafts").status == "being_tried"


def test_live_check_then_ship_with_limits_and_how_it_earned_approval(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    r = live_client.post("/tools/partner-outreach-drafts/check", data={
        "kept_using": "regularly", "went_wrong": "Two wrong tiers.", "how_tested": "Ran it on 20 past outreach notes.",
        "test_link": "https://tests.northstar.example/partner-outreach"}, follow_redirects=False)
    assert r.status_code == 303
    html = live_client.get("/tools/partner-outreach-drafts").text
    assert "4 of 4 ready" in html and "disabled" not in ship_button(html)
    r = live_client.post("/tools/partner-outreach-drafts/ship", data={"to_status": "approved_with_limits", "limits": ""})
    assert r.status_code == 400 and "Write the limits" in r.text
    live_client.post("/tools/partner-outreach-drafts/ship",
                     data={"to_status": "approved_with_limits", "limits": "A rep reads every draft."})
    tool = store.get_tool("partner-outreach-drafts")
    assert tool.status == "approved_with_limits" and tool.journey[-1]["kind"] == "shipped"
    html = live_client.get("/tools/partner-outreach-drafts").text
    assert "How it earned approval" in html and "Ran it on 20 past outreach notes." in html
    assert 'href="https://tests.northstar.example/partner-outreach"' in html


def test_live_stopped_team_hides_the_approval_options(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    live_client.post("/tools/translation-helper/check", data={
        "kept_using": "stopped", "went_wrong": "Nobody used it after the first week.", "how_tested": "Five pages."})
    html = live_client.get("/tools/translation-helper").text
    assert "A tool the team stopped using isn&#39;t ready to ship. Extend the trial or retire it." in html
    assert 'value="approved"' not in html and 'value="approved_with_limits"' not in html
    assert "Extend the trial</button>" in html and "Retire</button>" in html
    r = live_client.post("/tools/translation-helper/ship", data={"to_status": "approved"})
    assert r.status_code == 400
    assert store.get_tool("translation-helper").status == "being_tried"


def test_live_test_link_must_be_http_or_https(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    r = live_client.post("/tools/translation-helper/check", data={**GOOD_ANSWERS, "test_link": "ftp://files/results"})
    assert r.status_code == 400 and "Test result links start with http:// or https://" in r.text
    assert 'aria-invalid="true"' in r.text and "ftp://files/results" in r.text
    assert store.get_tool("translation-helper").ready_check == {}


def test_live_extend_once_and_up_to_60_days(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    end = store.get_tool("translation-helper").trial_ends
    r = live_client.post("/tools/translation-helper/extend", data={"new_end": (end + timedelta(days=61)).isoformat()})
    assert r.status_code == 400 and "up to 60 days" in r.text
    live_client.post("/tools/translation-helper/extend", data={"new_end": (end + timedelta(days=30)).isoformat()})
    tool = store.get_tool("translation-helper")
    assert tool.trial_ends == end + timedelta(days=30) and tool.trial_extended
    assert tool.journey[-1]["kind"] == "extended"
    r = live_client.post("/tools/translation-helper/extend", data={"new_end": (end + timedelta(days=40)).isoformat()})
    assert r.status_code == 400
    assert "already extended once" in live_client.get("/tools/translation-helper").text


def test_live_retire_needs_a_reason(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    r = live_client.post("/tools/translation-helper/retire", data={"retire_reason": " "})
    assert r.status_code == 400 and "Write a one-line reason" in r.text
    assert store.get_tool("translation-helper").status == "being_tried"
    live_client.post("/tools/translation-helper/retire", data={"retire_reason": "Help center has its own tool."})
    tool = store.get_tool("translation-helper")
    assert tool.status == "retired" and tool.journey[-1]["note"] == "Help center has its own tool."


def test_live_mark_reviewed_sets_the_next_review(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    r = live_client.post("/tools/proposal-drafter/reviewed", data={})
    assert r.status_code == 400 and "still in use" in r.text
    live_client.post("/tools/proposal-drafter/reviewed",
                     data={"still_in_use": "yes", "review_change": "", "next_review_month": ""})
    tool = store.get_tool("proposal-drafter")
    assert tool.next_review == format_month(add_months(date.today(), 6))
    assert tool.journey[-1]["kind"] == "reviewed"
    html = live_client.get("/review").text
    assert "Proposal Drafter" not in html[html.index("Needs a decision"):html.index("Requests to review")]


def test_live_security_check_recorded_on_the_tool(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    tool = store.get_tool("translation-helper")
    tool.security_check = "needed"
    store.save(tool)
    html = live_client.get("/tools/translation-helper").text
    assert "1 of 4 ready" in html and "Record the security check" in html
    r = live_client.post("/tools/translation-helper/security", data={"security_date": TODAY.isoformat()})
    assert r.status_code == 400
    live_client.post("/tools/translation-helper/security", data={
        "security_done": "yes", "security_date": TODAY.isoformat(), "security_note": "Checked by Sam."})
    tool = store.get_tool("translation-helper")
    assert tool.security_check == "done" and tool.journey[-1]["kind"] == "security_done"
    assert "2 of 4 ready" in live_client.get("/tools/translation-helper").text


def test_live_approval_records_security_and_journey(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    live_client.post("/review/r-1047", data={
        "action": "send", "outcome": "approve", "already_exists": "no", "sends_without_check": "no",
        "uses_customer_details": "yes", "security_check": "done", "reason": "Approved.", "what_would_change": "Nothing.",
        "tool_name": "Social Post Drafter", "tool_purpose": "Drafts posts.", "tool_owner_name": "Lena Ortiz",
        "tool_owner_team": "Field Marketing", "tool_allowed_info": "public_only", "owner_agreed": "yes",
        "tool_trial_ends": (TODAY + timedelta(days=60)).isoformat()})
    tool = store.get_tool("social-post-drafter")
    assert tool.security_check == "done"
    assert [e["kind"] for e in tool.journey] == ["requested", "being_tried"]
    html = live_client.get("/tools/social-post-drafter").text
    assert "2 of 4 ready" in html


def test_badge_counts_live(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    html = live_client.get("/review").text
    assert re.findall(r'class="badge"[^>]*>(\d+)<', html)[0] == "5"
    tool = store.get_tool("partner-outreach-drafts")
    tool.trial_ends = date.today()  # Ends today: not ended yet.
    store.save(tool)
    html = live_client.get("/review").text
    assert re.findall(r'class="badge"[^>]*>(\d+)<', html)[0] == "4"


def test_edit_checks_the_next_review_month(live_app, live_client):
    store = seed(live_app)
    as_reviewer(live_client)
    form = {"name": "Call Recap Writer", "purpose": "Turns call notes into a follow-up email.",
            "owner_name": "Dana Whitfield", "owner_team": "Sales Enablement", "teams": "Sales",
            "allowed_info": "customer_contact", "next_review": "someday"}
    r = live_client.post("/tools/call-recap-writer/edit", data=form)
    assert r.status_code == 400 and "for example March 2027" in r.text
    form["next_review"] = "march 2027"
    live_client.post("/tools/call-recap-writer/edit", data=form)
    assert store.get_tool("call-recap-writer").next_review == "March 2027"
