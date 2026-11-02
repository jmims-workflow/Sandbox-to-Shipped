"""Not now: a good idea at the wrong time, with a date to look again."""

import re
import sqlite3
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from sts.config import Settings
from sts.demo_data import load_demo_data
from sts.models import Decision, Request
from sts.rules import (
    Checklist,
    DecisionForm,
    RequestChangeError,
    add_months,
    add_needed_by,
    build_decision,
    reopen_request,
    revisit_due,
    revisit_is_due,
    validate_decision,
)
from sts.store import LiveStore
from sts.web import create_app

from .conftest import DEFAULT_OUTPUTS, DEMO_DIR, as_requester, as_reviewer, fake_client, visible_text

TODAY = date(2027, 3, 10)
DATA = load_demo_data(DEMO_DIR)


def form(**kw):
    base = dict(outcome="not_now", reason="Good idea, wrong time.", what_would_change="A free pilot slot.",
                revisit_on=add_months(TODAY, 3),
                checklist=Checklist(already_exists="no", sends_without_check="no", uses_customer_details="no",
                                    security_check="not_needed"))
    base.update(kw)
    return DecisionForm(**base)


def request(rid="r-9", status="decided", needed_by=()):
    return Request(id=rid, title="Video messages", task="t", team="Sales", how_often="rarely", who_uses="just_me",
                   info=["public_only"], requester_name="Malik Johnson", submitted_at=datetime(2027, 1, 1, 9),
                   status=status, needed_by=list(needed_by), timeline=[{"label": "Decided", "date": "2027-01-05"}])


def decision(revisit, rid="r-9", outcome="not_now", decided=datetime(2027, 1, 5, 15)):
    return Decision(request_id=rid, outcome=outcome, reason="r", what_would_change="w", decided_by="Jordan Ellis",
                    decided_at=decided, revisit_on=revisit)


# ---- The rules ----------------------------------------------------------------------------


def test_not_now_needs_a_reason_what_would_change_and_a_date():
    assert validate_decision(form(), [], today=TODAY) == {}
    errors = validate_decision(form(reason=" ", what_would_change="", revisit_on=None), [], today=TODAY)
    assert set(errors) == {"reason", "what_would_change", "revisit_on"}
    assert errors["revisit_on"] == "Pick the date to look at this again."


@pytest.mark.parametrize("revisit,ok", [
    (TODAY - timedelta(days=1), False),
    (TODAY, False),
    (TODAY + timedelta(days=1), True),
    (add_months(TODAY, 6), True),
    (add_months(TODAY, 6) + timedelta(days=1), False),
])
def test_revisit_date_is_after_today_and_within_6_months(revisit, ok):
    errors = validate_decision(form(revisit_on=revisit), [], today=TODAY)
    assert ("revisit_on" not in errors) is ok, errors


def test_too_far_names_the_latest_date():
    errors = validate_decision(form(revisit_on=add_months(TODAY, 7)), [], today=TODAY)
    assert errors["revisit_on"] == "Pick a date within 6 months, September 10, 2027 at the latest."


def test_the_date_is_saved_only_for_not_now():
    d = build_decision(form(), request(status="waiting"), "Jordan Ellis", datetime(2027, 3, 10, 12))
    assert d.outcome == "not_now" and d.revisit_on == add_months(TODAY, 3)
    d = build_decision(form(outcome="not_approved"), request(status="waiting"), "Jordan Ellis",
                       datetime(2027, 3, 10, 12))
    assert d.revisit_on is None


@pytest.mark.parametrize("days,due", [(-1, False), (0, True), (1, True), (30, True)])
def test_revisit_comes_due_on_the_date(days, due):
    revisit = TODAY - timedelta(days=days)  # days > 0: the date has passed.
    r, d = request(needed_by=[{"name": "A", "date": "2027-01-06"}]), decision(revisit)
    assert revisit_is_due(r, d, TODAY) is due
    items = revisit_due([r], [d], TODAY)
    assert bool(items) is due
    if due:
        assert items[0]["line"] == "Revisit: Not now since January 5, 2027. Needed by 2 people."


def test_only_not_now_decided_requests_come_back():
    past = TODAY - timedelta(days=1)
    assert not revisit_due([request()], [decision(past, outcome="not_approved")], TODAY)
    assert not revisit_due([request(status="waiting")], [decision(past)], TODAY)
    # A newer decision replaces the Not now.
    newer = decision(None, outcome="not_approved", decided=datetime(2027, 3, 1, 9))
    assert not revisit_due([request()], [decision(past), newer], TODAY)


def test_reopen_keeps_history():
    r, d = request(), decision(TODAY)
    reopen_request(r, d, TODAY)
    assert r.status == "waiting"
    assert [e["label"] for e in r.timeline] == ["Decided", "Reopened after Not now"]
    with pytest.raises(RequestChangeError):
        reopen_request(request(), decision(TODAY + timedelta(days=1)), TODAY)


def test_i_need_this_too_works_on_not_now():
    r = request()
    add_needed_by(r, "Grace Liu", "Us too.", TODAY, "not_now")
    assert r.needed_by[0]["name"] == "Grace Liu"
    with pytest.raises(RequestChangeError):
        add_needed_by(request(), "Grace Liu", "", TODAY, "not_approved")


# ---- Demo data ----------------------------------------------------------------------------


def test_demo_not_now_requests():
    reqs = {r.id: r for r in DATA.requests}
    decs = {d.request_id: d for d in DATA.decisions}
    today = DATA.as_of
    video, usage = decs["r-1050"], decs["r-1051"]
    assert reqs["r-1050"].title == "Personalized video messages for prospects" and reqs["r-1050"].team == "Sales"
    assert video.outcome == "not_now" and video.decided_at.date() == today - timedelta(days=5)
    assert video.revisit_on == add_months(today, 3)
    assert video.what_would_change == "A pilot slot opening up, or a version that reuses an approved tool."
    assert "pilot slots are in use" in video.reason
    assert reqs["r-1051"].team == "Customer success" and usage.outcome == "not_now"
    assert usage.decided_at.date() == add_months(today, -3) and usage.revisit_on == today - timedelta(days=2)
    assert len(reqs["r-1051"].needed_by) == 3
    items = revisit_due(DATA.requests, DATA.decisions, today)
    assert [i["request"].id for i in items] == ["r-1051"]
    assert items[0]["line"].endswith("Needed by 4 people.")


def test_demo_review_queue_shows_the_revisit(demo_client):
    as_reviewer(demo_client)
    html = demo_client.get("/review").text
    needs = html[html.index('id="needs-h"'):html.index("</section>", html.index('id="needs-h"'))]
    assert 'href="/review/r-1051"' in needs
    assert "Revisit: Not now since" in needs and "Needed by 4 people." in needs
    assert "label-notnow" in needs and "Not now" in needs
    html = demo_client.get("/review/r-1051").text
    assert "Reopen it" in html and "Decide again" in html
    assert re.search(r'value="reopen" disabled', html)  # Demo saves nothing.
    # The other Not now isn't due yet: no reopen, no new decision.
    html = demo_client.get("/review/r-1050").text
    assert "Reopen it" not in html and 'id="decision-form"' not in html


def test_requester_page_wording(demo_client):
    html = demo_client.get("/requests/r-1050").text
    month = add_months(date.today(), 3)
    assert f"Not now. We'll look at this again in {month:%B} {month.year}." in html
    assert "A pilot slot opening up, or a version that reuses an approved tool." in html
    assert "decision-card is-notnow" in html


def test_decided_before_shows_not_now_with_its_month(demo_client):
    html = demo_client.get("/decided?outcome=not_now").text
    month = add_months(date.today(), 3)
    assert "2 decisions." in html
    assert f"We'll look at this again in {month:%B} {month.year}." in html
    assert '<option value="not_now" selected>Not now</option>' in html
    for name in ("Malik Johnson", "Hana Kim", "Diego Alvarez"):
        assert name not in visible_text(html)


def test_not_now_label_uses_its_own_colors():
    from sts.config import ROOT
    css = (ROOT / "static" / "style.css").read_text()
    assert "--notnow-text: #334155;" in css and "--notnow-fill: #E2E8F0;" in css
    assert ".label-notnow { background: var(--notnow-fill); color: var(--notnow-text); }" in css


def test_demo_draft_supports_not_now(demo_client):
    as_reviewer(demo_client)
    html = demo_client.post("/review/r-1047", data={"action": "draft", "outcome": "not_now"}).text
    assert "three people need them" in html


# ---- Live, end to end -------------------------------------------------------------------------


@pytest.fixture
def live(tmp_path):
    settings = Settings(requested_mode="live", api_key="k", data_dir=tmp_path / "data", demo_dir=DEMO_DIR)
    client, msgs = fake_client(dict(DEFAULT_OUTPUTS))
    from sts.provider import ClaudeProvider
    app = create_app(settings, provider=ClaudeProvider("k", "m", client=client))
    app.state.store.load_demo(app.state.demo)
    app.state.fake_messages = msgs
    c = TestClient(app)
    c.cookies.set("sts_name", "Jordan Ellis")
    return app, c


def not_now_post(**extra):
    return {"action": "send", "outcome": "not_now", "already_exists": "no", "sends_without_check": "no",
            "uses_customer_details": "yes", "security_check": "passed", "reason": "Good idea, no room yet.",
            "what_would_change": "A pilot slot opening up.",
            "revisit_on": add_months(date.today(), 3).isoformat(), **extra}


def test_live_not_now_end_to_end(live):
    app, c = live
    store = app.state.store
    as_reviewer(c)
    assert c.post("/review/r-1047", data=not_now_post(revisit_on=""), follow_redirects=False).status_code == 400
    far = (add_months(date.today(), 6) + timedelta(days=1)).isoformat()
    r = c.post("/review/r-1047", data=not_now_post(revisit_on=far), follow_redirects=False)
    assert r.status_code == 400 and "Pick a date within 6 months" in r.text
    assert c.post("/review/r-1047", data=not_now_post(), follow_redirects=False).status_code == 303
    d = store.decision_for("r-1047")
    assert d.outcome == "not_now" and d.revisit_on == add_months(date.today(), 3)
    # The requester sees it, and someone else can still say they need it too.
    c.cookies.set("sts_name", "Owen Pratt")
    as_requester(c)
    month = add_months(date.today(), 3)
    assert f"We'll look at this again in {month:%B} {month.year}." in c.get("/requests/r-1047").text
    c.cookies.set("sts_name", "New Person")
    social = store.get_request("r-1047").task
    card = c.post("/api/matches", data={"task": social}).text
    r = c.post("/requests/r-1047/need-too", data={"task": social, "need_note": "Us too."}, follow_redirects=False)
    assert r.status_code == 303
    assert "New Person" in [p["name"] for p in store.get_request("r-1047").needed_by]
    assert "New Person" not in card


def test_live_revisit_reopen_keeps_history(live):
    app, c = live
    store = app.state.store
    as_reviewer(c)
    assert "Revisit: Not now since" in c.get("/review").text
    r = c.post("/review/r-1051", data={"action": "reopen"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/review/r-1051?reopened=1"
    req = store.get_request("r-1051")
    assert req.status == "waiting"
    assert [e["label"] for e in req.timeline][-1] == "Reopened after Not now"
    assert len(req.needed_by) == 3
    # The old decision is kept, still on Decided before.
    assert [d.outcome for d in store.list_decisions() if d.request_id == "r-1051"] == ["not_now"]
    assert "Summarize Connect usage reports" in c.get("/decided?outcome=not_now").text
    assert "Revisit: Not now since" not in c.get("/review").text
    # The requester sees it waiting again, without the old decision card.
    c.cookies.set("sts_name", "Hana Kim")
    as_requester(c)
    page = c.get("/requests/r-1051").text
    assert "Waiting for a reviewer" in page and "Reopened after Not now" in page
    # Reopening twice is refused.
    as_reviewer(c)
    assert c.post("/review/r-1051", data={"action": "reopen"}).status_code == 400


def test_live_decide_again_after_revisit(live):
    app, c = live
    store = app.state.store
    as_reviewer(c)
    r = c.post("/review/r-1051", data={**not_now_post(), "outcome": "not_approved"}, follow_redirects=False)
    assert r.status_code == 303
    assert store.decision_for("r-1051").outcome == "not_approved"
    assert len([d for d in store.list_decisions() if d.request_id == "r-1051"]) == 2
    assert store.get_request("r-1051").timeline[-1]["label"] == "Decided again"
    # Not due any more, so a third decision is refused.
    assert c.post("/review/r-1051", data=not_now_post()).status_code == 400
    # A Not now not yet due can't be decided again.
    assert c.post("/review/r-1050", data={**not_now_post(), "outcome": "not_approved"}).status_code == 400


def test_upgrade_adds_revisit_on(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    con = sqlite3.connect(data / "sts.db")
    con.execute("CREATE TABLE decision (id INTEGER PRIMARY KEY, request_id VARCHAR NOT NULL, outcome VARCHAR NOT NULL, "
                "checklist JSON, existing_tool_id VARCHAR, limits VARCHAR, reason VARCHAR NOT NULL, "
                "what_would_change VARCHAR NOT NULL, reason_drafted_by_claude BOOLEAN NOT NULL, "
                "reason_edited BOOLEAN NOT NULL, decided_by VARCHAR NOT NULL, decided_at DATETIME NOT NULL)")
    con.execute("INSERT INTO decision VALUES (1, 'r-1', 'not_approved', '{}', NULL, NULL, 'r', 'w', 0, 0, 'J', "
                "'2026-01-01 10:00:00')")
    con.commit()
    con.close()
    store = LiveStore(data)
    d = store.decision_for("r-1")
    assert d.outcome == "not_approved" and d.revisit_on is None
