from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from sts.config import ROOT, Settings
from sts.fake_claude import DEFAULT_OUTPUTS, FakeMessages, fake_client  # noqa: F401 (tests import these from here)
from sts.provider import ClaudeProvider
from sts.web import create_app

DEMO_DIR = ROOT / "demo"


@pytest.fixture
def demo_client(tmp_path):
    settings = Settings(requested_mode="demo", data_dir=tmp_path / "data", demo_dir=DEMO_DIR)
    return TestClient(create_app(settings))


@pytest.fixture
def live_app(tmp_path):
    # The demo data fills every pilot slot (3 of 3). These tests are about other rules, so they get room
    # for more pilots. tests/test_pilot_slots.py covers the default limit.
    settings = Settings(requested_mode="live", api_key="test-key", data_dir=tmp_path / "data", demo_dir=DEMO_DIR,
                        pilot_slots=10)
    client, msgs = fake_client(dict(DEFAULT_OUTPUTS))
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
