"""I need this too: related requests in review, adding people, counts, notes and privacy."""

import re

import pytest

from sts.demo_data import load_demo_data
from sts.provider import ClaudeProvider, DemoProvider, MatchResult
from sts.rules import RequestChangeError, add_needed_by, needed_by_count

from .conftest import DEMO_DIR, as_requester, as_reviewer, fake_client, visible_text

DATA = load_demo_data(DEMO_DIR)
REQ = {r.id: r for r in DATA.requests}
ALL_NAMES = {r.requester_name for r in DATA.requests} | {p["name"] for r in DATA.requests for p in r.needed_by}
OPEN = [{"id": r.id, "title": r.title, "task": r.task} for r in DATA.requests if r.status in ("waiting", "in_review")]
SOCIAL = "posts for social media from our case studies"


def seed(app):
    store = app.state.store
    store.load_demo(app.state.demo)
    return store


# ---- The match call ------------------------------------------------------------------------


def test_in_review_matches_drop_unknown_ids_and_never_send_names():
    bogus = MatchResult.model_validate({"matches": [], "related_request": {"request_id": "r-0001", "reason": "x"}})
    client, msgs = fake_client({"MatchResult": bogus})
    provider = ClaudeProvider("k", "claude-sonnet-5-5", client=client)
    assert provider.find_matches(SOCIAL, [], DATA.tools, [], OPEN).related_request is None
    sent = msgs.calls[0]["messages"][0]["content"]
    assert "Requests still in review" in sent and "r-1047" in sent
    for name in ALL_NAMES:
        assert name not in sent
    # A decided request id is not in the list sent, so it is dropped too.
    decided = MatchResult.model_validate({"related_request": {"request_id": "r-1044", "reason": "x"}})
    client, _ = fake_client({"MatchResult": decided})
    assert ClaudeProvider("k", "m", client=client).find_matches(SOCIAL, [], DATA.tools, [], OPEN).related_request is None
    good = MatchResult.model_validate({"related_request": {"request_id": "r-1047", "reason": "Same posts."}})
    client, _ = fake_client({"MatchResult": good})
    out = ClaudeProvider("k", "m", client=client).find_matches(SOCIAL, [], DATA.tools, [], OPEN)
    assert out.related_request == {"request_id": "r-1047", "reason": "Same posts."}


def test_demo_word_match_finds_the_waiting_social_posts_request():
    provider = DemoProvider(DATA.recorded, DATA.requests)
    assert provider.find_matches(SOCIAL, [], DATA.tools, [], OPEN).related_request["request_id"] == "r-1047"
    assert provider.find_matches("Plan the office holiday party menu", [], DATA.tools, [], OPEN).related_request is None


# ---- The rules -------------------------------------------------------------------------------


def test_added_once_and_never_to_your_own_request():
    r = REQ["r-1046"].model_copy(deep=True)
    add_needed_by(r, "Sam Rivera", "For onboarding calls too.", DATA.as_of)
    assert needed_by_count(r) == 2 and r.needed_by[-1]["note"] == "For onboarding calls too."
    with pytest.raises(RequestChangeError, match="already on this request"):
        add_needed_by(r, "Sam Rivera", "", DATA.as_of)
    with pytest.raises(RequestChangeError, match="your own request"):
        add_needed_by(r, r.requester_name, "", DATA.as_of)
    with pytest.raises(RequestChangeError, match="already has a decision"):
        add_needed_by(REQ["r-1044"].model_copy(deep=True), "Sam Rivera", "", DATA.as_of)
    assert needed_by_count(r) == 2


# ---- Demo -----------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/api/matches"])
def test_demo_shows_the_card_with_a_disabled_button(demo_client, path):
    html = demo_client.post(path, data={"action": "check", "task": SOCIAL}).text
    card = html[html.index("Someone already asked for something like this. It's in review."):]
    assert "Social posts from case studies" in card and "label-waiting" in card
    button = re.search(r"<button[^>]*>I need this too</button>", card).group(0)
    assert "disabled" in button and 'formaction="/requests/r-1047/need-too"' in button
    assert "Anything different about what you need? (optional)" in card
    assert "In live mode, this adds you to that request instead of starting a new one." in card
    for name in ALL_NAMES:
        assert name not in html.split("Viewing as")[0] or name == "Priya Raman"
    assert "Tomas Reyes" not in html and "Owen Pratt" not in html
    text = visible_text(html)
    assert not re.search(r"\b(me too|upvote|upvotes)\b", text, re.I) and "thumb" not in html
    assert re.search(r">\s*I need this too\s*</button>", button) and not re.search(r"\blike\b", button, re.I)


def test_demo_prefilled_example_has_no_card(demo_client):
    assert "Someone already asked" not in demo_client.get("/").text


def test_demo_waiting_request_needed_by_3_people(demo_client):
    as_reviewer(demo_client)
    html = demo_client.get("/review/r-1047").text
    queue = html[html.index('aria-label="Requests to review"'):html.index("req-title")]
    assert re.search(r"Social posts from case studies</span>.*?Needed by 3 people", queue, re.S)
    card = html[html.index("req-title"):html.index("claude-read-h")]
    assert "Needed by 3 people" in card
    assert "We&#39;d use it for partner case studies too." in card and "Tomas Reyes" in card
    assert "I&#39;d want a short post for our customer newsletter as well." in card and "Grace Liu" in card


def test_demo_need_too_saves_nothing(demo_client):
    r = demo_client.post("/requests/r-1047/need-too", data={"task": SOCIAL, "need_note": "x"})
    assert r.status_code == 400 and "this adds you to that request" in r.text
    assert len(demo_client.app.state.store.get_request("r-1047").needed_by) == 2


# ---- Live -----------------------------------------------------------------------------------


def test_live_need_too_adds_the_person_instead_of_a_new_request(live_app, live_client):
    store = seed(live_app)
    before = len(store.list_requests())
    r = live_client.post("/requests/r-1046/need-too",
                         data={"task": "renewal notes", "need_note": "  For onboarding calls too. "},
                         follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/requests?needed=r-1046"
    assert len(store.list_requests()) == before
    req = store.get_request("r-1046")
    assert req.needed_by == [{"name": "Avery Test", "note": "For onboarding calls too.", "date": req.needed_by[0]["date"]}]
    html = live_client.get("/requests?needed=r-1046").text
    also = html[html.index("Requests I need too"):]
    assert "Renewal risk notes for CSMs" in also
    assert "You're added to" in html
    # Only once.
    r = live_client.post("/requests/r-1046/need-too", data={"task": "renewal notes"})
    assert r.status_code == 400 and "already on this request" in r.text
    assert len(store.get_request("r-1046").needed_by) == 1


def test_live_never_added_to_your_own_request(live_app, live_client):
    store = seed(live_app)
    r = live_client.post("/", data={"task": "Draft renewal notes", "team": "Sales", "how_often": "rarely",
                                    "who_uses": "just_me", "info": "public_only"}, follow_redirects=False)
    rid = r.headers["location"].split("/requests/")[1].split("?")[0]
    r = live_client.post(f"/requests/{rid}/need-too", data={"task": "x"})
    assert r.status_code == 400 and "your own request" in r.text
    assert store.get_request(rid).needed_by == []


def test_live_own_requests_are_not_offered(live_app, live_client):
    store = seed(live_app)
    live_client.cookies.set("sts_name", "Owen Pratt")
    html = live_client.post("/api/matches", data={"task": SOCIAL}).text
    sent = live_app.state.fake_messages.calls[-1]["messages"][0]["content"]
    assert '"id": "r-1047"' not in sent and '"id": "r-1046"' in sent
    assert "Someone already asked" not in html
    assert store.get_request("r-1047").needed_by


def test_live_count_and_notes_for_reviewers_names_hidden_from_requesters(live_app, live_client):
    store = seed(live_app)
    live_client.post("/requests/r-1047/need-too", data={"task": SOCIAL, "need_note": "For webinars as well."})
    assert needed_by_count(store.get_request("r-1047")) == 4
    as_reviewer(live_client)
    html = live_client.get("/review/r-1047").text
    # The queue list and the request card. (The Not now revisit item for r-1051 says it too.)
    assert html.count("Needed by 4 people") == 3
    assert html.count("Needed by 4 people</span>") == 2
    assert "For webinars as well." in html and "Avery Test" in html
    as_requester(live_client)
    # The person who was added sees the request and the decision when it comes, but not who else is on it.
    page = live_client.get("/requests/r-1047").text
    assert "You said you need this too" in page and "For webinars as well." in page
    for other in ("Tomas Reyes", "Grace Liu", "Owen Pratt", "Needed by"):
        assert other not in page
    # The original requester never sees who else is attached either.
    live_client.cookies.set("sts_name", "Owen Pratt")
    for page in ("/requests", "/requests/r-1047"):
        html = live_client.get(page).text
        for other in ("Tomas Reyes", "Grace Liu", "Avery Test", "For webinars as well.", "Needed by"):
            assert other not in html, (page, other)


def test_live_added_person_sees_the_decision(live_app, live_client):
    store = seed(live_app)
    live_client.post("/requests/r-1046/need-too", data={"task": "x"})
    as_reviewer(live_client)
    live_client.post("/review/r-1046", data={
        "action": "send", "outcome": "not_approved", "already_exists": "no", "sends_without_check": "no",
        "uses_customer_details": "yes", "security_check": "needed", "reason": "Not this version.",
        "what_would_change": "Only notes the CSM can already see."})
    assert store.get_request("r-1046").status == "decided"
    as_requester(live_client)
    html = live_client.get("/requests").text
    also = html[html.index("Requests I need too"):]
    assert "Not approved as requested" in also
    assert "Not this version." in live_client.get("/requests/r-1046").text


def test_live_card_has_a_working_button(live_app, live_client):
    seed(live_app)
    live_app.state.fake_messages.outputs["MatchResult"] = MatchResult.model_validate(
        {"matches": [], "related_request": {"request_id": "r-1047", "reason": "Same posts."}})
    html = live_client.post("/api/matches", data={"task": SOCIAL}).text
    button = re.search(r"<button[^>]*>I need this too</button>", html).group(0)
    assert "disabled" not in button
    assert "Same posts." in html and "Owen Pratt" not in html
