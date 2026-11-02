"""The reviewer checklist and the decision rules.

A person always chooses the outcome. Nothing in this module reads an outcome
from Claude's output: the outcome only ever comes from the reviewer's form.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlparse

from .models import (
    SCREENING_LABELS,
    CUSTOMER_INFO,
    INFO_KINDS,
    JOURNEY_EVENTS,
    KEPT_USING,
    MAX_LINE,
    MAX_TEXT,
    OUTCOMES,
    READY_STATUSES,
    SECURITY_CHECK,
    SECURITY_COVERED,
    TOOL_STATUSES,
    Decision,
    Request,
    Tool,
)

YES_NO = ("yes", "no")
APPROVALS = ("approve", "approve_with_limits")

MSG_SECURITY = "Finish the security screening before approving."
MSG_SENDS_WARNING = "Northstar doesn't approve tools that send to customers on their own."
MSG_STOPPED = "A tool the team stopped using isn't ready to ship. Extend the pilot or retire it."
MSG_PASSED_ONLY = (
    "Passed automatically is only for requests that passed security's rules. Choose Needed, Done or Not needed."
)
MAX_EXTENSION_DAYS = 60
READY_TOTAL = 4
# Not now: the date to look again defaults to 3 months out and can be no more than 6.
REVISIT_DEFAULT_MONTHS = 3
REVISIT_MAX_MONTHS = 6


def msg_slots_full(total: int) -> str:
    return f"All {total} pilot slots are in use. Ship or retire a pilot first, or choose Not now."


def long_date(value: date) -> str:
    """March 5, 2027"""
    return f"{value:%B} {value.day}, {value.year}"


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def format_month(d: date) -> str:
    """March 2027"""
    return f"{d:%B} {d.year}"


MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}


def parse_month(text: Optional[str]) -> Optional[date]:
    """Read "March 2027" or "2027-03" as the first day of that month. None if it can't."""
    text = (text or "").strip()
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", text):
        year, month = int(m.group(1)), int(m.group(2))
    elif m := re.fullmatch(r"([A-Za-z]+)\s+(\d{4})", text):
        month, year = MONTHS.get(m.group(1).lower(), 0), int(m.group(2))
    else:
        return None
    if not 1 <= month <= 12:
        return None
    return date(year, month, 1)


def too_long_message(label: str, text: str) -> Optional[str]:
    if text and len(text) > MAX_TEXT:
        return (
            f"{label} is {len(text):,} characters. Please keep it under {MAX_TEXT:,} "
            "characters so a reviewer can read it quickly."
        )
    return None


@dataclass
class Checklist:
    already_exists: str = ""  # yes / no
    sends_without_check: str = ""  # yes / no
    uses_customer_details: str = ""  # yes / no
    security_check: str = "not_needed"  # not_needed / passed / needed / done

    def as_dict(self) -> dict:
        return {
            "already_exists": self.already_exists,
            "sends_without_check": self.sends_without_check,
            "uses_customer_details": self.uses_customer_details,
            "security_check": self.security_check,
        }


def auto_security(request: Request) -> str:
    """The automatic security check saved with the request: not_needed, passed, person, or "" if none."""
    return str((request.security_result or {}).get("result") or "")


def prefill_checklist(request: Request) -> Checklist:
    """Start the checklist from what the request says. The reviewer can change anything.

    The security item comes from the automatic check against security's rules: Not needed,
    Passed automatically, or Needed. Requests saved before that check fall back to the old read.
    """
    uses_customer = bool(set(request.info) & CUSTOMER_INFO)
    security = "not_needed"
    auto = auto_security(request)
    if auto:
        security = {"not_needed": "not_needed", "passed": "passed"}.get(auto, "needed")
    elif request.size_up and request.size_up.get("security_check_needed"):
        security = "needed"
    if any(e.get("label", "").startswith(SCREENING_LABELS) for e in request.timeline):
        security = "done"
    return Checklist(
        already_exists="yes" if any(m["confidence"] == "close" for m in request.matches) else "",
        uses_customer_details="yes" if uses_customer else "no",
        security_check=security,
    )


@dataclass
class NewTool:
    name: str = ""
    purpose: str = ""
    owner_name: str = ""
    owner_team: str = ""
    owner_agreed: bool = False
    allowed_info: list[str] = field(default_factory=list)
    trial_ends: Optional[date] = None


@dataclass
class DecisionForm:
    outcome: str = ""
    checklist: Checklist = field(default_factory=Checklist)
    existing_tool_id: str = ""
    limits: str = ""
    reason: str = ""
    what_would_change: str = ""
    drafted_reason: str = ""  # The reason text as Claude drafted it, if it did.
    new_tool: NewTool = field(default_factory=NewTool)
    revisit_on: Optional[date] = None  # Not now only.


def warnings_for(form: DecisionForm) -> list[str]:
    """Plain warnings shown above the decision. They never block it."""
    if form.checklist.sends_without_check == "yes":
        return [MSG_SENDS_WARNING]
    return []


def validate_decision(
    form: DecisionForm,
    inventory: list[Tool],
    auto_result: str = "",
    today: Optional[date] = None,
    pilot_slots: Optional[int] = None,
) -> dict[str, str]:
    """Return {field: message}. An empty dict means the decision can be sent.

    auto_result is the request's automatic security check. "Passed automatically" can only be
    kept when the request passed; a reviewer can always change it to Needed.
    pilot_slots is how many tools can be in pilot at once. Approvals are refused while every
    slot is in use, because every approval starts a new pilot.
    """
    today = today or date.today()
    errors: dict[str, str] = {}
    c = form.checklist
    if c.already_exists not in YES_NO:
        errors["already_exists"] = "Answer whether an approved tool already does this."
    if c.sends_without_check not in YES_NO:
        errors["sends_without_check"] = (
            "Answer whether it would send anything without a person checking first."
        )
    if c.uses_customer_details not in YES_NO:
        errors["uses_customer_details"] = "Answer whether it uses customer or deal details."
    if c.security_check not in SECURITY_CHECK:
        errors["security_check"] = "Choose where the security screening stands."
    elif c.security_check == "passed" and auto_result != "passed":
        errors["security_check"] = MSG_PASSED_ONLY

    if form.outcome not in OUTCOMES:
        errors["outcome"] = "Choose an outcome."
    if not form.reason.strip():
        errors["reason"] = "Write the reason the requester will see."
    if not form.what_would_change.strip():
        errors["what_would_change"] = "Say what would change the answer."
    for key, label in (
        ("reason", "The reason"),
        ("what_would_change", "What would change the answer"),
        ("limits", "The limits"),
    ):
        msg = too_long_message(label, getattr(form, key))
        if msg:
            errors[key] = msg

    if form.outcome == "use_existing":
        usable = {t.id for t in inventory if t.status != "retired"}
        if form.existing_tool_id not in usable:
            errors["existing_tool_id"] = "Choose the tool to point the requester to."

    if form.outcome == "approve_with_limits" and not form.limits.strip():
        errors["limits"] = "Write the limits that come with this approval."

    if form.outcome == "not_now":
        latest = add_months(today, REVISIT_MAX_MONTHS)
        if form.revisit_on is None:
            errors["revisit_on"] = "Pick the date to look at this again."
        elif form.revisit_on <= today:
            errors["revisit_on"] = "Pick a date after today."
        elif form.revisit_on > latest:
            errors["revisit_on"] = (
                f"Pick a date within {REVISIT_MAX_MONTHS} months, {long_date(latest)} at the latest."
            )

    if form.outcome in APPROVALS and pilot_slots is not None:
        slots = slot_count(inventory, pilot_slots)
        if slots["full"]:
            errors["outcome"] = msg_slots_full(slots["total"])

    if form.outcome in APPROVALS:
        if c.security_check == "needed":
            errors["security_check"] = MSG_SECURITY
        nt = form.new_tool
        if not nt.name.strip():
            errors["tool_name"] = "Give the new tool a name."
        if not nt.purpose.strip():
            errors["tool_purpose"] = "Say in one sentence what the tool does."
        if not nt.owner_name.strip() or not nt.owner_team.strip():
            errors["tool_owner"] = "Add the owner's name and team."
        if not nt.owner_agreed:
            errors["owner_agreed"] = "Check that the owner has agreed to own this tool."
        if not nt.allowed_info or any(i not in INFO_KINDS for i in nt.allowed_info):
            errors["tool_allowed_info"] = "Choose what information the tool is okay to use."
        if nt.trial_ends is None:
            errors["tool_trial_ends"] = "Pick the date the pilot ends."
    return errors


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "tool"


def build_decision(
    form: DecisionForm, request: Request, decided_by: str, now: datetime
) -> Decision:
    """Turn a valid reviewer form into a Decision. The outcome comes only from the form."""
    drafted = form.drafted_reason.strip()
    return Decision(
        request_id=request.id,
        outcome=form.outcome,
        checklist=form.checklist.as_dict(),
        existing_tool_id=form.existing_tool_id if form.outcome == "use_existing" else None,
        limits=form.limits.strip() if form.outcome == "approve_with_limits" else None,
        reason=form.reason.strip(),
        what_would_change=form.what_would_change.strip(),
        reason_drafted_by_claude=bool(drafted),
        reason_edited=bool(drafted) and drafted != form.reason.strip(),
        decided_by=decided_by,
        decided_at=now,
        revisit_on=form.revisit_on if form.outcome == "not_now" else None,
    )


def build_new_tool(
    form: DecisionForm, request: Request, existing_ids: set[str], today: Optional[date] = None
) -> Tool:
    """Approvals create a tool. New tools always start as a pilot (being_tried)."""
    today = today or date.today()
    nt = form.new_tool
    base = slugify(nt.name)
    tool_id, n = base, 2
    while tool_id in existing_ids:
        tool_id, n = f"{base}-{n}", n + 1
    tool = Tool(
        id=tool_id,
        name=nt.name.strip(),
        purpose=nt.purpose.strip(),
        owner_name=nt.owner_name.strip(),
        owner_team=nt.owner_team.strip(),
        teams=[request.team],
        status="being_tried",
        allowed_info=list(nt.allowed_info),
        limits=form.limits.strip() if form.outcome == "approve_with_limits" else None,
        trial_ends=nt.trial_ends,
        from_request=request.id,
        owner_agreed=True,
        security_check=form.checklist.security_check,
        ready_check={},
        journey=[],
    )
    add_event(tool, "requested", request.submitted_at.date())
    trial = f" until {long_date(nt.trial_ends)}" if nt.trial_ends else ""
    add_event(tool, "being_tried", today, f"By {request.team}{trial}.")
    return tool


class ToolChangeError(ValueError):
    """A tool change that can't be made. `errors` maps form fields to messages."""

    def __init__(self, message: str, field: str = "", errors: Optional[dict[str, str]] = None):
        super().__init__(message)
        self.errors = errors or ({field: message} if field else {})


def add_event(tool: Tool, kind: str, on: date, note: Optional[str] = None) -> None:
    """Add a step to the tool's journey."""
    assert kind in JOURNEY_EVENTS, kind
    tool.journey = list(tool.journey or []) + [
        {"kind": kind, "date": on.isoformat(), "note": (note or "").strip() or None}
    ]


def one_line(text: str) -> str:
    return " ".join((text or "").split())


# ---- Pilot slots -------------------------------------------------------------------


def slot_count(tools: list[Tool], total: int) -> dict[str, Any]:
    """Every tool in pilot uses a slot, even after its end date, until it is shipped or retired."""
    pilots = sorted([t for t in tools if t.status == "being_tried"], key=lambda t: t.name)
    return {"used": len(pilots), "total": total, "pilots": pilots, "full": len(pilots) >= total}


def slots_line(slots: dict[str, Any]) -> str:
    line = f"Pilot slots: {slots['used']} of {slots['total']} used."
    if slots["full"]:
        line += " Ship or retire a pilot to make room."
    return line


# ---- Not now ------------------------------------------------------------------------


def latest_decision(decisions: list[Decision], request_id: str) -> Optional[Decision]:
    """A request decided again after Not now keeps every decision. The newest one counts."""
    mine = [d for d in decisions if d.request_id == request_id]
    return max(mine, key=lambda d: (d.decided_at, d.id or 0)) if mine else None


def latest_decisions(decisions: list[Decision]) -> dict[str, Decision]:
    out: dict[str, Decision] = {}
    for d in sorted(decisions, key=lambda d: (d.decided_at, d.id or 0)):
        out[d.request_id] = d
    return out


def is_not_now(request: Request, decision: Optional[Decision]) -> bool:
    return request.status == "decided" and decision is not None and decision.outcome == "not_now"


def revisit_is_due(request: Request, decision: Optional[Decision], today: date) -> bool:
    """A Not now request comes back on its revisit date. The date itself counts."""
    return is_not_now(request, decision) and decision.revisit_on is not None and decision.revisit_on <= today


def revisit_due(requests: list[Request], decisions: list[Decision], today: date) -> list[dict[str, Any]]:
    """Not now requests whose revisit date has arrived, for "Needs a decision"."""
    latest = latest_decisions(decisions)
    items = []
    for r in sorted(requests, key=lambda r: r.title):
        d = latest.get(r.id)
        if revisit_is_due(r, d, today):
            n = needed_by_count(r)
            people = "1 person" if n == 1 else f"{n} people"
            line = f"Revisit: Not now since {long_date(d.decided_at.date())}. Needed by {people}."
            items.append({"request": r, "decision": d, "flag": "not_now", "line": line})
    return items


def reopen_request(request: Request, decision: Optional[Decision], today: date) -> Request:
    """Send a Not now request back to waiting. Its earlier decision and timeline are kept."""
    if not revisit_is_due(request, decision, today):
        raise RequestChangeError("Only a Not now request whose revisit date has arrived can be reopened.")
    request.status = "waiting"
    request.draft = None
    request.timeline = list(request.timeline) + [{"label": "Reopened after Not now", "date": today.isoformat()}]
    return request


# ---- Pilot ended and Review due ---------------------------------------------------


def trial_ended(tool: Tool, today: date) -> bool:
    """A tool in pilot whose end date has passed. The end date itself still counts."""
    return tool.status == "being_tried" and tool.trial_ends is not None and tool.trial_ends < today


def review_due(tool: Tool, today: date) -> bool:
    """An approved tool whose next review month has passed. The month itself still counts."""
    if tool.status not in READY_STATUSES:
        return False
    month = parse_month(tool.next_review)
    return month is not None and (month.year, month.month) < (today.year, today.month)


def tool_flags(tool: Tool, today: date) -> list[str]:
    flags = []
    if trial_ended(tool, today):
        flags.append("trial_ended")
    if review_due(tool, today):
        flags.append("review_due")
    return flags


def _ago(days: int) -> str:
    if days <= 0:
        return "today"
    return "yesterday" if days == 1 else f"{days} days ago"


def needs_decision(tools: list[Tool], today: date) -> list[dict[str, Any]]:
    """Tools a reviewer should look at: pilots that ran out and reviews that came due."""
    items = []
    for t in sorted(tools, key=lambda t: t.name):
        if trial_ended(t, today):
            team = t.teams[0] if t.teams else t.owner_team
            line = f"In pilot with {team}. Pilot ended {_ago((today - t.trial_ends).days)}."
            items.append({"tool": t, "flag": "trial_ended", "line": line})
        elif review_due(t, today):
            line = (
                f"{TOOL_STATUSES[t.status]}. Owner {t.owner_name}, {t.owner_team}. "
                f"Review was due in {t.next_review}."
            )
            items.append({"tool": t, "flag": "review_due", "line": line})
    return items


# ---- The ready to ship check -------------------------------------------------------


@dataclass
class ReadyItem:
    key: str
    label: str
    done: bool


def valid_test_link(link: str) -> bool:
    """Test result links must be http or https web addresses."""
    link = (link or "").strip()
    if not link or any(c.isspace() for c in link):
        return False
    parsed = urlparse(link)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def ready_items(tool: Tool) -> list[ReadyItem]:
    rc = tool.ready_check or {}
    link = str(rc.get("test_link") or "").strip()
    return [
        ReadyItem("owner", "Owner agreed to own it", bool(tool.owner_agreed)),
        ReadyItem(
            "security", "Security screening done or not needed", tool.security_check in SECURITY_COVERED
        ),
        ReadyItem(
            "kept_using",
            "The team kept using it",
            rc.get("kept_using") in ("regularly", "sometimes") and bool(str(rc.get("went_wrong") or "").strip()),
        ),
        ReadyItem(
            "tested",
            "How it was tested",
            bool(str(rc.get("how_tested") or "").strip()) and (not link or valid_test_link(link)),
        ),
    ]


def ready_count(tool: Tool) -> int:
    return sum(item.done for item in ready_items(tool))


def team_stopped(tool: Tool) -> bool:
    return (tool.ready_check or {}).get("kept_using") == "stopped"


def can_ship(tool: Tool) -> bool:
    return tool.status == "being_tried" and not team_stopped(tool) and ready_count(tool) == READY_TOTAL


def save_ready_answers(
    tool: Tool, kept_using: str, went_wrong: str, how_tested: str, test_link: str
) -> None:
    """Save the reviewer's answers. Answers can be saved a part at a time."""
    if tool.status != "being_tried":
        raise ToolChangeError("Only a tool in pilot has a ready to ship check.")
    kept_using, went_wrong = kept_using.strip(), went_wrong.strip()
    how_tested, test_link = how_tested.strip(), test_link.strip()
    errors: dict[str, str] = {}
    if kept_using and kept_using not in KEPT_USING:
        errors["kept_using"] = "Choose whether the team kept using it."
    if went_wrong and not kept_using:
        errors["kept_using"] = "Answer whether the team kept using it."
    if kept_using and not went_wrong:
        errors["went_wrong"] = "Say whether anything went wrong. \"Nothing\" is a fine answer."
    if test_link and not valid_test_link(test_link):
        errors["test_link"] = "Test result links start with http:// or https://"
    if test_link and not how_tested:
        errors["how_tested"] = "Say how it was tested."
    for key, label, text in (
        ("went_wrong", "What went wrong", went_wrong),
        ("how_tested", "How it was tested", how_tested),
        ("test_link", "The link", test_link),
    ):
        if msg := too_long_message(label, text):
            errors[key] = msg
    if errors:
        raise ToolChangeError("Please fix the answers below.", errors=errors)
    rc = dict(tool.ready_check or {})
    rc.update(kept_using=kept_using, went_wrong=went_wrong, how_tested=how_tested, test_link=test_link)
    tool.ready_check = rc


def record_security_check(tool: Tool, done: bool, on: Optional[date], note: str, today: date) -> None:
    """Record a security check that was needed when the tool was approved."""
    if tool.status != "being_tried":
        raise ToolChangeError("Only a tool in pilot has a ready to ship check.")
    if tool.security_check != "needed":
        raise ToolChangeError("The security screening is already covered for this tool.")
    note = one_line(note)
    errors: dict[str, str] = {}
    if not done:
        errors["security_done"] = "Check \"Security screening done\" to record it."
    if on is None:
        errors["security_date"] = "Pick the date the screening was done."
    elif on > today:
        errors["security_date"] = "The date can't be in the future."
    if not note:
        errors["security_note"] = "Add a one-line note about the screening."
    elif len(note) > MAX_LINE:
        errors["security_note"] = f"Keep the note to one line, under {MAX_LINE} characters."
    if errors:
        raise ToolChangeError("Please fix the security screening below.", errors=errors)
    tool.security_check = "done"
    tool.ready_check = {**(tool.ready_check or {}), "security_date": on.isoformat(), "security_note": note}
    add_event(tool, "security_done", on, note)


def ship_tool(tool: Tool, to_status: str, limits: str = "", today: Optional[date] = None) -> Tool:
    """Move a tool from pilot to approved or approved with limits.

    This is the promotion gate: it refuses until all four ready to ship items are done.
    """
    if tool.status != "being_tried":
        raise ToolChangeError("Only a tool in pilot can be shipped.")
    if team_stopped(tool):
        raise ToolChangeError(MSG_STOPPED)
    n = ready_count(tool)
    if n < READY_TOTAL:
        raise ToolChangeError(
            f"Ship it opens when all {READY_TOTAL} items are ready. {n} of {READY_TOTAL} ready now."
        )
    if to_status not in READY_STATUSES:
        raise ToolChangeError("Choose Approved or Approved with limits.", field="to_status")
    if to_status == "approved_with_limits" and not limits.strip():
        raise ToolChangeError("Write the limits that come with this approval.", field="ship_limits")
    if msg := too_long_message("The limits", limits):
        raise ToolChangeError(msg, field="ship_limits")
    tool.status = to_status
    tool.limits = limits.strip() if to_status == "approved_with_limits" else None
    tool.trial_ends = None
    note = TOOL_STATUSES[to_status] + (f". Limit: {tool.limits}" if tool.limits else ".")
    add_event(tool, "shipped", today or date.today(), note)
    return tool


def extend_trial(tool: Tool, new_end: Optional[date], today: date) -> Tool:
    """A pilot can be extended once, by up to 60 days past the current end date."""
    if tool.status != "being_tried" or tool.trial_ends is None:
        raise ToolChangeError("Only a tool in pilot can have its pilot extended.")
    if tool.trial_extended:
        raise ToolChangeError("This pilot was already extended once. Ship it or retire it.", field="new_end")
    latest = tool.trial_ends + timedelta(days=MAX_EXTENSION_DAYS)
    if new_end is None:
        raise ToolChangeError("Pick the new end date.", field="new_end")
    if new_end <= tool.trial_ends:
        raise ToolChangeError(
            f"Pick a date after the current end date, {long_date(tool.trial_ends)}.", field="new_end"
        )
    if new_end > latest:
        raise ToolChangeError(
            f"A pilot can be extended by up to {MAX_EXTENSION_DAYS} days, to {long_date(latest)} at the latest.",
            field="new_end",
        )
    if new_end <= today:
        raise ToolChangeError("Pick a date after today.", field="new_end")
    tool.trial_ends = new_end
    tool.trial_extended = True
    add_event(tool, "extended", today, f"New end date {long_date(new_end)}.")
    return tool


def retire_tool(
    tool: Tool,
    reason: str,
    replaced_by: str = "",
    inventory: Optional[list[Tool]] = None,
    today: Optional[date] = None,
) -> Tool:
    """Retire any tool, whatever its check shows. Needs a one-line reason; a replacement is optional."""
    if tool.status == "retired":
        raise ToolChangeError("This tool is already retired.")
    reason = one_line(reason)
    if not reason:
        raise ToolChangeError("Write a one-line reason for retiring it.", field="retire_reason")
    if len(reason) > MAX_LINE:
        raise ToolChangeError(f"Keep the reason to one line, under {MAX_LINE} characters.", field="retire_reason")
    names = {t.id: t.name for t in (inventory or []) if t.status != "retired" and t.id != tool.id}
    if replaced_by and replaced_by not in names:
        raise ToolChangeError("Choose a replacement from the inventory, or leave it empty.", field="replaced_by")
    tool.status = "retired"
    tool.replaced_by = replaced_by or None
    note = reason + (f" Replaced by {names[replaced_by]}." if replaced_by else "")
    add_event(tool, "retired", today or date.today(), note)
    return tool


REVIEW_MONTHS = 6


def mark_reviewed(
    tool: Tool, still_in_use: str, change: str, next_review: Optional[date], today: date
) -> Tool:
    """Record a review and set the next one, six months later by default."""
    if tool.status not in READY_STATUSES:
        raise ToolChangeError("Only an approved tool has reviews.")
    if still_in_use not in YES_NO:
        raise ToolChangeError("Answer whether it's still in use.", field="still_in_use")
    change = change.strip()
    if msg := too_long_message("Anything to change", change):
        raise ToolChangeError(msg, field="review_change")
    next_review = next_review or add_months(today, REVIEW_MONTHS)
    if (next_review.year, next_review.month) <= (today.year, today.month):
        raise ToolChangeError("Pick a month after this one for the next review.", field="next_review_month")
    tool.next_review = format_month(next_review)
    note = "Still in use: " + ("Yes." if still_in_use == "yes" else "No.")
    if change:
        note += f" To change: {change}"
    add_event(tool, "reviewed", today, note)
    return tool


COPY_FIELDS = ("task", "team", "how_often", "who_uses", "info")


def copy_request_fields(request: Request) -> dict:
    """Prefill for "Start a new request from this one"."""
    data = {k: getattr(request, k) for k in COPY_FIELDS}
    data["info"] = list(request.info)
    data["copied_from"] = request.id
    return data


# ---- I need this too ---------------------------------------------------------------------

OPEN_STATUSES = ("waiting", "in_review")


class RequestChangeError(ValueError):
    """A change to a request that can't be made."""


def needed_by_count(request: Request) -> int:
    """The original requester plus everyone added with "I need this too"."""
    return 1 + len(request.needed_by or [])


def add_needed_by(request: Request, name: str, note: str, today: date, outcome: str = "") -> Request:
    """Add a person to a request that is still waiting or in review, or decided as Not now.

    outcome is the request's latest decision, if any. Not now requests keep counting demand.
    A person can be added only once, and never to their own request.
    """
    name = one_line(name)
    note = one_line(note)
    if not name:
        raise RequestChangeError("We need your name to add you to this request.")
    if request.status not in OPEN_STATUSES and not (request.status == "decided" and outcome == "not_now"):
        raise RequestChangeError("This request already has a decision. You can see it on Decided before.")
    if name == request.requester_name:
        raise RequestChangeError("This is your own request, so you're already on it.")
    if any(p.get("name") == name for p in request.needed_by or []):
        raise RequestChangeError("You're already on this request. You'll see the decision on My requests.")
    if len(note) > MAX_LINE:
        raise RequestChangeError(f"Keep the note to one line, under {MAX_LINE} characters.")
    request.needed_by = list(request.needed_by or []) + [
        {"name": name, "note": note or None, "date": today.isoformat()}
    ]
    return request


# ---- Here's what happens next ---------------------------------------------------------

STEP_STATUSES = {"done": "Done", "next": "Next", "later": "Later"}


def next_steps(request: Request, review_days: int, security_line: str) -> list[dict[str, Any]]:
    """The three steps a requester sees after sending a request.

    security_line is the plain result of the automatic security check for this request.
    """
    auto = auto_security(request)
    days = f"{review_days} working day{'' if review_days == 1 else 's'}"
    return [
        {"key": "security", "title": "Security screening", "line": security_line,
         "status": "done" if auto in ("not_needed", "passed") else "next"},
        {"key": "reviewer", "title": "A reviewer decides",
         "line": f"Reviewers usually answer within {days}.", "status": "next", "current": True},
        {"key": "decision", "title": "You get a decision",
         "line": "You'll see the decision, the reason and what would change the answer on My requests.",
         "status": "later"},
    ]


# ---- What the match check sends to Claude ---------------------------------------------


def open_requests_for_match(store: Any, name: str) -> list[dict]:
    """Requests still waiting or in review, for "I need this too". Never includes who asked.

    The person's own requests, and requests they are already on, are left out. The web app and
    the matching evaluation both use this, so the evaluation sends what the app sends.
    """
    out = []
    latest = latest_decisions(store.list_decisions())
    for r in sorted(store.list_requests(), key=lambda r: r.submitted_at, reverse=True):
        # Not now requests still count demand, so people can join them too.
        if (r.status not in OPEN_STATUSES and not is_not_now(r, latest.get(r.id))) or r.requester_name == name:
            continue
        if any(p.get("name") == name for p in r.needed_by or []):
            continue
        out.append({"id": r.id, "title": r.title, "task": r.task})
    return out[:40]


def past_decisions_for_match(store: Any) -> list[dict]:
    """Decided requests for Asked before. Never includes who asked."""
    requests = {r.id: r for r in store.list_requests()}
    out = []
    for d in sorted(latest_decisions(store.list_decisions()).values(), key=lambda d: d.decided_at, reverse=True):
        r = requests.get(d.request_id)
        if r is None or r.status != "decided":
            continue
        out.append({"id": r.id, "title": r.title, "task": r.task, "outcome": d.outcome,
                    "reason": d.reason, "what_would_change": d.what_would_change})
    return out[:40]
