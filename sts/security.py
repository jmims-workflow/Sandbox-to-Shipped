"""The automatic security check, set by security.

The security team owns security_rules.yaml. Plain code here applies those rules
to the answers on a request. Claude is not involved in this check, and the early
warnings on Request a tool come from these rules too, never from Claude.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from .models import INFO_KINDS

# The three questions for security, in the order they are asked.
Q_SENDS = "sends_without_check"
Q_KEEPS = "keeps_elsewhere"
Q_SERVICE = "ai_service"
QUESTIONS: dict[str, str] = {
    Q_SENDS: "Would it send anything to customers or the public without a person checking first?",
    Q_KEEPS: "Would it keep information anywhere other than tools Northstar already approved?",
    Q_SERVICE: "Which AI service would it use?",
}
YES_NO_NOT_SURE: dict[str, str] = {"yes": "Yes", "no": "No", "not_sure": "Not sure"}
SOMETHING_ELSE = "something_else"
NOT_SURE = "not_sure"
OTHER_SERVICES: dict[str, str] = {SOMETHING_ELSE: "Something else", NOT_SURE: "Not sure"}

RESULTS: dict[str, str] = {
    "not_needed": "Security screening: not needed",
    "passed": "Security screening: passed automatically against security's rules",
    "person": "Security screening: a person from security will review this",
}
# The reviewer checklist value each result fills in.
CHECKLIST_VALUE = {"not_needed": "not_needed", "passed": "passed", "person": "needed"}

LEVELS: dict[str, str] = {
    "none": "No security screening",
    "automatic": "Checked automatically against security's rules",
    "person": "Always reviewed by a person on the security team",
}

WARN_SENDS = (
    "Heads up: Northstar doesn't approve tools that send to customers on their own. A version that drafts "
    "for a person to check and send is much more likely to be approved."
)
WARN_SENSITIVE = (
    "Requests with sensitive personal information always get a review from security, so expect this one "
    "to take longer."
)


# ---- The rules file ------------------------------------------------------------------


class Service(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("each service needs an id")
        if v in OTHER_SERVICES:
            raise ValueError(f"{v!r} is kept for the form's own choices; pick another id")
        return v


class SecurityRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved_services: list[Service]
    information: dict[str, Literal["none", "automatic", "person"]]

    @field_validator("approved_services")
    @classmethod
    def _services(cls, v: list[Service]) -> list[Service]:
        if not v:
            raise ValueError("list at least one approved AI service")
        ids = [s.id for s in v]
        if len(set(ids)) != len(ids):
            raise ValueError("two services share the same id")
        return v

    @field_validator("information", mode="before")
    @classmethod
    def _kinds(cls, v: Any) -> Any:
        if not isinstance(v, dict):
            return v
        unknown = [k for k in v if k not in INFO_KINDS]
        if unknown:
            raise ValueError(
                f"{', '.join(map(str, unknown))} is not an information kind. Use: {', '.join(INFO_KINDS)}"
            )
        missing = [k for k in INFO_KINDS if k not in v]
        if missing:
            raise ValueError(
                "add a rule (none, automatic or person) for: "
                + ", ".join(f"{k} ({INFO_KINDS[k]})" for k in missing)
            )
        return v

    @model_validator(mode="after")
    def _ordered(self):
        self.information = {k: self.information[k] for k in INFO_KINDS}
        return self

    @property
    def service_names(self) -> dict[str, str]:
        return {s.id: s.name for s in self.approved_services}

    def service_choices(self) -> dict[str, str]:
        """For the form's select: the approved services, then Something else and Not sure."""
        return {**self.service_names, **OTHER_SERVICES}


class SecurityRulesError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def load_security_rules(path: Path) -> SecurityRules:
    """Read and check the rules file. Problems name the file and the field to fix."""
    path = Path(path)
    name = path.name
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raise SecurityRulesError([f"{name}: file not found at {path}"])
    except yaml.YAMLError as exc:
        raise SecurityRulesError([f"{name}: not valid YAML ({exc.__class__.__name__})"])
    try:
        return SecurityRules.model_validate(raw)
    except ValidationError as exc:
        problems = []
        for e in exc.errors():
            loc = ""
            for part in e["loc"]:
                loc += f"[{part}]" if isinstance(part, int) else (f".{part}" if loc else str(part))
            msg = e["msg"].removeprefix("Value error, ")
            if e["type"] == "missing":
                msg = "this is required"
            elif e["type"] == "extra_forbidden":
                msg = "not a setting this file uses (check the spelling)"
            elif e["type"] == "literal_error":
                msg = "use none, automatic or person"
            problems.append(f"{name}, {loc or 'file'}: {msg}")
        raise SecurityRulesError(problems)


def check_security_rules(path: Path) -> list[str]:
    try:
        load_security_rules(path)
    except SecurityRulesError as exc:
        return exc.problems
    return []


# ---- The check -----------------------------------------------------------------------


@dataclass
class SecurityResult:
    result: str  # not_needed, passed or person
    reasons: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return RESULTS[self.result]

    def as_dict(self) -> dict[str, Any]:
        return {"result": self.result, "reasons": list(self.reasons)}


def needs_questions(info: list[str], rules: SecurityRules) -> bool:
    """The three questions are asked when the request uses anything other than public information."""
    return any(i != "public_only" for i in info)


def answer_text(question: str, value: str, rules: SecurityRules) -> str:
    if question == Q_SERVICE:
        return rules.service_choices().get(value, "Not answered")
    return YES_NO_NOT_SURE.get(value, "Not answered")


def _answered(question: str, value: str, rules: SecurityRules) -> str:
    return f"“{QUESTIONS[question]}” was answered {answer_text(question, value, rules)}."


def check_security(info: list[str], answers: Optional[dict], rules: SecurityRules) -> SecurityResult:
    """Apply security's rules to a request.

    - Only information with no check (for Northstar, public only): not needed.
    - Any information security always reviews (sensitive personal): a person, whatever the answers.
    - Otherwise it passes automatically only when the first two answers are No and the AI service is
      an approved one. Any Yes, Not sure, missing answer or unapproved service sends it to a person,
      and the reasons name each answer that did.
    """
    answers = answers or {}
    levels = {i: rules.information.get(i, "person") for i in info if i in INFO_KINDS}
    if not levels or all(level == "none" for level in levels.values()):
        return SecurityResult("not_needed")
    person_kinds = [i for i, level in levels.items() if level == "person"]
    if person_kinds:
        names = ", ".join(INFO_KINDS[i].split(" (")[0].lower() for i in person_kinds)
        return SecurityResult(
            "person", [f"It uses {names}, which always goes to a person on the security team."]
        )
    reasons = []
    for q in (Q_SENDS, Q_KEEPS):
        value = str(answers.get(q) or "")
        if value != "no":
            reasons.append(_answered(q, value, rules) if value else f"“{QUESTIONS[q]}” wasn't answered.")
    service = str(answers.get(Q_SERVICE) or "")
    if service not in rules.service_names:
        if not service:
            reasons.append(f"“{QUESTIONS[Q_SERVICE]}” wasn't answered.")
        elif service in OTHER_SERVICES:
            reasons.append(_answered(Q_SERVICE, service, rules))
        else:
            reasons.append(f"“{QUESTIONS[Q_SERVICE]}” named a service that isn't on security's approved list.")
    if reasons:
        return SecurityResult("person", reasons)
    return SecurityResult("passed")


def clean_answers(form: Any, info: list[str], rules: SecurityRules) -> dict[str, str]:
    """Keep only known answer values. No answers are kept for public-only requests."""
    if not needs_questions(info, rules):
        return {}
    out = {}
    for q in (Q_SENDS, Q_KEEPS):
        value = str(form.get(q) or "").strip()
        out[q] = value if value in YES_NO_NOT_SURE else ""
    service = str(form.get(Q_SERVICE) or "").strip()
    out[Q_SERVICE] = service if service in rules.service_choices() else ""
    return out


def answer_errors(info: list[str], answers: dict, rules: SecurityRules) -> dict[str, str]:
    if not needs_questions(info, rules):
        return {}
    errors = {}
    for q in (Q_SENDS, Q_KEEPS):
        if not answers.get(q):
            errors[q] = "Answer this question for security. “Not sure” is fine."
    if not answers.get(Q_SERVICE):
        errors[Q_SERVICE] = "Choose the AI service it would use. “Not sure” is fine."
    return errors


def early_warnings(info: list[str], answers: Optional[dict]) -> dict[str, str]:
    """Plain warnings shown next to the answers that trigger them. They never block submitting."""
    answers = answers or {}
    warnings = {}
    if "sensitive_personal" in info:
        warnings["info"] = WARN_SENSITIVE
    if answers.get(Q_SENDS) == "yes" and any(i != "public_only" for i in info):
        warnings[Q_SENDS] = WARN_SENDS
    return warnings


# What a requester sees about each question when it sent the request to a person.
SHORT_QUESTIONS = {
    Q_SENDS: "to sending to customers without a person checking",
    Q_KEEPS: "to keeping information outside approved tools",
    Q_SERVICE: "about the AI service",
}


def requester_line(info: list[str], answers: Optional[dict], rules: SecurityRules) -> str:
    """The security step on "Here's what happens next", in the requester's words.

    Built from the same rules as check_security(), in code. Claude is not involved.
    """
    result = check_security(info, answers, rules).result
    if result == "not_needed":
        return "Not needed. It only uses public information."
    if result == "passed":
        return "Passed automatically against security's rules."
    answers = answers or {}
    levels = {i: rules.information.get(i, "person") for i in info if i in INFO_KINDS}
    person_kinds = [i for i, level in levels.items() if level == "person"]
    if person_kinds:
        names = ", ".join(INFO_KINDS[i].split(" (")[0].lower() for i in person_kinds)
        because = [f"it uses {names}"]
    else:
        because = []
        for q in (Q_SENDS, Q_KEEPS, Q_SERVICE):
            value = str(answers.get(q) or "")
            if q != Q_SERVICE and value == "no":
                continue
            if q == Q_SERVICE and value in rules.service_names:
                continue
            if not value:
                because.append(f"the question about {SHORT_QUESTIONS[q].split(' ', 1)[1]} wasn't answered")
            elif q == Q_SERVICE and value not in OTHER_SERVICES:
                because.append("the AI service isn't on security's approved list")
            else:
                because.append(f"you answered {answer_text(q, value, rules)} {SHORT_QUESTIONS[q]}")
    joined = because[0] if len(because) == 1 else ", ".join(because[:-1]) + " and " + because[-1]
    return f"A person from security will review this, because {joined}."
