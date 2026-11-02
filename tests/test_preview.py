"""Live preview: real Claude for three features, nothing saved, daily and per-visitor limits."""

import logging
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from sts.config import Settings
from sts.provider import MSG_LIMITED, CallLimiter, ClaudeProvider, MatchResult
from sts.web import create_app

from .conftest import DEFAULT_OUTPUTS, DEMO_DIR, as_reviewer, fake_client

SOCIAL = "posts for social media from our case studies"
SUBMIT = {"task": "Write invite and reminder emails for a webinar", "team": "Marketing", "how_often": "few_month",
          "who_uses": "my_team", "info": "public_only", "matches_json": "[]"}
LIMITED = "Today&#39;s live checks are used up, so you&#39;re seeing the sample version."
LIMITED_RAW = "Today's live checks are used up, so you're seeing the sample version."


def preview_app(tmp_path, daily=100, hourly=10, key="test-key"):
    settings = Settings(requested_mode="preview", api_key=key, data_dir=tmp_path / "data", demo_dir=DEMO_DIR,
                        daily_claude_calls=daily, visitor_claude_calls_per_hour=hourly)
    client, msgs = fake_client(dict(DEFAULT_OUTPUTS))
    app = create_app(settings, provider=ClaudeProvider(key, "claude-sonnet-5-5", client=client))
    app.state.fake_messages = msgs
    return app


def has_limited_notice(html):
    return LIMITED in html or LIMITED_RAW in html


def test_preview_mode_and_pill(tmp_path):
    app = preview_app(tmp_path)
    assert app.state.settings.mode == "preview"
    html = TestClient(app).get("/").text
    assert "Live preview: real Claude, nothing saved" in html and "mode-preview" in html
    assert "test-key" not in html


def test_preview_calls_claude_only_for_the_three_features(tmp_path):
    app = preview_app(tmp_path)
    calls = app.state.fake_messages.calls
    c = TestClient(app)
    for page in ["/", "/?from=r-1044", "/requests", "/tools", "/tools/translation-helper", "/decided", "/how-it-works",
                 "/requests/r-1044"]:
        assert c.get(page).status_code == 200
    as_reviewer(c)
    for page in ["/review", "/review/r-1047", "/tools/proposal-drafter"]:
        assert c.get(page).status_code == 200
    assert calls == []  # Opening pages never uses a Claude call.

    c.post("/api/matches", data={"task": "turn notes into an email"})
    assert [x["output_format"].__name__ for x in calls] == ["MatchResult"]
    c.cookies.set("sts_viewer", "requester")
    html = c.post("/", data=SUBMIT).text
    # Requesters never see Claude's read, so sending a request doesn't ask Claude for one.
    assert [x["output_format"].__name__ for x in calls] == ["MatchResult"]
    assert "Short follow-up emails" not in html and "Claude&#39;s read" not in html
    # "See this request the way a reviewer would" asks Claude for its read, on the button press.
    html = c.post("/review/sample", data=SUBMIT).text
    assert [x["output_format"].__name__ for x in calls] == ["MatchResult", "SizeUp"]
    assert "Short follow-up emails" in html and "Demo builds this from simple rules" not in html
    as_reviewer(c)
    r = c.post("/review/r-1048", data={"action": "draft", "outcome": "use_existing", "existing_tool_id": "call-recap-writer"})
    assert "Drafted reason text." in r.text
    assert c.post("/api/review/r-1048/draft", data={"outcome": "not_approved"}).json()["reason"] == "Drafted reason text."
    assert [x["output_format"].__name__ for x in calls] == ["MatchResult", "SizeUp", "DraftReason", "DraftReason"]

    # Saving actions stay off and never call Claude.
    before = len(calls)
    assert c.post("/review/r-1048", data={"action": "send", "outcome": "not_approved", "reason": "x",
                                          "what_would_change": "y"}).status_code == 400
    assert c.post("/review/r-1048", data={"action": "save"}).status_code == 400
    assert c.post("/tools/translation-helper/ship", data={"to_status": "approved"}).status_code == 400
    assert c.post("/requests/r-1047/need-too", data={"task": SOCIAL}).status_code == 400
    c.cookies.set("sts_viewer", "requester")
    assert c.post("/requests/r-1044/ask", data={"question": "Why?"}).status_code == 400
    assert len(calls) == before


def test_preview_saves_nothing_and_disables_saving_buttons(tmp_path):
    app = preview_app(tmp_path)
    c = TestClient(app)
    c.post("/", data=SUBMIT)
    c.post("/requests/r-1047/need-too", data={"task": SOCIAL})
    as_reviewer(c)
    html = c.get("/review/r-1048").text
    assert re.search(r'value="send" disabled', html)
    assert "The live preview doesn&#39;t save anything." in html or "The live preview doesn't save anything." in html
    html = c.get("/tools/translation-helper").text
    assert "disabled" in re.search(r"<button[^>]*>Ship it</button>", html).group(0)
    assert "disabled" in re.search(r"<button[^>]*>Extend the pilot</button>", html).group(0)
    c.cookies.set("sts_viewer", "requester")
    card = c.post("/api/matches", data={"task": SOCIAL}).text
    if "I need this too" in card:
        assert "disabled" in re.search(r"<button[^>]*>I need this too</button>", card).group(0)
    assert not (tmp_path / "data").exists()
    assert len(app.state.store.list_requests()) == 11
    assert len(app.state.store.get_request("r-1047").needed_by) == 2


def test_preview_daily_limit_falls_back_with_the_notice(tmp_path):
    app = preview_app(tmp_path, daily=2)
    calls = app.state.fake_messages.calls
    c = TestClient(app)
    for _ in range(2):
        html = c.post("/api/matches", data={"task": "turn notes into an email"}).text
        assert not has_limited_notice(html)
    assert len(calls) == 2
    r = c.post("/api/matches", data={"task": "Write invite and reminder emails for a webinar"})
    assert r.status_code == 200 and has_limited_notice(r.text)
    assert "Webinar Invite Writer" in r.text  # The demo word match.
    assert len(calls) == 2
    # Claude's read and drafts fall back too, never with an error page.
    r = c.post("/", data=SUBMIT)
    assert r.status_code == 200 and "what would happen next" in r.text
    r = c.post("/review/sample", data=SUBMIT)
    assert r.status_code == 200 and has_limited_notice(r.text) and "Claude's read" in r.text
    as_reviewer(c)
    r = c.post("/review/r-1048", data={"action": "draft", "outcome": "use_existing"})
    assert r.status_code == 200 and has_limited_notice(r.text)
    assert "Good news: Call Recap Writer already does this" in r.text  # The recorded draft.
    j = c.post("/api/review/r-1048/draft", data={"outcome": "use_existing"}).json()
    assert j["note"].startswith(LIMITED_RAW)
    assert len(calls) == 2
    assert app.state.limiter.used_today() == 2


def test_preview_per_visitor_limit(tmp_path):
    app = preview_app(tmp_path, daily=100, hourly=2)
    calls = app.state.fake_messages.calls
    c = TestClient(app)
    a = {"x-forwarded-for": "203.0.113.5"}
    b = {"x-forwarded-for": "198.51.100.7, 10.0.0.1"}
    for _ in range(2):
        assert not has_limited_notice(c.post("/api/matches", data={"task": "notes"}, headers=a).text)
    assert has_limited_notice(c.post("/api/matches", data={"task": "notes"}, headers=a).text)
    assert not has_limited_notice(c.post("/api/matches", data={"task": "notes"}, headers=b).text)
    assert len(calls) == 3


def test_limiter_resets_at_midnight_utc_and_after_an_hour():
    now = [datetime(2026, 11, 1, 23, 30, tzinfo=timezone.utc)]
    limiter = CallLimiter(daily=2, per_visitor_hour=10, now=lambda: now[0])
    assert limiter.allow("a") and limiter.allow("b") and not limiter.allow("c")
    now[0] = datetime(2026, 11, 2, 0, 0, 1, tzinfo=timezone.utc)
    assert limiter.used_today() == 0 and limiter.allow("c")

    limiter = CallLimiter(daily=100, per_visitor_hour=1, now=lambda: now[0])
    assert limiter.allow("a") and not limiter.allow("a") and limiter.allow("b")
    now[0] += timedelta(minutes=61)
    assert limiter.allow("a")


def test_visitor_key_is_a_hash_of_the_address():
    limiter = CallLimiter(10, 10)
    key = limiter.visitor_key("203.0.113.5")
    assert key != "203.0.113.5" and "203.0.113" not in key and len(key) == 64
    assert key == limiter.visitor_key("203.0.113.5") != limiter.visitor_key("203.0.113.6")


def test_preview_falls_back_quietly_when_claude_cant_answer(tmp_path):
    from sts.provider import ClaudeUnavailable

    app = preview_app(tmp_path)

    def broken(kwargs):
        raise ClaudeUnavailable("down")
    app.state.fake_messages.outputs["MatchResult"] = broken
    try:
        r = TestClient(app).post("/api/matches", data={"task": "Write invite and reminder emails for a webinar"})
    except ClaudeUnavailable:
        pytest.fail("preview should fall back")
    assert r.status_code == 200 and "Webinar Invite Writer" in r.text


def test_preview_uses_real_claude_for_asked_before_and_in_review(tmp_path):
    app = preview_app(tmp_path)
    app.state.fake_messages.outputs["MatchResult"] = MatchResult.model_validate({
        "matches": [], "related_decision": {"request_id": "r-1044", "reason": "Same auto-reply."},
        "related_request": {"request_id": "r-1047", "reason": "Same posts."}})
    html = TestClient(app).post("/api/matches", data={"task": SOCIAL}).text
    assert "Asked before" in html and "Same auto-reply." in html
    assert "Someone already asked for something like this." in html and "Same posts." in html
    sent = app.state.fake_messages.calls[-1]["messages"][0]["content"]
    assert "Owen Pratt" not in sent and "Priya Raman" not in sent


def test_preview_without_a_key_falls_back_to_demo_with_a_notice(tmp_path):
    settings = Settings(requested_mode="preview", api_key="", data_dir=tmp_path / "d", demo_dir=DEMO_DIR)
    assert settings.mode == "demo" and settings.fell_back
    app = create_app(settings)
    html = TestClient(app).get("/").text
    assert "Live preview is turned on, but no API key is set." in html
    assert "Demo: sample data" in html and "Live preview: real Claude" not in html
    assert app.state.limiter is None
    assert not (tmp_path / "d").exists()


def test_preview_from_env(monkeypatch):
    monkeypatch.setenv("STS_MODE", "preview")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("STS_DAILY_CLAUDE_CALLS", "7")
    monkeypatch.setenv("STS_VISITOR_CLAUDE_CALLS_PER_HOUR", "3")
    s = Settings.from_env()
    assert s.mode == "preview" and s.daily_claude_calls == 7 and s.visitor_claude_calls_per_hour == 3
    monkeypatch.delenv("STS_DAILY_CLAUDE_CALLS")
    monkeypatch.delenv("STS_VISITOR_CLAUDE_CALLS_PER_HOUR")
    s = Settings.from_env()
    assert s.daily_claude_calls == 100 and s.visitor_claude_calls_per_hour == 10
    assert "api_key" not in repr(s)


def test_preview_never_logs_the_key_or_visitor_text(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    app = preview_app(tmp_path, key="sk-secret-preview-key")
    c = TestClient(app)
    c.post("/api/matches", data={"task": "A very private visitor sentence"})
    c.post("/", data={**SUBMIT, "task": "A very private visitor sentence"})
    logs = caplog.text
    assert "sk-secret-preview-key" not in logs and "A very private visitor sentence" not in logs
    for page in ("/", "/tools", "/how-it-works"):
        assert "sk-secret-preview-key" not in c.get(page).text
