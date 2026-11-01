"""Where data lives.

DemoStore keeps the demo data in memory and refuses every write, so demo mode
saves nothing. LiveStore saves to a SQLite file in DATA_DIR.
"""

from __future__ import annotations

import copy
import re
from datetime import datetime, time
from pathlib import Path
from typing import Optional

from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session, SQLModel, create_engine, delete, select

from .demo_data import DemoData
from .models import Decision, Request, Tool

JSON_FIELDS = {
    Tool: ("teams", "allowed_info"),
    Request: ("info", "matches", "size_up", "questions", "timeline", "draft"),
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
        return next((copy.deepcopy(d) for d in self._decisions if d.request_id == request_id), None)

    def new_request_id(self) -> str:
        return "r-new"

    def save(self, *objects) -> None:
        raise ReadOnlyError("Demo mode saves nothing.")


class LiveStore:
    read_only = False

    def __init__(self, data_dir: Path):
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            f"sqlite:///{Path(data_dir) / 'sts.db'}", connect_args={"check_same_thread": False}
        )
        SQLModel.metadata.create_all(self.engine)

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
            return s.exec(select(Decision).where(Decision.request_id == request_id)).first()

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
