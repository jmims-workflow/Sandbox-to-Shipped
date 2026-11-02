"""STS_FAKE_CLAUDE: live mode with the stand-in Claude client, for development only."""

import socket

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from sts.cli import app as cli_app
from sts.config import ROOT, Settings, StartupError
from sts.web import create_app

from .conftest import DEMO_DIR, as_reviewer

NEW_REQUEST = {"task": "Turn my call notes into a short follow-up email", "team": "Sales",
               "how_often": "few_week", "who_uses": "my_team", "info": ["customer_contact"],
               "sends_without_check": "no", "keeps_elsewhere": "no", "ai_service": "not_sure"}


@pytest.mark.parametrize("mode", ["demo", "preview"])
def test_refused_in_demo_and_preview(tmp_path, mode):
    settings = Settings(requested_mode=mode, fake_claude=True, data_dir=tmp_path / "d", demo_dir=DEMO_DIR)
    with pytest.raises(StartupError, match="live mode only"):
        create_app(settings)


def test_refused_with_a_real_key(tmp_path):
    settings = Settings(requested_mode="live", api_key="sk-real", fake_claude=True, data_dir=tmp_path / "d",
                        demo_dir=DEMO_DIR)
    with pytest.raises(StartupError, match="ANTHROPIC_API_KEY"):
        create_app(settings)


@pytest.mark.parametrize("env", [
    {"STS_MODE": "demo", "STS_FAKE_CLAUDE": "1"},
    {"STS_MODE": "preview", "STS_FAKE_CLAUDE": "1"},
    {"STS_MODE": "live", "STS_FAKE_CLAUDE": "1", "ANTHROPIC_API_KEY": "sk-real"},
])
@pytest.mark.parametrize("command", [["serve"], ["seed", "--reset", "--yes"]])
def test_the_command_line_refuses_to_start_and_says_why(monkeypatch, tmp_path, env, command):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "d"))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    result = CliRunner().invoke(cli_app, command)
    assert result.exit_code == 1
    assert "Not starting: STS_FAKE_CLAUDE" in result.output
    assert not (tmp_path / "d").exists()


def test_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("STS_FAKE_CLAUDE", "1")
    assert Settings.from_env().fake_claude
    monkeypatch.setenv("STS_FAKE_CLAUDE", "")
    assert not Settings.from_env().fake_claude


def test_live_mode_works_with_no_key_and_no_network(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("the stand-in tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    settings = Settings(requested_mode="live", fake_claude=True, data_dir=tmp_path / "d", demo_dir=DEMO_DIR)
    assert settings.mode == "live" and not settings.fell_back and settings.startup_problem() is None
    app = create_app(settings)
    app.state.store.load_demo(app.state.demo)
    client = TestClient(app)
    client.cookies.set("sts_name", "Avery Test")
    assert "close match" in client.post("/", data={"action": "check", **NEW_REQUEST}).text
    r = client.post("/", data=NEW_REQUEST, follow_redirects=False)
    assert r.status_code == 303
    rid = r.headers["location"].split("/requests/")[1].split("?")[0]
    saved = app.state.store.get_request(rid)
    assert saved.title == "Short follow-up emails" and saved.status == "waiting"
    assert saved.security_result["result"] == "person"
    as_reviewer(client)
    assert client.get(f"/review/{rid}").status_code == 200
    assert (tmp_path / "d" / "sts.db").exists()
    calls = app.state.provider._client.beta.messages.calls
    assert calls and all(c["model"] == settings.model for c in calls)


def test_never_mentioned_in_the_pages():
    for path in [*(ROOT / "templates").rglob("*.html"), ROOT / "static" / "app.js"]:
        assert "FAKE_CLAUDE" not in path.read_text(encoding="utf-8"), path
