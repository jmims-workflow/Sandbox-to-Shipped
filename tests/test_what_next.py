"""Here's what happens next: one story from the requester's side, never Claude's read."""

import re

import pytest
from fastapi.testclient import TestClient

from sts.config import Settings
from sts.web import create_app

from .conftest import DEMO_DIR, visible_text
from .test_preview import preview_app

BASE = {"task": "Turn my call notes into a short follow-up email", "team": "Sales", "how_often": "few_week",
        "who_uses": "my_team"}
ALL_NO = {"sends_without_check": "no", "keeps_elsewhere": "no", "ai_service": "claude"}


def text_of(html):
    return " ".join(visible_text(html).split())


def steps(html):
    """Each step as (status word, title, line)."""
    found = re.findall(
        r'<li class="step-item is-(\w+)"[^>]*>.*?<span>(Done|Next|Later)</span></span>\s*<div>\s*<h3>(.*?)</h3>\s*'
        r'<p>(.*?)</p>', html, re.S)
    return [(word, title, " ".join(line.split())) for _, word, title, line in found]


@pytest.mark.parametrize("data,status,line", [
    ({"info": "public_only"}, "Done", "Not needed. It only uses public information."),
    ({"info": "customer_contact", **ALL_NO}, "Done", "Passed automatically against security&#39;s rules."),
    ({"info": "customer_contact", **ALL_NO, "ai_service": "not_sure"}, "Next",
     "A person from security will review this, because you answered Not sure about the AI service."),
    ({"info": ["sensitive_personal", "internal_notes"], **ALL_NO}, "Next",
     "A person from security will review this, because it uses sensitive personal information."),
    ({"info": "customer_contact", **ALL_NO, "sends_without_check": "yes", "ai_service": "something_else"}, "Next",
     "A person from security will review this, because you answered Yes to sending to customers without a person "
     "checking and you answered Something else about the AI service."),
])
def test_security_step_shows_this_requests_result(demo_client, data, status, line):
    html = demo_client.post("/", data={**BASE, **data}).text
    got = steps(html)
    assert [s[1] for s in got] == ["Security screening", "A reviewer decides", "You get a decision"]
    assert got[0][0] == status and got[0][2] == line


def test_the_other_two_steps(demo_client):
    html = demo_client.post("/", data={**BASE, "info": "public_only"}).text
    got = steps(html)
    assert got[1] == ("Next", "A reviewer decides", "Reviewers usually answer within 5 working days.")
    assert got[2][0] == "Later"
    assert got[2][2] == "You&#39;ll see the decision, the reason and what would change the answer on My requests."
    assert re.search(r'<li class="step-item is-next" aria-current="step">\s*<span class="step-status">', html)
    # Status is shown in words and icons, not color alone.
    assert html.count('class="step-status"><svg') == 3


def test_demo_heading_and_one_line(demo_client):
    html = demo_client.post("/", data={**BASE, "info": "public_only"}).text
    text = text_of(html)
    assert "Here's what would happen next This is the demo, so nothing was saved." in text.replace("&#39;", "'")
    assert "notice-info" not in html  # No separate banner.
    assert html.index("What happens next") < html.index("Your request")
    assert "Requested by" in text and "Information it uses" in text and BASE["task"] in text
    assert 'href="/" class="btn btn-secondary">Back to Request a tool</a>' in html
    assert 'href="/requests" class="btn">Go to My requests</a>' in html


def test_never_shows_claudes_read(demo_client, tmp_path, live_client, live_app):
    live_app.state.store.load_demo(live_app.state.demo)
    pages = [demo_client.post("/", data={**BASE, "info": "public_only"}).text,
             TestClient(preview_app(tmp_path)).post("/", data={**BASE, "info": "public_only"}).text]
    r = live_client.post("/", data={**BASE, "info": "public_only"})
    pages.append(r.text)
    for html in pages:
        assert "claude-read-h" not in html and "Claude&#39;s read" not in html and "Claude's read" not in html
        assert "A starting point. You decide." not in html


def test_reviewer_link_only_in_demo_and_preview(demo_client, tmp_path, live_client, live_app):
    link = "See this request the way a reviewer would"
    assert link in demo_client.post("/", data={**BASE, "info": "public_only"}).text
    assert link in TestClient(preview_app(tmp_path)).post("/", data={**BASE, "info": "public_only"}).text
    live_app.state.store.load_demo(live_app.state.demo)
    html = live_client.post("/", data={**BASE, "info": "public_only"}).text
    assert "<h1>Request sent</h1>" in html and link not in html
    assert "This is the demo" not in html
    # The link is a real button in a form, and live mode refuses the reviewer view.
    assert live_client.post("/review/sample", data={**BASE, "info": "public_only"},
                            follow_redirects=False).status_code == 303


def test_live_request_sent_page_is_the_requesters_own(live_app, live_client):
    store = live_app.state.store
    store.load_demo(live_app.state.demo)
    r = live_client.post("/", data={**BASE, "info": "public_only"}, follow_redirects=False)
    target = r.headers["location"]
    assert target.endswith("?submitted=1")
    html = live_client.get(target).text
    assert "<h1>Request sent</h1>" in html
    assert "Not needed. It only uses public information." in html
    # Someone else opening the same link sees the ordinary request page.
    live_client.cookies.set("sts_name", "Someone Else")
    assert "<h1>Request sent</h1>" not in live_client.get(target).text


def test_reviewer_view_shows_claudes_read_and_switches_to_reviewer(demo_client):
    r = demo_client.post("/review/sample", data={**BASE, "info": "public_only"})
    assert r.status_code == 200
    assert "claude-read-h" in r.text and "Review queue" in r.text
    assert "sts_viewer=reviewer" in r.headers["set-cookie"]
    assert "Just sent. Not saved, because this is the demo." in r.text
    assert "there&#39;s nothing to decide here" in r.text or "there's nothing to decide here" in r.text
    assert len(demo_client.app.state.store.list_requests()) == 11  # Nothing saved.


def test_reviewer_view_in_preview_uses_one_claude_call(tmp_path):
    app = preview_app(tmp_path)
    c = TestClient(app)
    calls = app.state.fake_messages.calls
    c.post("/", data={**BASE, "info": "public_only", "matches_json": "[]"})
    assert calls == []
    html = c.post("/review/sample", data={**BASE, "info": "public_only", "matches_json": "[]"}).text
    assert [x["output_format"].__name__ for x in calls] == ["SizeUp"]
    assert "Short follow-up emails" in html


def test_review_days_setting_shows_in_the_step(tmp_path):
    settings = Settings(requested_mode="demo", data_dir=tmp_path / "d", demo_dir=DEMO_DIR, review_days=1)
    html = TestClient(create_app(settings)).post("/", data={**BASE, "info": "public_only"}).text
    assert "Reviewers usually answer within 1 working day." in html
