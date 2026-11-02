"""Live mode may already have a database from the first version. Startup upgrades it in place."""

import json
import sqlite3

from fastapi.testclient import TestClient

from sts.config import Settings
from sts.store import LiveStore
from sts.web import create_app

from .conftest import DEMO_DIR, as_reviewer

# The tables exactly as the first version of the app created them.
V1_SCHEMA = """
CREATE TABLE tool (
    id VARCHAR NOT NULL, name VARCHAR NOT NULL, purpose VARCHAR NOT NULL, owner_name VARCHAR NOT NULL,
    owner_team VARCHAR NOT NULL, teams JSON, status VARCHAR NOT NULL, allowed_info JSON, limits VARCHAR,
    trial_ends DATE, next_review VARCHAR, link VARCHAR, replaced_by VARCHAR, from_request VARCHAR,
    owner_agreed BOOLEAN NOT NULL, PRIMARY KEY (id)
);
CREATE TABLE request (
    id VARCHAR NOT NULL, title VARCHAR NOT NULL, task VARCHAR NOT NULL, team VARCHAR NOT NULL,
    how_often VARCHAR NOT NULL, who_uses VARCHAR NOT NULL, info JSON, extra VARCHAR, whats_missing VARCHAR,
    requester_name VARCHAR NOT NULL, submitted_at DATETIME NOT NULL, status VARCHAR NOT NULL, matches JSON,
    matches_seen BOOLEAN NOT NULL, size_up JSON, copied_from VARCHAR, questions JSON, timeline JSON, draft JSON,
    PRIMARY KEY (id)
);
CREATE TABLE decision (
    id INTEGER NOT NULL, request_id VARCHAR NOT NULL, outcome VARCHAR NOT NULL, checklist JSON,
    existing_tool_id VARCHAR, limits VARCHAR, reason VARCHAR NOT NULL, what_would_change VARCHAR NOT NULL,
    reason_drafted_by_claude BOOLEAN NOT NULL, reason_edited BOOLEAN NOT NULL, decided_by VARCHAR NOT NULL,
    decided_at DATETIME NOT NULL, PRIMARY KEY (id)
);
CREATE INDEX ix_decision_request_id ON decision (request_id);
"""


def tool_row(id, name, status, *, info=("public_only",), trial_ends=None, from_request=None, next_review=None,
             limits=None):
    return (id, name, f"{name} does a job.", "Ana Ferreira", "Marketing", json.dumps(["Marketing"]), status,
            json.dumps(list(info)), limits, trial_ends, next_review, None, None, from_request, 1)


def make_v1_database(data_dir):
    data_dir.mkdir(parents=True)
    db = sqlite3.connect(data_dir / "sts.db")
    db.executescript(V1_SCHEMA)
    db.executemany("INSERT INTO tool VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        tool_row("recap-tool", "Recap Tool", "being_tried", trial_ends="2026-12-01", from_request="r-2001"),
        tool_row("notes-helper", "Notes Helper", "being_tried", info=("customer_contact",), trial_ends="2026-10-01"),
        tool_row("old-drafter", "Old Drafter", "approved", next_review="January 2026"),
        tool_row("gone-tool", "Gone Tool", "retired"),
    ])
    db.execute("INSERT INTO request VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
        "r-2001", "Webinar recaps", "Write webinar recaps.", "Marketing", "rarely", "my_team",
        json.dumps(["public_only"]), None, None, "Sam Rivera", "2026-09-01 09:00:00.000000", "decided", "[]", 1,
        None, None, "[]",
        json.dumps([{"label": "Submitted", "date": "2026-09-01"}, {"label": "Security check done", "date": "2026-09-03"},
                    {"label": "Decided", "date": "2026-09-05"}]), None))
    db.execute("INSERT INTO decision VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
        1, "r-2001", "approve", json.dumps({"already_exists": "no", "sends_without_check": "no",
                                            "uses_customer_details": "no", "security_check": "done"}),
        None, None, "Approved.", "Nothing.", 1, 0, "Jordan Ellis", "2026-09-05 15:00:00.000000"))
    db.commit()
    db.close()


def test_startup_upgrade_keeps_existing_data_and_builds_journeys(tmp_path):
    data_dir = tmp_path / "data"
    make_v1_database(data_dir)
    store = LiveStore(data_dir)

    cols = {row[1] for row in sqlite3.connect(data_dir / "sts.db").execute("PRAGMA table_info(tool)")}
    assert {"security_check", "trial_extended", "ready_check", "journey"} <= cols
    req_cols = {row[1] for row in sqlite3.connect(data_dir / "sts.db").execute("PRAGMA table_info(request)")}
    assert {"security_answers", "security_result", "needed_by"} <= req_cols
    old = store.get_request("r-2001")
    assert old.needed_by == [] and old.security_answers == {} and old.security_result is None

    tools = {t.id: t for t in store.list_tools()}
    assert set(tools) == {"recap-tool", "notes-helper", "old-drafter", "gone-tool"}
    assert tools["recap-tool"].name == "Recap Tool" and str(tools["recap-tool"].trial_ends) == "2026-12-01"
    assert tools["old-drafter"].next_review == "January 2026"
    assert store.get_request("r-2001").requester_name == "Sam Rivera"
    assert store.decision_for("r-2001").reason == "Approved."

    recap = tools["recap-tool"]
    assert [e["kind"] for e in recap.journey] == ["requested", "security_done", "being_tried"]
    assert [e["date"] for e in recap.journey] == ["2026-09-01", "2026-09-03", "2026-09-05"]
    assert recap.security_check == "done" and recap.ready_check == {} and recap.trial_extended is False
    # No decision and customer details: the security check needs recording.
    assert tools["notes-helper"].security_check == "needed"
    assert [e["kind"] for e in tools["notes-helper"].journey] == ["being_tried"]
    assert [e["kind"] for e in tools["old-drafter"].journey] == ["shipped"]
    assert [e["kind"] for e in tools["gone-tool"].journey] == ["retired"]
    assert all(e["date"] for t in tools.values() for e in t.journey)


def test_upgrade_runs_once_and_keeps_later_changes(tmp_path):
    data_dir = tmp_path / "data"
    make_v1_database(data_dir)
    store = LiveStore(data_dir)
    tool = store.get_tool("recap-tool")
    tool.ready_check = {"kept_using": "regularly", "went_wrong": "Nothing"}
    store.save(tool)
    again = LiveStore(data_dir)
    tool = again.get_tool("recap-tool")
    assert tool.ready_check == {"kept_using": "regularly", "went_wrong": "Nothing"}
    assert len(tool.journey) == 3


def test_upgraded_database_works_in_the_app(tmp_path):
    data_dir = tmp_path / "data"
    make_v1_database(data_dir)
    from .conftest import DEFAULT_OUTPUTS, fake_client
    from sts.provider import ClaudeProvider

    client, _ = fake_client(DEFAULT_OUTPUTS)
    settings = Settings(requested_mode="live", api_key="test-key", data_dir=data_dir, demo_dir=DEMO_DIR)
    app = create_app(settings, provider=ClaudeProvider("test-key", "claude-sonnet-5-5", client=client))
    c = TestClient(app)
    c.cookies.set("sts_name", "Avery Test")
    as_reviewer(c)
    html = c.get("/tools/recap-tool").text
    assert "Ready to ship?" in html and "2 of 4 ready" in html and "Its journey" in html
    html = c.get("/tools/notes-helper").text
    assert "1 of 4 ready" in html and "Record the security screening" in html
    review = c.get("/review").text
    assert "Notes Helper" in review and "Old Drafter" in review  # Trial ended and Review due
    assert c.get("/tools/old-drafter").status_code == 200
    # A request saved before the automatic security check still opens for reviewers.
    assert c.get("/review/r-2001").status_code == 200
