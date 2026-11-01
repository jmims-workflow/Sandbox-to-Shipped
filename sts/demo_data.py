"""Load and check the demo data files in demo/.

Files are checked with Pydantic. Problems are reported with the file name and
the field, for example: demo/tools.yaml, tools[3].status: ...

Every demo date is stored as an offset from today ("today", "3 days ago",
"in 2 weeks", "last month"), so the demo always looks current.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Literal, Optional

import yaml
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

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
from .config import ROOT
from .provider import DraftReason, MatchItem, RelatedDecision, RelatedRequest, SizeUp
from .rules import add_months, format_month
from .security import SecurityRules, SecurityRulesError, check_security, load_security_rules

OFFSET_HELP = 'use an offset from today, for example "today", "3 days ago" or "in 2 weeks"'
UNIT_DAYS = {"day": 1, "week": 7}


def offset_parts(text: str) -> tuple[int, str]:
    """Read an offset like "3 days ago" or "in 2 weeks" as (amount, unit). Negative is the past."""
    words = " ".join(str(text).lower().split())
    fixed = {"today": (0, "day"), "yesterday": (-1, "day"), "tomorrow": (1, "day"),
             "last month": (-1, "month"), "next month": (1, "month")}
    if words in fixed:
        return fixed[words]
    if m := re.fullmatch(r"(\d+) (day|week|month)s? ago", words):
        return -int(m.group(1)), m.group(2)
    if m := re.fullmatch(r"in (\d+) (day|week|month)s?", words):
        return int(m.group(1)), m.group(2)
    raise ValueError(OFFSET_HELP)


def relative_date(text: str, today: date) -> date:
    amount, unit = offset_parts(text)
    if unit == "month":
        return add_months(today, amount)
    return today + timedelta(days=amount * UNIT_DAYS[unit])


def _today(info: ValidationInfo) -> date:
    return (info.context or {}).get("today") or date.today()


def _rel_date(value, info: ValidationInfo):
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        raise ValueError(f"dates are stored as offsets: {OFFSET_HELP}")
    return relative_date(str(value), _today(info))


def _rel_month(value, info: ValidationInfo):
    if value is None:
        return None
    return format_month(_rel_date(value, info))


# A date written as an offset from today, turned into a real date when loaded.
RelDate = Annotated[date, BeforeValidator(_rel_date)]
# A month written as an offset ("last month", "in 3 months"), loaded as "March 2027".
RelMonth = Annotated[str, BeforeValidator(_rel_month)]

InfoKind = Literal["customer_contact", "deal_pricing", "internal_notes", "sensitive_personal", "public_only"]
YesNoNotSure = Literal["yes", "no", "not_sure"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadyCheckIn(Strict):
    kept_using: Optional[Literal["regularly", "sometimes", "stopped"]] = None
    went_wrong: str = ""
    how_tested: str = ""
    test_link: str = ""
    security_date: Optional[RelDate] = None
    security_note: str = ""


class JourneyIn(Strict):
    kind: Literal["requested", "being_tried", "security_done", "extended", "shipped", "reviewed", "retired"]
    date: RelDate
    note: Optional[str] = None


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
    trial_ends: Optional[RelDate] = None
    next_review: Optional[RelMonth] = None
    link: Optional[str] = None
    replaced_by: Optional[str] = None
    from_request: Optional[str] = None
    security_check: Optional[Literal["not_needed", "passed", "needed", "done"]] = None
    trial_extended: bool = False
    ready_check: ReadyCheckIn = ReadyCheckIn()
    journey: list[JourneyIn] = []

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
    security_check: Literal["not_needed", "passed", "needed", "done"]


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
    decided_at: RelDate

    @model_validator(mode="after")
    def _outcome_fields(self):
        if self.outcome == "use_existing" and not self.existing_tool_id:
            raise ValueError("existing_tool_id is required when outcome is use_existing")
        if self.outcome == "approve_with_limits" and not self.limits:
            raise ValueError("limits is required when outcome is approve_with_limits")
        return self


class QuestionIn(Strict):
    text: str
    date: RelDate
    handled: bool = False


class EventIn(Strict):
    label: str
    date: RelDate


class SecurityAnswersIn(Strict):
    sends_without_check: YesNoNotSure
    keeps_elsewhere: YesNoNotSure
    ai_service: str


class NeededByIn(Strict):
    name: str
    note: Optional[str] = None
    date: RelDate


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
    submitted_at: RelDate
    status: Literal["waiting", "in_review", "decided"]
    copied_from: Optional[str] = None
    questions: list[QuestionIn] = []
    timeline: list[EventIn] = []
    security_answers: Optional[SecurityAnswersIn] = None
    needed_by: list[NeededByIn] = []
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
        if any(i != "public_only" for i in self.info) and self.security_answers is None:
            raise ValueError("security_answers is required when info includes anything other than public_only")
        names = [p.name for p in self.needed_by]
        if self.requester_name in names or len(set(names)) != len(names):
            raise ValueError("needed_by lists each person once and never the requester")
        return self


class RequestsFile(Strict):
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
    related_decision: Optional[RelatedDecision] = None
    related_request: Optional[RelatedRequest] = None


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


def load_demo_data(
    demo_dir: Path, today: Optional[date] = None, rules: Optional[SecurityRules] = None
) -> DemoData:
    """Load the demo files. Offsets are counted from `today` (the real date by default).

    Each request's security check is worked out from security's rules, the same way as live mode.
    """
    today = today or date.today()
    rules = rules or load_security_rules(ROOT / "security_rules.yaml")
    ctx = {"today": today}
    demo_dir = Path(demo_dir)
    problems: list[str] = []
    tools_name = "demo/tools.yaml"
    req_name = "demo/requests.yaml"

    tools_raw = _read_yaml(demo_dir / "tools.yaml", problems)
    reqs_raw = _read_yaml(demo_dir / "requests.yaml", problems)
    tools_file = reqs_file = None
    if tools_raw is not None:
        try:
            tools_file = ToolsFile.model_validate(tools_raw, context=ctx)
        except ValidationError as exc:
            problems += _fmt(tools_name, "", exc)
    if reqs_raw is not None:
        try:
            reqs_file = RequestsFile.model_validate(reqs_raw, context=ctx)
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
        related = rec.get("related_decision")
        decided_ids = {r.id for r in reqs_file.requests if r.decision}
        if related and related["request_id"] not in decided_ids:
            problems.append(
                f"demo/recorded/{rid}.json, related_decision.request_id: no decided request with id "
                f"{related['request_id']!r}"
            )
        related_req = rec.get("related_request")
        open_ids = {r.id for r in reqs_file.requests if r.status in ("waiting", "in_review")}
        if related_req and related_req["request_id"] not in open_ids:
            problems.append(
                f"demo/recorded/{rid}.json, related_request.request_id: no waiting or in review request with id "
                f"{related_req['request_id']!r}"
            )
    for i, r in enumerate(reqs_file.requests):
        service = r.security_answers.ai_service if r.security_answers else None
        if service and service not in rules.service_choices():
            problems.append(
                f"{req_name}, requests[{i}].security_answers.ai_service: use one of "
                + ", ".join(rules.service_choices())
            )
    if problems:
        raise DemoDataError(problems)

    decided_security = {r.id: r.decision.checklist.security_check for r in reqs_file.requests if r.decision}
    tools = []
    for t in tools_file.tools:
        data = t.model_dump(exclude={"ready_check", "journey", "security_check"})
        # The security check comes from the decision that created the tool, when there is one.
        security = decided_security.get(t.from_request or "") or t.security_check or "not_needed"
        ready = {k: v for k, v in t.ready_check.model_dump(mode="json").items() if v not in (None, "")}
        journey = [e.model_dump(mode="json") for e in t.journey]
        tools.append(Tool(**data, owner_agreed=True, security_check=security, ready_check=ready, journey=journey))
    requests: list[Request] = []
    decisions: list[Decision] = []
    for r in reqs_file.requests:
        rec = recorded[r.id]
        data = r.model_dump(exclude={"decision", "questions", "timeline", "submitted_at", "security_answers",
                                     "needed_by"})
        answers = r.security_answers.model_dump() if r.security_answers else {}
        req = Request(
            **data,
            security_answers=answers,
            security_result=check_security(r.info, answers, rules).as_dict(),
            needed_by=[n.model_dump(mode="json") for n in r.needed_by],
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
        as_of=today,
        demo_requester=reqs_file.demo_requester,
        demo_reviewer=reqs_file.demo_reviewer,
        example_request_id=example,
    )


def check_demo_data(demo_dir: Path, rules_path: Optional[Path] = None) -> list[str]:
    try:
        rules = load_security_rules(rules_path or ROOT / "security_rules.yaml")
        load_demo_data(demo_dir, rules=rules)
    except (DemoDataError, SecurityRulesError) as exc:
        return exc.problems
    return []
