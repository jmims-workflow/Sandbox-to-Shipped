"""The web app: FastAPI with server-rendered Jinja2 pages."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote

from fastapi import FastAPI, Request as HTTPRequest
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import APP_NAME, TAGLINE
from .config import ROOT, Settings
from .demo_data import load_demo_data
from .matching import clean_matches, clean_related
from .models import (
    HOW_OFTEN,
    INFO_KINDS,
    JOURNEY_EVENTS,
    KEPT_USING,
    OUTCOME_CHOICES,
    OUTCOMES,
    READY_STATUSES,
    REQUEST_STATUSES,
    SECURITY_CHECK,
    TEAMS,
    TOOL_STATUSES,
    WHO_USES,
    Request,
    Tool,
)
from .provider import MSG_LIMITED, CallLimiter, ClaudeProvider, ClaudeUnavailable, DemoProvider, PreviewProvider
from .rules import (
    MSG_STOPPED,
    OPEN_STATUSES,
    RequestChangeError,
    add_needed_by,
    auto_security,
    needed_by_count,
    READY_TOTAL,
    REVIEW_MONTHS,
    Checklist,
    DecisionForm,
    NewTool,
    ToolChangeError,
    add_months,
    build_decision,
    build_new_tool,
    can_ship,
    copy_request_fields,
    extend_trial,
    long_date,
    mark_reviewed,
    needs_decision,
    parse_month,
    prefill_checklist,
    ready_count,
    ready_items,
    record_security_check,
    retire_tool,
    save_ready_answers,
    ship_tool,
    team_stopped,
    tool_flags,
    too_long_message,
    validate_decision,
    warnings_for,
)
from .security import (
    LEVELS,
    QUESTIONS,
    RESULTS,
    WARN_SENDS,
    WARN_SENSITIVE,
    YES_NO_NOT_SURE,
    answer_errors,
    answer_text,
    check_security,
    clean_answers,
    early_warnings,
    load_security_rules,
    needs_questions,
)
from .store import DemoStore, LiveStore

DEMO_READONLY = "Demo mode doesn't save anything. Run in live mode to send real decisions."
TOOL_READONLY = "Demo mode doesn't save changes to tools."
ASK_READONLY = "Demo mode doesn't save questions."
NEED_READONLY = "Demo mode doesn't save anything. In live mode, this adds you to that request instead of starting a new one."
# Live preview saves nothing either. Its lines say so in its own words.
READONLY_LINES = {
    "demo": {"DEMO_READONLY": DEMO_READONLY, "TOOL_READONLY": TOOL_READONLY, "ASK_READONLY": ASK_READONLY,
             "NEED_READONLY": NEED_READONLY},
    "preview": {
        "DEMO_READONLY": "The live preview doesn't save anything. Run in live mode to send real decisions.",
        "TOOL_READONLY": "The live preview doesn't save changes to tools.",
        "ASK_READONLY": "The live preview doesn't save questions.",
        "NEED_READONLY": "The live preview doesn't save anything. In live mode, this adds you to that request "
                         "instead of starting a new one.",
    },
}


# ---- Small helpers used by templates ----------------------------------------------


def fmt_date(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    if isinstance(value, datetime):
        value = value.date()
    return long_date(value)


def parse_date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value or "").strip())
    except ValueError:
        return None


def days_between(earlier: Any, now: datetime) -> int:
    d = earlier.date() if isinstance(earlier, datetime) else earlier
    return (now.date() - d).days


def join_words(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def create_app(settings: Optional[Settings] = None, provider: Any = None) -> FastAPI:
    """Build the app. Tests may pass a provider; otherwise the mode picks one."""
    settings = settings or Settings.from_env()
    # Security's rules are checked at startup. A problem stops the app with a message naming the line.
    rules = load_security_rules(settings.security_rules_path)
    demo = load_demo_data(settings.demo_dir, rules=rules)
    demo_provider = DemoProvider(demo.recorded, demo.requests)
    limiter = None
    if settings.is_live:
        store: Any = LiveStore(settings.data_dir)
        provider = provider or ClaudeProvider(settings.api_key, settings.model)
    elif settings.is_preview:
        # Real Claude for three features, nothing saved, within the daily and per-visitor limits.
        store = DemoStore(demo)
        limiter = CallLimiter(settings.daily_claude_calls, settings.visitor_claude_calls_per_hour)
        provider = PreviewProvider(provider or ClaudeProvider(settings.api_key, settings.model), demo_provider, limiter)
    else:
        store = DemoStore(demo)
        provider = demo_provider

    app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.store = store
    app.state.provider = provider
    app.state.demo = demo
    app.state.rules = rules
    app.state.limiter = limiter
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    templates = Jinja2Templates(directory=ROOT / "templates")
    env = templates.env
    env.filters["date"] = fmt_date
    env.globals.update(
        APP_NAME=APP_NAME,
        TAGLINE=TAGLINE,
        INFO_KINDS=INFO_KINDS,
        HOW_OFTEN=HOW_OFTEN,
        WHO_USES=WHO_USES,
        TEAMS=TEAMS,
        OUTCOMES=OUTCOMES,
        OUTCOME_CHOICES=OUTCOME_CHOICES,
        TOOL_STATUSES=TOOL_STATUSES,
        REQUEST_STATUSES=REQUEST_STATUSES,
        SECURITY_CHECK=SECURITY_CHECK,
        KEPT_USING=KEPT_USING,
        JOURNEY_EVENTS=JOURNEY_EVENTS,
        READY_TOTAL=READY_TOTAL,
        MSG_STOPPED=MSG_STOPPED,
        MSG_LIMITED=MSG_LIMITED,
        **READONLY_LINES["preview" if settings.is_preview else "demo"],
        RULES=rules,
        LEVELS=LEVELS,
        QUESTIONS=QUESTIONS,
        YES_NO_NOT_SURE=YES_NO_NOT_SURE,
        SECURITY_RESULTS=RESULTS,
        WARN_SENDS=WARN_SENDS,
        WARN_SENSITIVE=WARN_SENSITIVE,
        REVIEW_DAYS=settings.review_days,
        answer_text=lambda q, v: answer_text(q, v, rules),
        needed_by_count=needed_by_count,
        join_words=join_words,
        tool_flags=lambda t: tool_flags(t, store.now().date()),
    )

    # ---- Who is viewing -------------------------------------------------------

    def viewer(req: HTTPRequest) -> str:
        return "reviewer" if req.cookies.get("sts_viewer") == "reviewer" else "requester"

    def display_name(req: HTTPRequest, role: Optional[str] = None) -> str:
        if not settings.is_live:
            role = role or viewer(req)
            return demo.demo_reviewer if role == "reviewer" else demo.demo_requester
        return (req.cookies.get("sts_name") or "").strip()[:80]

    @app.middleware("http")
    async def ask_for_name(req: HTTPRequest, call_next):
        path = req.url.path
        if (
            settings.is_live
            and not req.cookies.get("sts_name")
            and not path.startswith(("/static", "/health", "/welcome", "/viewing-as"))
        ):
            return RedirectResponse("/welcome?next=" + quote(path), status_code=303)
        return await call_next(req)

    def waiting_count() -> int:
        return sum(1 for r in store.list_requests() if r.status == "waiting")

    def badge_count() -> int:
        """Waiting requests plus tools that need a decision."""
        return waiting_count() + len(needs_decision(store.list_tools(), store.now().date()))

    def visitor_address(req: HTTPRequest) -> str:
        """The visitor's address, used only to make a hashed key for the preview limit."""
        forwarded = req.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return req.client.host if req.client else ""

    def prov(req: HTTPRequest):
        """The provider for this visitor. In live preview it is bound to a hashed visitor key."""
        if hasattr(provider, "for_visitor"):
            return provider.for_visitor(limiter.visitor_key(visitor_address(req)))
        return provider

    def base_ctx(req: HTTPRequest) -> dict:
        return dict(
            settings=settings,
            mode=settings.mode,
            read_only=store.read_only,
            fell_back=settings.fell_back,
            requested_mode=settings.requested_mode,
            viewer=viewer(req),
            path=req.url.path,
        )

    def render(req: HTTPRequest, name: str, current: str, status_code: int = 200, **ctx):
        base = dict(
            settings=settings,
            mode=settings.mode,
            read_only=store.read_only,
            fell_back=settings.fell_back,
            requested_mode=settings.requested_mode,
            viewer=viewer(req),
            current=current,
            waiting_count=waiting_count(),
            badge_count=badge_count(),
            path=req.url.path,
            now=store.now(),
        )
        base.update(ctx)
        return templates.TemplateResponse(req, name, base, status_code=status_code)

    def tool_map() -> dict[str, Tool]:
        return {t.id: t for t in store.list_tools()}

    def need_reviewer(req: HTTPRequest):
        if viewer(req) != "reviewer":
            return render(
                req,
                "message.html",
                "",
                status_code=403,
                heading="This page is for reviewers",
                body="Switch Viewing as to Reviewer in the menu to see it.",
            )
        return None

    # ---- Basic routes ---------------------------------------------------------------

    @app.get("/health")
    def health():
        return PlainTextResponse("ok")

    @app.post("/viewing-as")
    async def set_viewer(req: HTTPRequest):
        form = await req.form()
        role = "reviewer" if form.get("role") == "reviewer" else "requester"
        target = "/review" if role == "reviewer" else "/"
        nxt = str(form.get("next") or "")
        keep = ("/tools", "/decided", "/how-it-works")
        if nxt.startswith(keep):
            target = nxt
        resp = RedirectResponse(target, status_code=303)
        resp.set_cookie("sts_viewer", role, max_age=60 * 60 * 24 * 365, samesite="lax", httponly=True)
        return resp

    @app.get("/welcome", response_class=HTMLResponse)
    def welcome(req: HTTPRequest, next: str = "/"):
        return render(req, "welcome.html", "", next=next, error="", name="")

    @app.post("/welcome", response_class=HTMLResponse)
    async def welcome_post(req: HTTPRequest):
        form = await req.form()
        name = str(form.get("name") or "").strip()
        nxt = str(form.get("next") or "/")
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/"
        if not name or len(name) > 80:
            return render(
                req, "welcome.html", "", status_code=400, next=nxt, name=name[:80],
                error="Please enter your name (up to 80 characters).",
            )
        resp = RedirectResponse(nxt, status_code=303)
        resp.set_cookie("sts_name", name, max_age=60 * 60 * 24 * 365, samesite="lax", httponly=True)
        return resp

    @app.get("/how-it-works", response_class=HTMLResponse)
    def how_it_works(req: HTTPRequest):
        return render(req, "how_it_works.html", "how")

    # ---- Request a tool ---------------------------------------------------------------

    def empty_form() -> dict:
        return dict(task="", team="", how_often="", who_uses="", info=[], extra="", whats_missing="", copied_from="",
                    answers={}, need_note="")

    def example_form() -> dict:
        ex = next((r for r in demo.requests if r.id == demo.example_request_id), None)
        if not ex:
            return empty_form()
        f = empty_form()
        f.update(task=ex.task, team=ex.team, how_often=ex.how_often, who_uses=ex.who_uses, info=list(ex.info),
                 answers=dict(ex.security_answers or {}))
        return f

    def open_requests(name: str) -> list[dict]:
        """Requests still waiting or in review, for "I need this too". Never includes who asked.

        The person's own requests, and requests they are already on, are left out.
        """
        out = []
        for r in sorted(store.list_requests(), key=lambda r: r.submitted_at, reverse=True):
            if r.status not in OPEN_STATUSES or r.requester_name == name:
                continue
            if any(p.get("name") == name for p in r.needed_by or []):
                continue
            out.append({"id": r.id, "title": r.title, "task": r.task})
        return out[:40]

    def past_decisions() -> list[dict]:
        """Decided requests for Asked before. Never includes who asked."""
        requests = {r.id: r for r in store.list_requests()}
        out = []
        for d in sorted(store.list_decisions(), key=lambda d: d.decided_at, reverse=True):
            r = requests.get(d.request_id)
            if r is None or r.status != "decided":
                continue
            out.append({"id": r.id, "title": r.title, "task": r.task, "outcome": d.outcome,
                        "reason": d.reason, "what_would_change": d.what_would_change})
        return out[:40]

    def check_matches(task: str, info: list[str], req: HTTPRequest, p: Any = None) -> dict:
        """Run the existing-tool check. Returns matches with their tools, the source, any related
        decision (Asked before) and any related request still in review (I need this too)."""
        p = p or prov(req)
        inventory = store.list_tools()
        past = past_decisions()
        others = open_requests(display_name(req, "requester"))
        error = ""
        related = related_req = None
        try:
            outcome = p.find_matches(task, info, inventory, past, others)
            matches, source = clean_matches(outcome.matches, inventory), outcome.source
            related = clean_related(outcome.related, past)
            related_req = clean_related(outcome.related_request, others)
        except ClaudeUnavailable:
            matches, source = [], "claude"
            error = "Claude couldn't check the inventory just now. You can still submit, and a reviewer will check."
        tools = {t.id: t for t in inventory}
        in_review = None
        if related_req and (other := store.get_request(related_req["request_id"])):
            # Only the title and status. Never who asked or who else is on it.
            in_review = {"id": other.id, "title": other.title, "status": other.status, "why": related_req["reason"]}
        asked_before = None
        if related:
            d = next(p for p in past if p["id"] == related["request_id"])
            # Only what Decided before shows. Never who asked.
            asked_before = {"id": d["id"], "title": d["title"], "outcome": d["outcome"], "reason": d["reason"],
                            "what_would_change": d["what_would_change"], "why": related["reason"]}
        return {
            "items": [{**m, "tool": tools[m["tool_id"]]} for m in matches],
            "raw": matches,
            "source": source,
            "error": error,
            "checked": bool(task.strip()),
            "asked_before": asked_before,
            "in_review": in_review,
            "limited": bool(getattr(p, "limited", False)),
        }

    def read_request_form(form) -> dict:
        f = empty_form()
        for key in ("task", "team", "how_often", "who_uses", "extra", "whats_missing", "copied_from"):
            f[key] = str(form.get(key) or "").strip()
        f["info"] = [i for i in form.getlist("info") if i in INFO_KINDS]
        f["answers"] = clean_answers(form, f["info"], rules)
        f["need_note"] = str(form.get("need_note") or "").strip()
        return f

    def validate_request_form(f: dict) -> dict[str, str]:
        errors = {}
        if not f["task"]:
            errors["task"] = "Tell us what you're trying to do."
        if f["team"] not in TEAMS:
            errors["team"] = "Choose your team."
        if f["how_often"] not in HOW_OFTEN:
            errors["how_often"] = "Choose how often you'd do this."
        if f["who_uses"] not in WHO_USES:
            errors["who_uses"] = "Choose who would use it."
        if not f["info"]:
            errors["info"] = "Check at least one kind of information. Not sure? Check it anyway."
        errors.update(answer_errors(f["info"], f["answers"], rules))
        for key, label in (
            ("task", "What you're trying to do"),
            ("extra", "Anything else"),
            ("whats_missing", "What's missing"),
        ):
            msg = too_long_message(label, f[key])
            if msg:
                errors[key] = msg
        return errors

    def form_page(req: HTTPRequest, f: dict, errors: dict, panel: Optional[dict], notice: str = "",
                  status_code: int = 200, need_error: str = ""):
        return render(
            req, "request_form.html", "request", status_code=status_code, f=f, errors=errors, panel=panel,
            notice=notice, warnings=early_warnings(f["info"], f["answers"]),
            show_questions=needs_questions(f["info"], rules), need_error=need_error,
        )

    @app.get("/", response_class=HTMLResponse)
    def request_form(req: HTTPRequest):
        source = req.query_params.get("from", "")
        notice = ""
        if source and (orig := store.get_request(source)):
            f = empty_form()
            f.update(copy_request_fields(orig))
            notice = f"Your answers from “{orig.title}” are copied over. Change what's different."
        elif not settings.is_live:
            f = example_form()
        else:
            f = empty_form()
        # Opening the page uses the recorded results in live preview, so page views don't use up Claude calls.
        panel = check_matches(f["task"], f["info"], req, demo_provider if settings.is_preview else None) \
            if f["task"] else None
        return form_page(req, f, {}, panel, notice)

    @app.post("/", response_class=HTMLResponse)
    async def request_submit(req: HTTPRequest):
        form = await req.form()
        f = read_request_form(form)
        action = form.get("action", "submit")
        if action == "check":
            errors = {}
            msg = too_long_message("What you're trying to do", f["task"])
            if msg:
                errors["task"] = msg
            panel = check_matches(f["task"], f["info"], req) if f["task"] and not errors else None
            return form_page(req, f, errors, panel)

        errors = validate_request_form(f)
        if errors:
            panel = check_matches(f["task"], f["info"], req) if f["task"] and "task" not in errors else None
            return form_page(req, f, errors, panel, status_code=400)

        inventory = store.list_tools()
        seen = True
        try:
            shown = json.loads(str(form.get("matches_json") or "null"))
        except json.JSONDecodeError:
            shown = None
        p = prov(req)
        if shown is None:
            seen = False
            shown = check_matches(f["task"], f["info"], req, p)["raw"]
        matches = clean_matches(shown, inventory)

        now = store.now()
        request = Request(
            id=store.new_request_id(),
            title="",
            task=f["task"],
            team=f["team"],
            how_often=f["how_often"],
            who_uses=f["who_uses"],
            info=f["info"],
            extra=f["extra"] or None,
            whats_missing=(f["whats_missing"] or None) if matches else None,
            requester_name=display_name(req, "requester"),
            submitted_at=now,
            status="waiting",
            matches=matches,
            matches_seen=seen,
            copied_from=f["copied_from"] or None,
            timeline=[{"label": "Submitted", "date": now.date().isoformat()}],
            security_answers=f["answers"],
            # The automatic security check: security's rules applied in code. Claude is not involved.
            security_result=check_security(f["info"], f["answers"], rules).as_dict(),
            needed_by=[],
        )
        recent = [
            {"outcome": d.outcome, "reason": d.reason, "what_would_change": d.what_would_change}
            for d in sorted(store.list_decisions(), key=lambda d: d.decided_at, reverse=True)
        ]
        size_up_error = ""
        try:
            request.size_up = p.size_up(request, inventory, recent)
            request.title = request.size_up.get("title") or ""
        except ClaudeUnavailable:
            size_up_error = "Claude couldn't size up this request just now. A reviewer will read it as is."
        if not request.title:
            words = request.task.split()
            request.title = " ".join(words[:6]) + ("..." if len(words) > 6 else "")

        if store.read_only:
            if getattr(p, "used_claude", False) and not getattr(p, "limited", False):
                source = "claude"
            else:
                source = "recorded" if p.recorded_for_task(request.task) else "rules"
            return render(
                req,
                "what_next.html",
                "request",
                r=request,
                tools=tool_map(),
                saw_line=saw_line(request, tool_map()),
                size_up_source=source,
                limited=bool(getattr(p, "limited", False)),
                claude_read_label="Only reviewers see this",
            )
        store.save(request)
        target = f"/requests/{request.id}?submitted=1"
        if size_up_error:
            target += "&note=sizeup"
        return RedirectResponse(target, status_code=303)

    @app.post("/api/matches", response_class=HTMLResponse)
    async def api_matches(req: HTTPRequest):
        form = await req.form()
        task = str(form.get("task") or "").strip()
        info = [i for i in form.getlist("info") if i in INFO_KINDS]
        whats_missing = str(form.get("whats_missing") or "")
        if too_long_message("x", task):
            return HTMLResponse("", status_code=400)
        panel = check_matches(task, info, req) if task else None
        ctx = base_ctx(req)
        ctx.update(panel=panel, f={"whats_missing": whats_missing, "need_note": str(form.get("need_note") or "")},
                   errors={}, need_error="")
        return templates.TemplateResponse(req, "partials/match_panel.html", ctx)

    @app.post("/requests/{request_id}/need-too", response_class=HTMLResponse)
    async def need_too(req: HTTPRequest, request_id: str):
        """I need this too: add this person to a request still in review instead of starting a new one."""
        form = await req.form()
        f = read_request_form(form)
        r = store.get_request(request_id)
        error = ""
        if store.read_only:
            error = READONLY_LINES["preview" if settings.is_preview else "demo"]["NEED_READONLY"]
        elif r is None:
            error = "We couldn't find that request. You can still submit yours."
        else:
            try:
                add_needed_by(r, display_name(req, "requester"), f["need_note"], store.now().date())
            except RequestChangeError as exc:
                error = str(exc)
        if error:
            panel = check_matches(f["task"], f["info"], req, demo_provider if settings.is_preview else None) \
                if f["task"] else None
            return form_page(req, f, {}, panel, status_code=400, need_error=error)
        store.save(r)
        return RedirectResponse(f"/requests?needed={r.id}", status_code=303)

    # ---- My requests ------------------------------------------------------------------

    def my_requests(req: HTTPRequest) -> list[Request]:
        name = display_name(req, "requester")
        mine = [r for r in store.list_requests() if r.requester_name == name]
        return sorted(mine, key=lambda r: r.submitted_at, reverse=True)

    def needed_too(req: HTTPRequest) -> list[Request]:
        """Requests this person was added to with "I need this too"."""
        name = display_name(req, "requester")
        found = [r for r in store.list_requests() if any(p.get("name") == name for p in r.needed_by or [])]
        return sorted(found, key=lambda r: r.submitted_at, reverse=True)

    @app.get("/requests", response_class=HTMLResponse)
    def requests_list(req: HTTPRequest):
        decisions = {d.request_id: d for d in store.list_decisions()}
        items = [{"r": r, "d": decisions.get(r.id)} for r in my_requests(req)]
        also = [{"r": r, "d": decisions.get(r.id)} for r in needed_too(req)]
        added = store.get_request(req.query_params.get("needed", "")) if req.query_params.get("needed") else None
        return render(req, "my_requests.html", "mine", items=items, also=also, added=added)

    def request_page_context(r: Request, req: HTTPRequest) -> dict:
        name = display_name(req, "requester")
        mine = r.requester_name == name
        my_note = next((p.get("note") for p in r.needed_by or [] if p.get("name") == name), None)
        also = not mine and any(p.get("name") == name for p in r.needed_by or [])
        d = store.decision_for(r.id)
        tools = tool_map()
        open_tool = None
        if d:
            if d.outcome == "use_existing":
                open_tool = tools.get(d.existing_tool_id or "")
            elif d.outcome in ("approve", "approve_with_limits"):
                open_tool = next((t for t in tools.values() if t.from_request == r.id), None)
        return {"r": r, "d": d, "open_tool": open_tool, "tools": tools, "needed_too": also, "my_note": my_note}

    @app.get("/requests/{request_id}", response_class=HTMLResponse)
    def request_page(req: HTTPRequest, request_id: str):
        r = store.get_request(request_id)
        if not r:
            return render(req, "message.html", "mine", status_code=404, heading="We couldn't find that request",
                          body="It may have been removed. Your other requests are on My requests.")
        ctx = request_page_context(r, req)
        return render(
            req, "request_page.html", "mine", **ctx,
            submitted=req.query_params.get("submitted") == "1",
            sizeup_note=req.query_params.get("note") == "sizeup",
            asked=req.query_params.get("asked") == "1",
            ask_error="", ask_text="",
        )

    @app.post("/requests/{request_id}/ask", response_class=HTMLResponse)
    async def request_ask(req: HTTPRequest, request_id: str):
        r = store.get_request(request_id)
        if not r:
            return RedirectResponse("/requests", status_code=303)
        form = await req.form()
        text = str(form.get("question") or "").strip()
        error = ""
        if store.read_only:
            error = ASK_READONLY
        elif not text:
            error = "Write your question first."
        else:
            error = too_long_message("Your question", text) or ""
        if error:
            return render(
                req, "request_page.html", "mine", status_code=400, **request_page_context(r, req),
                submitted=False, sizeup_note=False, asked=False, ask_error=error, ask_text=text[:5000],
            )
        now = store.now()
        r.questions = r.questions + [{"text": text, "date": now.date().isoformat(), "handled": False}]
        r.timeline = r.timeline + [{"label": "Asked about the decision", "date": now.date().isoformat()}]
        store.save(r)
        return RedirectResponse(f"/requests/{r.id}?asked=1#ask", status_code=303)

    # ---- Tool inventory -----------------------------------------------------------------

    STATUS_FILTERS = {
        "": "Ready or in pilot",
        "ready": "Ready to use",
        "being_tried": "In pilot",
        "all": "All, including retired",
    }

    @app.get("/tools", response_class=HTMLResponse)
    def tools_page(req: HTTPRequest, q: str = "", team: str = "", status: str = "", info: str = ""):
        all_tools = sorted(store.list_tools(), key=lambda t: t.name)
        teams = sorted({team_name for t in all_tools for team_name in t.teams})
        shown = []
        for t in all_tools:
            if status == "ready" and t.status not in READY_STATUSES:
                continue
            if status == "being_tried" and t.status != "being_tried":
                continue
            if status not in ("all", "ready", "being_tried") and t.status == "retired":
                continue
            if team and team not in t.teams:
                continue
            if info and info not in t.allowed_info:
                continue
            if q and q.lower() not in f"{t.name} {t.purpose} {t.owner_name}".lower():
                continue
            shown.append(t)
        counts = {
            "ready": sum(t.status in READY_STATUSES for t in shown),
            "being_tried": sum(t.status == "being_tried" for t in shown),
            "retired": sum(t.status == "retired" for t in shown),
        }
        return render(
            req, "tools.html", "tools", tools=shown, all_tools={t.id: t for t in all_tools}, total=len(all_tools), counts=counts, teams=teams,
            filters={"q": q, "team": team, "status": status, "info": info}, status_filters=STATUS_FILTERS,
        )

    def tool_page_context(t: Tool) -> dict:
        origin = store.get_request(t.from_request) if t.from_request else None
        decision = store.decision_for(t.from_request) if t.from_request else None
        tools = tool_map()
        today = store.now().date()
        latest_extension = (t.trial_ends + timedelta(days=60)) if t.trial_ends else None
        return {
            "t": t,
            "origin": origin,
            "origin_decision": decision,
            "tools": tools,
            "replacements": [x for x in tools.values() if x.id != t.id and x.status != "retired"],
            "flags": tool_flags(t, today),
            "ready": ready_items(t),
            "ready_n": ready_count(t),
            "can_ship": can_ship(t),
            "stopped": team_stopped(t),
            "rc": t.ready_check or {},
            "journey": sorted(t.journey or [], key=lambda e: e.get("date") or ""),
            "today": today,
            "latest_extension": latest_extension,
            "next_review_default": add_months(today, REVIEW_MONTHS).strftime("%Y-%m"),
            "errors": {},
            "posted": {},
        }

    @app.get("/tools/{tool_id}", response_class=HTMLResponse)
    def tool_page(req: HTTPRequest, tool_id: str):
        t = store.get_tool(tool_id)
        if not t:
            return render(req, "message.html", "tools", status_code=404, heading="We couldn't find that tool",
                          body="It may have a new name. Everything we have is in the Tool inventory.")
        return render(req, "tool_page.html", "tools", **tool_page_context(t), error="",
                      changed=req.query_params.get("changed", ""))

    async def tool_change(req: HTTPRequest, tool_id: str, change):
        if (blocked := need_reviewer(req)) is not None:
            return blocked
        t = store.get_tool(tool_id)
        if not t:
            return RedirectResponse("/tools", status_code=303)
        form = await req.form()
        if store.read_only:
            return render(req, "tool_page.html", "tools", status_code=400, **tool_page_context(t),
                          error=TOOL_READONLY, changed="")
        before = t.model_copy(deep=True)
        try:
            label = change(t, form)
        except ToolChangeError as exc:
            ctx = tool_page_context(before)
            ctx.update(errors=exc.errors, posted={k: str(v) for k, v in form.items()})
            return render(req, "tool_page.html", "tools", status_code=400, **ctx, error=str(exc), changed="")
        store.save(t)
        return RedirectResponse(f"/tools/{t.id}?changed={label}", status_code=303)

    def today() -> date:
        return store.now().date()

    @app.post("/tools/{tool_id}/check", response_class=HTMLResponse)
    async def tool_check(req: HTTPRequest, tool_id: str):
        def change(t, form):
            save_ready_answers(t, str(form.get("kept_using") or ""), str(form.get("went_wrong") or ""),
                               str(form.get("how_tested") or ""), str(form.get("test_link") or ""))
            return "checked"
        return await tool_change(req, tool_id, change)

    @app.post("/tools/{tool_id}/security", response_class=HTMLResponse)
    async def tool_security(req: HTTPRequest, tool_id: str):
        def change(t, form):
            record_security_check(t, form.get("security_done") == "yes", parse_date(form.get("security_date")),
                                  str(form.get("security_note") or ""), today())
            return "security"
        return await tool_change(req, tool_id, change)

    @app.post("/tools/{tool_id}/ship", response_class=HTMLResponse)
    async def tool_ship(req: HTTPRequest, tool_id: str):
        def change(t, form):
            ship_tool(t, str(form.get("to_status") or ""), str(form.get("limits") or ""), today())
            return "shipped"
        return await tool_change(req, tool_id, change)

    @app.post("/tools/{tool_id}/extend", response_class=HTMLResponse)
    async def tool_extend(req: HTTPRequest, tool_id: str):
        def change(t, form):
            extend_trial(t, parse_date(form.get("new_end")), today())
            return "extended"
        return await tool_change(req, tool_id, change)

    @app.post("/tools/{tool_id}/retire", response_class=HTMLResponse)
    async def tool_retire(req: HTTPRequest, tool_id: str):
        def change(t, form):
            retire_tool(t, str(form.get("retire_reason") or ""), str(form.get("replaced_by") or ""),
                        store.list_tools(), today())
            return "retired"
        return await tool_change(req, tool_id, change)

    @app.post("/tools/{tool_id}/reviewed", response_class=HTMLResponse)
    async def tool_reviewed(req: HTTPRequest, tool_id: str):
        def change(t, form):
            raw = str(form.get("next_review_month") or "").strip()
            month = parse_month(raw)
            if raw and month is None:
                raise ToolChangeError("Pick the month of the next review.", field="next_review_month")
            mark_reviewed(t, str(form.get("still_in_use") or ""), str(form.get("review_change") or ""),
                          month, today())
            return "reviewed"
        return await tool_change(req, tool_id, change)

    @app.get("/tools/{tool_id}/edit", response_class=HTMLResponse)
    def tool_edit(req: HTTPRequest, tool_id: str):
        if (blocked := need_reviewer(req)) is not None:
            return blocked
        t = store.get_tool(tool_id)
        if not t:
            return RedirectResponse("/tools", status_code=303)
        return render(req, "tool_edit.html", "tools", t=t, errors={}, owner_changed=False)

    @app.post("/tools/{tool_id}/edit", response_class=HTMLResponse)
    async def tool_edit_post(req: HTTPRequest, tool_id: str):
        if (blocked := need_reviewer(req)) is not None:
            return blocked
        t = store.get_tool(tool_id)
        if not t:
            return RedirectResponse("/tools", status_code=303)
        form = await req.form()
        old_owner = (t.owner_name, t.owner_team)
        errors: dict[str, str] = {}
        if store.read_only:
            errors["form"] = TOOL_READONLY
        for key in ("name", "purpose", "owner_name", "owner_team"):
            value = str(form.get(key) or "").strip()
            if not value:
                errors[key] = "This can't be empty."
            elif msg := too_long_message("This field", value):
                errors[key] = msg
            setattr(t, key, value)
        t.teams = [x.strip() for x in str(form.get("teams") or "").split(",") if x.strip()]
        t.allowed_info = [i for i in form.getlist("allowed_info") if i in INFO_KINDS]
        if not t.allowed_info:
            errors["allowed_info"] = "Choose what information the tool is okay to use."
        t.next_review = str(form.get("next_review") or "").strip() or None
        if t.next_review:
            month = parse_month(t.next_review)
            if month is None:
                errors["next_review"] = "Write the month and year, for example March 2027."
            else:
                t.next_review = f"{month:%B} {month.year}"
        t.link = str(form.get("link") or "").strip() or None
        if t.link and not t.link.startswith(("https://", "http://")):
            errors["link"] = "Links start with https://"
        if t.status == "approved_with_limits":
            t.limits = str(form.get("limits") or "").strip()
            if not t.limits:
                errors["limits"] = "Tools approved with limits need the limits written down."
        owner_changed = (t.owner_name, t.owner_team) != old_owner
        if owner_changed and form.get("owner_agreed") != "yes":
            errors["owner_agreed"] = "Check that the new owner has agreed to own this tool."
        if errors:
            return render(req, "tool_edit.html", "tools", status_code=400, t=t, errors=errors,
                          owner_changed=owner_changed)
        store.save(t)
        return RedirectResponse(f"/tools/{t.id}?changed=edited", status_code=303)

    # ---- Decided before -------------------------------------------------------------------

    @app.get("/decided", response_class=HTMLResponse)
    def decided(req: HTTPRequest, q: str = "", outcome: str = ""):
        requests = {r.id: r for r in store.list_requests()}
        items = []
        for d in sorted(store.list_decisions(), key=lambda d: d.decided_at, reverse=True):
            r = requests.get(d.request_id)
            if not r:
                continue
            if outcome and d.outcome != outcome:
                continue
            text = f"{r.title} {r.task} {d.reason} {d.what_would_change}".lower()
            if q and q.lower() not in text:
                continue
            # Only what is safe to show everyone. Never the requester's name.
            items.append(
                {"id": r.id, "title": r.title, "outcome": d.outcome, "reason": d.reason,
                 "what_would_change": d.what_would_change, "decided_at": d.decided_at}
            )
        return render(req, "decided.html", "decided", items=items, q=q, outcome=outcome)

    # ---- Review queue ----------------------------------------------------------------------

    def queue() -> list[Request]:
        items = [
            r for r in store.list_requests()
            if r.status in ("waiting", "in_review") or any(not q.get("handled") for q in r.questions)
        ]
        open_items = sorted([r for r in items if r.status != "decided"], key=lambda r: r.submitted_at, reverse=True)
        asked = sorted([r for r in items if r.status == "decided"], key=lambda r: r.submitted_at, reverse=True)
        return open_items + asked

    def queue_line(r: Request, now: datetime) -> str:
        n = days_between(r.submitted_at, now)
        when = "Submitted today" if n <= 0 else ("Yesterday" if n == 1 else f"{n} days ago")
        security_done = any(e["label"].startswith("Security check") for e in r.timeline)
        auto = auto_security(r)
        if any(not q.get("handled") for q in r.questions):
            note = "Has a question about the decision."
        elif r.status != "decided" and auto == "person" and not security_done:
            note = "A person from security will review this."
        elif r.status != "decided" and not auto and r.size_up and r.size_up.get("security_check_needed") \
                and not security_done:
            note = "Needs a security check."
        elif r.status != "decided" and auto == "passed" and not r.matches:
            note = "Security check passed automatically."
        elif any(m["confidence"] == "close" for m in r.matches):
            note = "Close match found."
        elif r.matches:
            note = "Possible match found."
        else:
            note = "No match found."
        if r.status == "in_review" and note != "Has a question about the decision.":
            note = "In review. " + note
        return f"{r.team}. {when}. {note}"

    def default_form(r: Request, now: datetime) -> DecisionForm:
        if r.draft:
            return form_from_dict(r.draft)
        return DecisionForm(
            checklist=prefill_checklist(r),
            existing_tool_id=r.matches[0]["tool_id"] if r.matches else "",
            new_tool=NewTool(
                name=r.title,
                allowed_info=list(r.info),
                trial_ends=(now + timedelta(days=60)).date(),
            ),
        )

    def form_from_dict(data: dict) -> DecisionForm:
        def get(k):
            return str(data.get(k) or "").strip() if not isinstance(data.get(k), list) else ""

        trial = None
        try:
            if data.get("tool_trial_ends"):
                trial = date.fromisoformat(str(data.get("tool_trial_ends")))
        except ValueError:
            trial = None
        allowed = data.get("tool_allowed_info") or []
        if isinstance(allowed, str):
            allowed = [allowed]
        return DecisionForm(
            outcome=get("outcome"),
            checklist=Checklist(
                already_exists=get("already_exists"),
                sends_without_check=get("sends_without_check"),
                uses_customer_details=get("uses_customer_details"),
                security_check=get("security_check") or "not_needed",
            ),
            existing_tool_id=get("existing_tool_id"),
            limits=get("limits"),
            reason=get("reason"),
            what_would_change=get("what_would_change"),
            drafted_reason=get("drafted_reason"),
            new_tool=NewTool(
                name=get("tool_name"),
                purpose=get("tool_purpose"),
                owner_name=get("tool_owner_name"),
                owner_team=get("tool_owner_team"),
                owner_agreed=get("owner_agreed") == "yes",
                allowed_info=[i for i in allowed if i in INFO_KINDS],
                trial_ends=trial,
            ),
        )

    def form_to_dict(form) -> dict:
        keys = (
            "outcome", "already_exists", "sends_without_check", "uses_customer_details", "security_check",
            "existing_tool_id", "limits", "reason", "what_would_change", "drafted_reason", "tool_name",
            "tool_purpose", "tool_owner_name", "tool_owner_team", "owner_agreed", "tool_trial_ends",
        )
        data = {k: str(form.get(k) or "") for k in keys}
        data["tool_allowed_info"] = list(form.getlist("tool_allowed_info"))
        return data

    def review_render(req, r: Optional[Request], form: Optional[DecisionForm] = None, status_code=200, **extra):
        now = store.now()
        items = queue()
        tools = tool_map()
        ctx: dict[str, Any] = dict(
            queue=[{"r": x, "line": queue_line(x, now), "needed_by": needed_by_count(x)} for x in items],
            sel=r,
            tools=tools,
            usable_tools=sorted([t for t in tools.values() if t.status != "retired"], key=lambda t: t.name),
            errors={},
            draft_note="",
            draft_error="",
            flash="",
            needs=needs_decision(list(tools.values()), now.date()),
        )
        if r is not None:
            form = form or default_form(r, now)
            ctx.update(
                form=form,
                warnings=warnings_for(form),
                decision=store.decision_for(r.id) if r.status == "decided" else None,
                saw_line=saw_line(r, tools),
                open_questions=[q for q in r.questions if not q.get("handled")],
                auto_result=auto_security(r),
                show_needed_by=True,
            )
        ctx.update(extra)
        return render(req, "review.html", "review", status_code=status_code, **ctx)

    def saw_line(r: Request, tools: dict[str, Tool]) -> str:
        names = [tools[m["tool_id"]].name for m in r.matches if m["tool_id"] in tools]
        if not names:
            return "No existing tools matched before submitting."
        noun = "the match" if len(names) == 1 else "the matches"
        lead = f"Shown {noun} {join_words(names)} before submitting." if r.matches_seen else (
            f"Matched {join_words(names)} when submitting."
        )
        if r.whats_missing:
            return lead + f" Said what's missing: “{r.whats_missing}”"
        return lead + " Left ‘what's missing’ blank."

    @app.get("/review", response_class=HTMLResponse)
    def review(req: HTTPRequest):
        if (blocked := need_reviewer(req)) is not None:
            return blocked
        items = queue()
        flash = ""
        if req.query_params.get("sent"):
            flash = "Decision sent. The requester can see it on My requests."
        elif req.query_params.get("saved"):
            flash = "Saved for later."
        elif req.query_params.get("handled"):
            flash = "Marked as handled."
        return review_render(req, items[0] if items else None, flash=flash)

    @app.get("/review/{request_id}", response_class=HTMLResponse)
    def review_one(req: HTTPRequest, request_id: str):
        if (blocked := need_reviewer(req)) is not None:
            return blocked
        r = store.get_request(request_id)
        if not r:
            return RedirectResponse("/review", status_code=303)
        return review_render(req, r)

    def make_draft(r: Request, form: DecisionForm, req: HTTPRequest) -> tuple[Optional[dict], str, bool]:
        """Returns (draft, error, limited). limited is True when the live preview limit was reached."""
        if form.outcome not in OUTCOMES:
            return None, "Choose an outcome first, then Claude can draft the reason.", False
        tools = tool_map()
        chosen = tools.get(form.existing_tool_id) if form.outcome == "use_existing" else None
        p = prov(req)
        try:
            draft = p.draft_reason(r, form.outcome, form.checklist.as_dict(), chosen, form.limits)
        except ClaudeUnavailable:
            return None, "Claude couldn't draft a reason just now. You can write it yourself.", False
        limited = bool(getattr(p, "limited", False))
        if not draft:
            return None, "The demo has no recorded draft for this outcome. Live mode asks Claude.", limited
        return draft, "", limited

    @app.post("/review/{request_id}", response_class=HTMLResponse)
    async def review_post(req: HTTPRequest, request_id: str):
        if (blocked := need_reviewer(req)) is not None:
            return blocked
        r = store.get_request(request_id)
        if not r:
            return RedirectResponse("/review", status_code=303)
        raw = await req.form()
        action = str(raw.get("action") or "")
        data = form_to_dict(raw)
        form = form_from_dict(data)

        if action == "draft":
            draft, err, limited = make_draft(r, form, req)
            if draft:
                form.reason = draft["reason"]
                form.what_would_change = draft["what_would_change"]
                form.drafted_reason = draft["reason"]
            return review_render(req, r, form, draft_error=err, draft_limited=limited,
                                 draft_note="Drafted by Claude from your checklist. Edit it before sending." if draft else "")

        if action == "handled":
            if store.read_only:
                return review_render(req, r, form, status_code=400, flash=DEMO_READONLY)
            r.questions = [{**q, "handled": True} for q in r.questions]
            store.save(r)
            return RedirectResponse("/review?handled=1", status_code=303)

        if store.read_only:
            return review_render(req, r, form, status_code=400, flash=DEMO_READONLY)

        now = store.now()
        today = now.date().isoformat()
        if action == "save":
            r.draft = data
            if r.status == "waiting":
                r.status = "in_review"
            if not any(e["label"] == "Reviewer picked it up" for e in r.timeline):
                r.timeline = r.timeline + [{"label": "Reviewer picked it up", "date": today}]
            store.save(r)
            return RedirectResponse("/review?saved=1", status_code=303)

        if r.status == "decided":
            return review_render(req, r, form, status_code=400, flash="This request already has a decision.")
        inventory = store.list_tools()
        errors = validate_decision(form, inventory, auto_security(r))
        if errors:
            return review_render(req, r, form, status_code=400, errors=errors)

        reviewer = display_name(req, "reviewer")
        decision = build_decision(form, r, reviewer, now)
        to_save: list[Any] = [decision]
        if form.outcome in ("approve", "approve_with_limits"):
            to_save.append(build_new_tool(form, r, {t.id for t in inventory}, now.date()))
        timeline = list(r.timeline)
        if not any(e["label"] == "Reviewer picked it up" for e in timeline):
            timeline.append({"label": "Reviewer picked it up", "date": today})
        if form.checklist.security_check == "done" and not any(
            e["label"].startswith("Security check") for e in timeline
        ):
            timeline.append({"label": "Security check done", "date": today})
        timeline.append({"label": "Decided", "date": today})
        r.timeline = timeline
        r.status = "decided"
        r.draft = None
        to_save.append(r)
        store.save(*to_save)
        return RedirectResponse(f"/review?sent={r.id}", status_code=303)

    @app.post("/api/review/{request_id}/draft")
    async def api_draft(req: HTTPRequest, request_id: str):
        if viewer(req) != "reviewer":
            return JSONResponse({"error": "This is for reviewers."}, status_code=403)
        r = store.get_request(request_id)
        if not r:
            return JSONResponse({"error": "We couldn't find that request."}, status_code=404)
        form = form_from_dict(form_to_dict(await req.form()))
        draft, err, limited = make_draft(r, form, req)
        if not draft:
            return JSONResponse({"error": (MSG_LIMITED + " " + err) if limited else err}, status_code=200)
        note = "Drafted by Claude from your checklist. Edit it before sending."
        if limited:
            note = MSG_LIMITED + " " + note
        return JSONResponse({"reason": draft["reason"], "what_would_change": draft["what_would_change"], "note": note})

    return app


app = create_app()
