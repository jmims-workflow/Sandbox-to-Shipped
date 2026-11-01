"""Saved data: tools, requests and decisions.

The same classes hold demo data (kept in memory, never saved) and live data
(saved to SQLite through SQLModel).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import NaiveDatetime
from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

# Information kinds, used on requests and tools.
INFO_KINDS: dict[str, str] = {
    "customer_contact": "Customer names or contact details",
    "deal_pricing": "Deal or pricing details",
    "internal_notes": "Internal notes only",
    "public_only": "Public information only",
}
CUSTOMER_INFO = {"customer_contact", "deal_pricing"}

TEAMS = ["Marketing", "Sales", "Partnerships", "Customer success", "Support"]

HOW_OFTEN: dict[str, str] = {
    "every_day": "Every day",
    "few_week": "A few times a week",
    "few_month": "A few times a month",
    "rarely": "Rarely",
}
WHO_USES: dict[str, str] = {
    "just_me": "Just me",
    "my_team": "My team",
    "several_teams": "Several teams",
}

TOOL_STATUSES: dict[str, str] = {
    "being_tried": "Being tried",
    "approved": "Approved",
    "approved_with_limits": "Approved with limits",
    "retired": "Retired",
}
MATCHABLE_STATUSES = {"approved", "approved_with_limits", "being_tried"}
READY_STATUSES = {"approved", "approved_with_limits"}

REQUEST_STATUSES: dict[str, str] = {
    "waiting": "Waiting",
    "in_review": "In review",
    "decided": "Decided",
}

OUTCOMES: dict[str, str] = {
    "approve": "Approved",
    "approve_with_limits": "Approved with limits",
    "use_existing": "Use a tool we have",
    "not_approved": "Not approved as requested",
}
# Shorter labels for the reviewer's radio cards.
OUTCOME_CHOICES: dict[str, str] = {
    "approve": "Approve",
    "approve_with_limits": "Approve with limits",
    "use_existing": "Use an existing tool",
    "not_approved": "Not approved",
}

SECURITY_CHECK: dict[str, str] = {
    "not_needed": "Not needed",
    "needed": "Needed",
    "done": "Done",
}

# The ready to ship check: "Did the team keep using it?"
KEPT_USING: dict[str, str] = {
    "regularly": "Yes, regularly",
    "sometimes": "Some of the time",
    "stopped": "No",
}

# Each tool's journey. Every event has a date and an optional note.
JOURNEY_EVENTS: dict[str, str] = {
    "requested": "Requested",
    "being_tried": "Started being tried",
    "security_done": "Security check done",
    "extended": "Trial extended",
    "shipped": "Shipped",
    "reviewed": "Reviewed",
    "retired": "Retired",
}

MAX_TEXT = 5000
MAX_LINE = 300


class Tool(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    purpose: str
    owner_name: str
    owner_team: str
    teams: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = "being_tried"
    allowed_info: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    limits: Optional[str] = None
    trial_ends: Optional[date] = None
    next_review: Optional[str] = None
    link: Optional[str] = None
    replaced_by: Optional[str] = None
    from_request: Optional[str] = None
    owner_agreed: bool = True
    # From the decision that created the tool: not_needed, needed or done.
    security_check: str = "not_needed"
    trial_extended: bool = False
    # Answers recorded in the ready to ship check:
    # {"kept_using", "went_wrong", "how_tested", "test_link", "security_date", "security_note"}
    ready_check: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    # Each event: {"kind": one of JOURNEY_EVENTS, "date": "YYYY-MM-DD", "note": str or None}
    journey: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))


class Request(SQLModel, table=True):
    id: str = Field(primary_key=True)
    title: str
    task: str
    team: str
    how_often: str
    who_uses: str
    info: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    extra: Optional[str] = None
    whats_missing: Optional[str] = None
    requester_name: str
    submitted_at: NaiveDatetime
    status: str = "waiting"
    # Each match: {"tool_id", "confidence": "close"|"possible", "reason"}
    matches: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    matches_seen: bool = True
    # Claude's read: {"title", "bullets": [{"label", "text"}], "security_check_needed"}
    size_up: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    copied_from: Optional[str] = None
    # Each question: {"text", "date", "handled"}
    questions: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    # Each event: {"label", "date"}
    timeline: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    # A reviewer's unsent decision, from "Save for later".
    draft: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))


class Decision(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    request_id: str = Field(index=True)
    outcome: str
    checklist: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    existing_tool_id: Optional[str] = None
    limits: Optional[str] = None
    reason: str
    what_would_change: str
    reason_drafted_by_claude: bool = False
    reason_edited: bool = False
    decided_by: str
    decided_at: NaiveDatetime
