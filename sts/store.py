"""Where data lives.

DemoStore keeps the demo data in memory and refuses every write, so demo mode
saves nothing. LiveStore saves to a SQLite file in DATA_DIR.
"""

from __future__ import annotations

import copy
import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session, SQLModel, create_engine, delete, select

from .demo_data import DemoData
from .models import CUSTOMER_INFO, Decision, Request, Tool
from .rules import latest_decision

JSON_FIELDS = {
    Tool: ("teams", "allowed_info", "ready_check", "journey"),
    Request: ("info", "matches", "size_up", "questions", "timeline", "draft", "security_answers",
              "security_result", "needed_by"),
    Decision: ("checklist",),
}


class ReadOnlyError(RuntimeError):
    """Raised when something tries to save in demo mode."""


class DemoStore:
    read_only = True

    def __init__(self, data: DemoData):
        self.data = data
        self._tools = data.tools
        self._requests = data.requests
        self._decisions = data.decisions

    def now(self) -> datetime:
        return datetime.combine(self.data.as_of, time(11, 0))

    # Reads return copies so a page can never change the demo data by accident.
    def list_tools(self) -> list[Tool]:
        return [t.model_copy(deep=True) for t in self._tools]

    def get_tool(self, tool_id: str) -> Optional[Tool]:
        return next((t.model_copy(deep=True) for t in self._tools if t.id == tool_id), None)

    def list_requests(self) -> list[Request]:
        return [copy.deepcopy(r) for r in self._requests]

    def get_request(self, request_id: str) -> Optional[Request]:
        return next((copy.deepcopy(r) for r in self._requests if r.id == request_id), None)

    def list_decisions(self) -> list[Decision]:
        return [copy.deepcopy(d) for d in self._decisions]

    def decision_for(self, request_id: str) -> Optional[Decision]:
        """The newest decision. A request decided again after Not now keeps the earlier one."""
        d = latest_decision(self._decisions, request_id)
        return copy.deepcopy(d) if d else None

    def new_request_id(self) -> str:
        return "r-new"

    def save(self, *objects) -> None:
        raise ReadOnlyError("Demo mode saves nothing.")


def upgraded_security(tool: Tool, decision: Optional[Decision]) -> str:
    """For a tool saved before the security check was kept on tools."""
    if decision is not None:
        value = (decision.checklist or {}).get("security_check")
        if value in ("not_needed", "passed", "needed", "done"):
            return value
    # Nothing recorded: a tool that uses customer details needs the check recorded.
    return "needed" if set(tool.allowed_info or []) & CUSTOMER_INFO else "not_needed"


def journey_from_known(
    tool: Tool, origin: Optional[Request], decision: Optional[Decision], today: date
) -> list[dict[str, Any]]:
    """Build a journey for a tool saved by an earlier version, from what is already known."""
    events: list[dict[str, Any]] = []

    def add(kind: str, on: date, note: Optional[str] = None):
        events.append({"kind": kind, "date": on.isoformat(), "note": note})

    if origin is not None:
        add("requested", origin.submitted_at.date())
        for e in origin.timeline or []:
            if str(e.get("label", "")).startswith("Security check") and e.get("date"):
                add("security_done", date.fromisoformat(str(e["date"])[:10]))
    if decision is not None:
        team = (tool.teams or [tool.owner_team])[0]
        add("being_tried", decision.decided_at.date(), f"By {team}.")
    if tool.status != "being_tried" or decision is None:
        # The date of this step wasn't kept, so it is recorded on the day of the upgrade.
        kind = {"being_tried": "being_tried", "retired": "retired"}.get(tool.status, "shipped")
        if not any(e["kind"] == kind for e in events):
            add(kind, today, "Recorded when journeys were added. The earlier date wasn't kept.")
    return sorted(events, key=lambda e: e["date"])


class LiveStore:
    read_only = False

    def __init__(self, data_dir: Path):
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{Path(data_dir) / 'sts.db'}", connect_args={"check_same_thread": False}
        )
        SQLModel.metadata.create_all(self.engine)
        self.upgrade()

    # Columns added after the first version: name -> SQL to add it with a safe default.
    NEW_TOOL_COLUMNS = {
        "security_check": "VARCHAR NOT NULL DEFAULT 'not_needed'",
        "trial_extended": "BOOLEAN NOT NULL DEFAULT 0",
        "ready_check": "JSON",
        "journey": "JSON",
    }
    NEW_REQUEST_COLUMNS = {
        "security_answers": "JSON",
        "security_result": "JSON",
        "needed_by": "JSON",
    }
    NEW_DECISION_COLUMNS = {
        "revisit_on": "DATE",
    }

    def upgrade(self) -> None:
        """Bring a database from an earlier version up to date without losing data.

        create_all() adds missing tables but not missing columns, so new columns are
        added here. Tools without a journey get one built from what is already known.
        Requests saved before the automatic security check keep no result, and the
        reviewer checklist falls back to the earlier read for them.
        """
        added: list[str] = []
        with self.engine.begin() as conn:
            for table, columns in (("tool", self.NEW_TOOL_COLUMNS), ("request", self.NEW_REQUEST_COLUMNS),
                                   ("decision", self.NEW_DECISION_COLUMNS)):
                have = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
                for name in columns:
                    if name not in have:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {columns[name]}"))
                        if table == "tool":
                            added.append(name)
        with self._session() as s:
            old_requests = [r for r in s.exec(select(Request)) if r.needed_by is None or r.security_answers is None]
        for r in old_requests:
            r.needed_by = r.needed_by or []
            r.security_answers = r.security_answers or {}
        if old_requests:
            self.save(*old_requests)
        with self._session() as s:
            tools = list(s.exec(select(Tool)))
            if not any(t.journey is None or t.ready_check is None for t in tools):
                return
            requests = {r.id: r for r in s.exec(select(Request))}
            decisions = {d.request_id: d for d in s.exec(select(Decision))}
        today = self.now().date()
        changed = []
        for t in tools:
            if t.ready_check is None:
                t.ready_check = {}
            if t.journey is None:
                origin = requests.get(t.from_request or "")
                decision = decisions.get(t.from_request or "")
                if "security_check" in added:
                    t.security_check = upgraded_security(t, decision)
                t.journey = journey_from_known(t, origin, decision, today)
            changed.append(t)
        self.save(*changed)

    def _session(self) -> Session:
        return Session(self.engine, expire_on_commit=False)

    def now(self) -> datetime:
        return datetime.now().replace(microsecond=0)

    def list_tools(self) -> list[Tool]:
        with self._session() as s:
            return list(s.exec(select(Tool).order_by(Tool.name)))

    def get_tool(self, tool_id: str) -> Optional[Tool]:
        with self._session() as s:
            return s.get(Tool, tool_id)

    def list_requests(self) -> list[Request]:
        with self._session() as s:
            return list(s.exec(select(Request)))

    def get_request(self, request_id: str) -> Optional[Request]:
        with self._session() as s:
            return s.get(Request, request_id)

    def list_decisions(self) -> list[Decision]:
        with self._session() as s:
            return list(s.exec(select(Decision)))

    def decision_for(self, request_id: str) -> Optional[Decision]:
        with self._session() as s:
            # The newest decision. A request decided again after Not now keeps the earlier one.
            return s.exec(
                select(Decision).where(Decision.request_id == request_id)
                .order_by(Decision.decided_at.desc(), Decision.id.desc())
            ).first()

    def new_request_id(self) -> str:
        nums = [int(m.group(1)) for r in self.list_requests() if (m := re.fullmatch(r"r-(\d+)", r.id))]
        return f"r-{max(nums + [2000]) + 1}"

    def save(self, *objects) -> None:
        with self._session() as s:
            for obj in objects:
                merged = s.merge(obj)
                for name in JSON_FIELDS.get(type(obj), ()):
                    setattr(merged, name, copy.deepcopy(getattr(obj, name)))
                    flag_modified(merged, name)
            s.commit()

    def has_data(self) -> bool:
        return bool(self.list_tools() or self.list_requests())

    def load_demo(self, data: DemoData) -> None:
        """Replace everything with the demo data (used by `sts seed --reset`)."""
        with self._session() as s:
            for model in (Decision, Request, Tool):
                s.exec(delete(model))
            s.commit()
        self.save(*data.tools, *data.requests, *[copy.deepcopy(d) for d in data.decisions])
