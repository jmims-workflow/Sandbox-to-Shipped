"""Request a tool starts empty, and each "Try an example" button fills the whole form."""

import re
import shutil
import socket
import subprocess
import threading
import time

import pytest
import uvicorn
from fastapi.testclient import TestClient

from sts.config import ROOT, Settings
from sts.web import create_app

from .conftest import DEMO_DIR, visible_text

EXAMPLES = {
    "follow-up-emails": {"label": "Follow-up emails", "team": "Sales", "how_often": "few_week", "who_uses": "my_team",
                         "info": ["customer_contact", "deal_pricing"], "task": "After a discovery call, turn my notes"},
    "auto-reply": {"label": "Auto-reply to demo requests", "team": "Sales", "how_often": "every_day",
                   "who_uses": "several_teams", "info": ["customer_contact"], "task": "When someone asks for a demo"},
    "social-posts": {"label": "Social posts from case studies", "team": "Marketing", "how_often": "few_month",
                     "who_uses": "my_team", "info": ["public_only"], "task": "Turn each new case study"},
}


def task_value(html):
    return re.search(r'<textarea id="task"[^>]*>(.*?)</textarea>', html, re.S).group(1)


def checked(html, name):
    return re.findall(rf'name="{name}" value="([^"]+)"[^>]* checked', html)


def selected_team(html):
    m = re.search(r'<option value="([^"]+)" selected>', html[html.index('id="team"'):])
    return m.group(1) if m else ""


@pytest.fixture(params=["demo", "preview", "live"])
def any_mode_client(request, tmp_path):
    key = "" if request.param == "demo" else "test-key"
    settings = Settings(requested_mode=request.param, api_key=key, data_dir=tmp_path / "data", demo_dir=DEMO_DIR)
    c = TestClient(create_app(settings))
    c.cookies.set("sts_name", "Avery Test")
    return c


def test_form_starts_empty_in_every_mode(any_mode_client):
    html = any_mode_client.get("/").text
    assert task_value(html) == ""
    assert selected_team(html) == ""
    for name in ("how_often", "who_uses", "info", "sends_without_check", "keeps_elsewhere"):
        assert checked(html, name) == [], name
    assert "Describe the task, not the tool." in html  # The hint under the label stays.
    assert "Describe what you're trying to do, and we'll check the tools Northstar already has." in html


def test_example_row_has_three_links(demo_client):
    html = demo_client.get("/").text
    assert "Not sure what to write? Try an example:" in html
    for key, ex in EXAMPLES.items():
        assert f'<a class="btn btn-secondary" href="/?example={key}">{ex["label"]}</a>' in html
    # The row comes before the form.
    assert html.index("Try an example") < html.index('<form id="request-form"')


@pytest.mark.parametrize("key", list(EXAMPLES))
def test_each_example_fills_the_whole_form(demo_client, key):
    ex = EXAMPLES[key]
    html = demo_client.get(f"/?example={key}").text
    assert task_value(html).startswith(ex["task"])
    assert selected_team(html) == ex["team"]
    assert checked(html, "how_often") == [ex["how_often"]]
    assert checked(html, "who_uses") == [ex["who_uses"]]
    assert checked(html, "info") == ex["info"]
    assert f"Example filled in: {ex['label']}." in html


def test_follow_up_example_shows_call_recap_writer(demo_client):
    html = demo_client.get("/?example=follow-up-emails").text
    assert "Claude thinks <strong>Call Recap Writer</strong> is a close match for what you described." in html
    assert "Asked before" not in html and "I need this too" not in html
    assert checked(html, "ai_service") == [] and '<option value="claude" selected>' in html


def test_auto_reply_example_shows_the_sends_warning_and_asked_before(demo_client):
    html = demo_client.get("/?example=auto-reply").text
    assert checked(html, "sends_without_check") == ["yes"]
    warning = re.search(r'<p class="early-warning" id="warn-sends_without_check"[^>]*>(.*?)</p>', html, re.S).group(1)
    assert "Heads up: Northstar doesn" in warning
    assert "Asked before" in html and "Reply to inbound demo requests automatically" in html
    assert 'value="Replies can take a day right now, and people lose interest."' in html


def test_social_posts_example_shows_i_need_this_too(demo_client):
    html = demo_client.get("/?example=social-posts").text
    assert "I need this too" in html and "Social posts from case studies" in html
    assert "formaction=\"/requests/r-1047/need-too\"" in html


def test_unknown_example_gives_an_empty_form(demo_client):
    r = demo_client.get("/?example=nope")
    assert r.status_code == 200 and task_value(r.text) == ""


def test_examples_in_preview_never_call_claude(tmp_path):
    from .test_preview import preview_app

    app = preview_app(tmp_path)
    c = TestClient(app)
    for key in EXAMPLES:
        assert c.get(f"/?example={key}").status_code == 200
    assert app.state.fake_messages.calls == []


def test_match_card_wording(demo_client):
    html = demo_client.post("/api/matches", data={"task": SOCIAL_TASK}).text
    assert "You may already have what you need" in html
    assert "You may already have this<" not in html
    assert "Claude thinks <strong>Case Study Builder</strong> is a possible match for what you described. " \
           "Claude is less sure." in html
    html = demo_client.get("/?example=follow-up-emails").text
    card = html[html.index('class="match-card"'):]
    card = card[:card.index("</article>")]
    text = " ".join(visible_text(card).split())
    # The outcome comes first, then the reason, purpose, information, owner and links.
    order = ["Claude thinks", "It turns call notes", "Okay to use with", "Owner: Dana Whitfield",
             "See it in the inventory", "Try it before you submit"]
    assert [text.index(x) for x in order] == sorted(text.index(x) for x in order)
    assert "Open the tool" not in html


SOCIAL_TASK = "Turn each new case study into a few social media posts and a short blurb for our newsletter."


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def node_playwright():
    node = shutil.which("node")
    if not node:
        return None
    ok = subprocess.run([node, "-e", "require('playwright')"], cwd=ROOT, capture_output=True).returncode == 0
    return node if ok else None


def test_examples_with_javascript_in_a_real_browser(tmp_path):
    node = node_playwright()
    if not node:
        pytest.skip("Needs Node with Playwright.")
    settings = Settings(requested_mode="demo", data_dir=tmp_path / "data", demo_dir=DEMO_DIR)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        out = subprocess.run([node, str(ROOT / "scripts" / "check_examples.js"), f"http://127.0.0.1:{port}"],
                             cwd=ROOT, capture_output=True, text=True, timeout=120)
        if "Executable doesn't exist" in out.stderr or "browserType.launch" in out.stderr:
            pytest.skip("Playwright has no browser installed here.")
        assert out.returncode == 0 and out.stdout.strip() == "ok", out.stdout + out.stderr
    finally:
        server.should_exit = True
        thread.join(timeout=5)
