"""The reviewer checklist and the decision rules.

A person always chooses the outcome. Nothing in this module reads an outcome
from Claude's output: the outcome only ever comes from the reviewer's form.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from .models import (
    CUSTOMER_INFO,
    INFO_KINDS,
    MAX_TEXT,
    OUTCOMES,
    READY_STATUSES,
    SECURITY_CHECK,
    Decision,
    Request,
    Tool,
)

YES_NO = ("yes", "no")
APPROVALS = ("approve", "approve_with_limits")

MSG_SECURITY = "Finish the security check before approving."
MSG_SENDS_WARNING = "Northstar doesn't approve tools that send to customers on their own."


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
    security_check: str = "not_needed"  # not_needed / needed / done

    def as_dict(self) -> dict:
        return {
            "already_exists": self.already_exists,
            "sends_without_check": self.sends_without_check,
            "uses_customer_details": self.uses_customer_details,
            "security_check": self.security_check,
        }


def prefill_checklist(request: Request) -> Checklist:
    """Start the checklist from what the request says. The reviewer can change anything."""
    uses_customer = bool(set(request.info) & CUSTOMER_INFO)
    security = "not_needed"
    if request.size_up and request.size_up.get("security_check_needed"):
        security = "needed"
    if any(e.get("label", "").startswith("Security check") for e in request.timeline):
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


def warnings_for(form: DecisionForm) -> list[str]:
    """Plain warnings shown above the decision. They never block it."""
    if form.checklist.sends_without_check == "yes":
        return [MSG_SENDS_WARNING]
    return []


def validate_decision(form: DecisionForm, inventory: list[Tool]) -> dict[str, str]:
    """Return {field: message}. An empty dict means the decision can be sent."""
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
        errors["security_check"] = "Choose where the security check stands."

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
            errors["tool_trial_ends"] = "Pick the date the trial ends."
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
    )


def build_new_tool(form: DecisionForm, request: Request, existing_ids: set[str]) -> Tool:
    """Approvals create a tool. New tools always start as being tried."""
    nt = form.new_tool
    base = slugify(nt.name)
    tool_id, n = base, 2
    while tool_id in existing_ids:
        tool_id, n = f"{base}-{n}", n + 1
    return Tool(
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
    )


class ToolChangeError(ValueError):
    pass


def ship_tool(tool: Tool, to_status: str, limits: str = "") -> Tool:
    """Move a tool from being tried to approved or approved with limits."""
    if tool.status != "being_tried":
        raise ToolChangeError("Only a tool that is being tried can be shipped.")
    if to_status not in READY_STATUSES:
        raise ToolChangeError("Choose Approved or Approved with limits.")
    if to_status == "approved_with_limits" and not limits.strip():
        raise ToolChangeError("Write the limits that come with this approval.")
    tool.status = to_status
    tool.limits = limits.strip() if to_status == "approved_with_limits" else None
    tool.trial_ends = None
    return tool


def retire_tool(tool: Tool, replaced_by: str = "", inventory: Optional[list[Tool]] = None) -> Tool:
    """Retire any tool. A replacement is optional."""
    if replaced_by:
        ids = {t.id for t in (inventory or []) if t.status != "retired" and t.id != tool.id}
        if replaced_by not in ids:
            raise ToolChangeError("Choose a replacement from the inventory, or leave it empty.")
    tool.status = "retired"
    tool.replaced_by = replaced_by or None
    return tool


COPY_FIELDS = ("task", "team", "how_often", "who_uses", "info")


def copy_request_fields(request: Request) -> dict:
    """Prefill for "Start a new request from this one"."""
    data = {k: getattr(request, k) for k in COPY_FIELDS}
    data["info"] = list(request.info)
    data["copied_from"] = request.id
    return data
