"""Load and check the demo data files in demo/.

Files are checked with Pydantic. Problems are reported with the file name and
the field, for example: demo/tools.yaml, tools[3].status: ...
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from .models import (
    HOW_OFTEN,
    INFO_KINDS,
    OUTCOMES,
    SECURITY_CHECK,
    TEAMS,
    TOOL_STATUSES,
    WHO_USES,
    Decision,
    Request,
    Tool,
)
from .provider import DraftReason, MatchItem, SizeUp

InfoKind = Literal["customer_contact", "deal_pricing", "internal_notes", "public_only"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolIn(Strict):
    id: str
    name: str
    purpose: str
    owner_name: str
    owner_team: str
    teams: list[str]
    status: Literal["being_tried", "approved", "approved_with_limits", "retired"]
    allowed_info: list[InfoKind]
    limits: Optional[str] = None
    trial_ends: Optional[date] = None
    next_review: Optional[str] = None
    link: Optional[str] = None
    replaced_by: Optional[str] = None
    from_request: Optional[str] = None

    @model_validator(mode="after")
    def _status_fields(self):
        if self.status == "approved_with_limits" and not self.limits:
            raise ValueError("limits is required when status is approved_with_limits")
        if self.status == "being_tried" and not self.trial_ends:
            raise ValueError("trial_ends is required when status is being_tried")
        return self


class ChecklistIn(Strict):
    already_exists: Literal["yes", "no"]
    sends_without_check: Literal["yes", "no"]
    uses_customer_details: Literal["yes", "no"]
    security_check: Literal["not_needed", "needed", "done"]


class DecisionIn(Strict):
    outcome: Literal["approve", "approve_with_limits", "use_existing", "not_approved"]
    checklist: ChecklistIn
    existing_tool_id: Optional[str] = None
    limits: Optional[str] = None
    reason: str
    what_would_change: str
    reason_drafted_by_claude: bool = True
    reason_edited: bool = False
    decided_by: str
    decided_at: date

    @model_validator(mode="after")
    def _outcome_fields(self):
        if self.outcome == "use_existing" and not self.existing_tool_id:
            raise ValueError("existing_tool_id is required when outcome is use_existing")
        if self.outcome == "approve_with_limits" and not self.limits:
            raise ValueError("limits is required when outcome is approve_with_limits")
        return self


class QuestionIn(Strict):
    text: str
    date: date
    handled: bool = False


class EventIn(Strict):
    label: str
    date: date


class RequestIn(Strict):
    id: str
    title: str
    task: str
    team: str
    how_often: Literal["every_day", "few_week", "few_month", "rarely"]
    who_uses: Literal["just_me", "my_team", "several_teams"]
    info: list[InfoKind]
    extra: Optional[str] = None
    whats_missing: Optional[str] = None
    requester_name: str
    submitted_at: date
    status: Literal["waiting", "in_review", "decided"]
    copied_from: Optional[str] = None
    questions: list[QuestionIn] = []
    timeline: list[EventIn] = []
    decision: Optional[DecisionIn] = None

    @field_validator("team")
    @classmethod
    def _team(cls, v):
        if v not in TEAMS:
            raise ValueError(f"team must be one of: {', '.join(TEAMS)}")
        return v

    @model_validator(mode="after")
    def _decided(self):
        if self.status == "decided" and self.decision is None:
            raise ValueError("a decided request needs a decision")
        if self.status != "decided" and self.decision is not None:
            raise ValueError("only a decided request can have a decision")
        return self


class RequestsFile(Strict):
    as_of: date
    demo_requester: str
    demo_reviewer: str
    requests: list[RequestIn]


class ToolsFile(Strict):
    tools: list[ToolIn]


class RecordedFile(Strict):
    request_id: str
    matches: list[MatchItem]
    size_up: SizeUp
    drafts: dict[Literal["approve", "approve_with_limits", "use_existing", "not_approved"], DraftReason] = {}


class DemoDataError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def _fmt(file: str, prefix: str, err: ValidationError) -> list[str]:
    out = []
    for e in err.errors():
        loc = prefix
        for part in e["loc"]:
            loc += f"[{part}]" if isinstance(part, int) else (f".{part}" if loc else str(part))
        out.append(f"{file}, {loc or 'file'}: {e['msg']}")
    return out


def _read_yaml(path: Path, problems: list[str]):
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        problems.append(f"{path.as_posix()}: file not found")
    except yaml.YAMLError as exc:
        problems.append(f"{path.as_posix()}: not valid YAML ({exc.__class__.__name__})")
    return None


@dataclass
class DemoData:
    tools: list[Tool]
    requests: list[Request]
    decisions: list[Decision]
    recorded: dict[str, dict]
    as_of: date
    demo_requester: str
    demo_reviewer: str
    example_request_id: str = ""
    problems: list[str] = field(default_factory=list)


def _at(d: date, hour: int = 10) -> datetime:
    return datetime.combine(d, time(hour, 0))


def load_demo_data(demo_dir: Path) -> DemoData:
    demo_dir = Path(demo_dir)
    problems: list[str] = []
    tools_name = "demo/tools.yaml"
    req_name = "demo/requests.yaml"

    tools_raw = _read_yaml(demo_dir / "tools.yaml", problems)
    reqs_raw = _read_yaml(demo_dir / "requests.yaml", problems)
    tools_file = reqs_file = None
    if tools_raw is not None:
        try:
            tools_file = ToolsFile.model_validate(tools_raw)
        except ValidationError as exc:
            problems += _fmt(tools_name, "", exc)
    if reqs_raw is not None:
        try:
            reqs_file = RequestsFile.model_validate(reqs_raw)
        except ValidationError as exc:
            problems += _fmt(req_name, "", exc)

    recorded: dict[str, dict] = {}
    rec_dir = demo_dir / "recorded"
    for path in sorted(rec_dir.glob("*.json")) if rec_dir.exists() else []:
        name = f"demo/recorded/{path.name}"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            rec = RecordedFile.model_validate(raw)
        except json.JSONDecodeError as exc:
            problems.append(f"{name}: not valid JSON (line {exc.lineno})")
            continue
        except ValidationError as exc:
            problems += _fmt(name, "", exc)
            continue
        if rec.request_id != path.stem:
            problems.append(f"{name}, request_id: should be {path.stem!r} to match the file name")
        recorded[path.stem] = rec.model_dump(mode="json")

    if problems:
        raise DemoDataError(problems)

    # Cross-file checks.
    tool_ids = [t.id for t in tools_file.tools]
    if len(set(tool_ids)) != len(tool_ids):
        problems.append(f"{tools_name}, tools: two tools share the same id")
    req_ids = {r.id for r in reqs_file.requests}
    for i, t in enumerate(tools_file.tools):
        if t.replaced_by and t.replaced_by not in tool_ids:
            problems.append(f"{tools_name}, tools[{i}].replaced_by: no tool with id {t.replaced_by!r}")
        if t.from_request and t.from_request not in req_ids:
            problems.append(f"{tools_name}, tools[{i}].from_request: no request with id {t.from_request!r}")
    for i, r in enumerate(reqs_file.requests):
        if r.decision and r.decision.existing_tool_id and r.decision.existing_tool_id not in tool_ids:
            problems.append(
                f"{req_name}, requests[{i}].decision.existing_tool_id: no tool with id "
                f"{r.decision.existing_tool_id!r}"
            )
        if r.id not in recorded:
            problems.append(f"demo/recorded/{r.id}.json: missing (every demo request needs recorded results)")
    for rid, rec in recorded.items():
        if rid not in req_ids:
            problems.append(f"demo/recorded/{rid}.json, request_id: no request with this id")
        for j, m in enumerate(rec["matches"]):
            if m["tool_id"] not in tool_ids:
                problems.append(f"demo/recorded/{rid}.json, matches[{j}].tool_id: no tool with id {m['tool_id']!r}")
    if problems:
        raise DemoDataError(problems)

    tools = [Tool(**t.model_dump(), owner_agreed=True) for t in tools_file.tools]
    requests: list[Request] = []
    decisions: list[Decision] = []
    for r in reqs_file.requests:
        rec = recorded[r.id]
        data = r.model_dump(exclude={"decision", "questions", "timeline", "submitted_at"})
        req = Request(
            **data,
            submitted_at=_at(r.submitted_at, 9),
            matches=rec["matches"],
            size_up=rec["size_up"],
            questions=[q.model_dump(mode="json") for q in r.questions],
            timeline=[e.model_dump(mode="json") for e in r.timeline],
        )
        requests.append(req)
        if r.decision:
            d = r.decision.model_dump(exclude={"decided_at"})
            d["checklist"] = r.decision.checklist.model_dump()
            decisions.append(Decision(**d, request_id=r.id, decided_at=_at(r.decision.decided_at, 15)))

    example = next(
        (r.id for r in requests if r.requester_name == reqs_file.demo_requester and r.status == "waiting"),
        "",
    )
    return DemoData(
        tools=tools,
        requests=requests,
        decisions=decisions,
        recorded=recorded,
        as_of=reqs_file.as_of,
        demo_requester=reqs_file.demo_requester,
        demo_reviewer=reqs_file.demo_reviewer,
        example_request_id=example,
    )


def check_demo_data(demo_dir: Path) -> list[str]:
    try:
        load_demo_data(demo_dir)
    except DemoDataError as exc:
        return exc.problems
    return []
