from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from sts.config import ROOT, Settings
from sts.provider import ClaudeProvider, DraftReason, MatchResult, SizeUp
from sts.web import create_app

DEMO_DIR = ROOT / "demo"


class FakeMessages:
    """Stands in for client.beta.messages. Returns canned structured output."""

    def __init__(self, outputs):
        self.outputs = outputs
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        shape = kwargs["output_format"]
        value = self.outputs[shape.__name__]
        parsed = value(kwargs) if callable(value) else value
        return SimpleNamespace(stop_reason="end_turn", parsed_output=parsed)


def fake_client(outputs):
    msgs = FakeMessages(outputs)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


DEFAULT_OUTPUTS = {
    "MatchResult": MatchResult.model_validate(
        {"matches": [{"tool_id": "call-recap-writer", "confidence": "close", "reason": "It writes follow-up emails."}]}
    ),
    "SizeUp": SizeUp.model_validate(
        {
            "title": "Short follow-up emails",
            "bullets": [{"label": "Closest match", "text": "Call Recap Writer."}, {"label": "Worth asking", "text": "How often?"}],
            "security_check_needed": False,
        }
    ),
    "DraftReason": DraftReason(reason="Drafted reason text.", what_would_change="Drafted change text."),
}


@pytest.fixture
def demo_client(tmp_path):
    settings = Settings(requested_mode="demo", data_dir=tmp_path / "data", demo_dir=DEMO_DIR)
    return TestClient(create_app(settings))


@pytest.fixture
def live_app(tmp_path):
    settings = Settings(requested_mode="live", api_key="test-key", data_dir=tmp_path / "data", demo_dir=DEMO_DIR)
    client, msgs = fake_client(DEFAULT_OUTPUTS)
    provider = ClaudeProvider("test-key", "claude-sonnet-5-5", client=client)
    app = create_app(settings, provider=provider)
    app.state.fake_messages = msgs
    return app


@pytest.fixture
def live_client(live_app):
    c = TestClient(live_app)
    c.cookies.set("sts_name", "Avery Test")
    return c


def as_reviewer(client):
    client.cookies.set("sts_viewer", "reviewer")
    return client


def as_requester(client):
    client.cookies.set("sts_viewer", "requester")
    return client


def visible_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html)
    attrs = " ".join(re.findall(r'(?:aria-label|title|placeholder|alt|content)="([^"]*)"', html))
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    return text + " " + attrs
