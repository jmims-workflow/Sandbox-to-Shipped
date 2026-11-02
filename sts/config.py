"""Settings read from the environment. The API key never leaves the server."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "claude-sonnet-5-5"
MODES = ("demo", "live", "preview")


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "").strip())
    except ValueError:
        return default
    return value if value >= 0 else default


@dataclass
class Settings:
    requested_mode: str = "demo"
    api_key: str = field(default="", repr=False)
    model: str = DEFAULT_MODEL
    data_dir: Path = Path("./data")
    demo_dir: Path = ROOT / "demo"
    security_rules_path: Path = ROOT / "security_rules.yaml"
    # How many working days reviewers usually take to answer.
    review_days: int = 5
    # How many tools can be in pilot at once.
    pilot_slots: int = 3
    # Live preview limits on Claude calls.
    daily_claude_calls: int = 100
    visitor_claude_calls_per_hour: int = 10
    # Development only: live mode with the stand-in Claude client in sts/fake_claude.py, so a run
    # (such as the recorded walkthrough) is repeatable and needs no key. Refused in demo and
    # preview, and refused when a real key is present.
    fake_claude: bool = False

    @property
    def mode(self) -> str:
        """The mode the app actually runs in."""
        if self.requested_mode in ("live", "preview") and self.api_key:
            return self.requested_mode
        if self.requested_mode == "live" and self.fake_claude:
            return "live"
        return "demo"

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    @property
    def is_preview(self) -> bool:
        return self.mode == "preview"

    @property
    def fell_back(self) -> bool:
        """Live or preview was asked for but there is no key, so we run the demo."""
        return self.requested_mode in ("live", "preview") and not self.api_key and self.mode == "demo"

    def startup_problem(self) -> str | None:
        """A setting combination the app refuses to start with, as a message saying why."""
        if not self.fake_claude:
            return None
        if self.requested_mode != "live":
            return (f"STS_FAKE_CLAUDE is for development in live mode only, and STS_MODE is {self.requested_mode}. "
                    "Unset STS_FAKE_CLAUDE, or set STS_MODE=live.")
        if self.api_key:
            return ("STS_FAKE_CLAUDE can't be used while ANTHROPIC_API_KEY is set, so a real key is never "
                    "mixed with the stand-in. Unset one of them.")
        return None

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / "sts.db"

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.environ.get("STS_MODE", "demo").strip().lower()
        if mode not in MODES:
            mode = "demo"
        return cls(
            requested_mode=mode,
            api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
            model=os.environ.get("STS_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            data_dir=Path(os.environ.get("DATA_DIR", "./data")),
            review_days=_int_env("STS_REVIEW_DAYS", 5) or 5,
            pilot_slots=_int_env("STS_PILOT_SLOTS", 3) or 3,
            daily_claude_calls=_int_env("STS_DAILY_CLAUDE_CALLS", 100),
            visitor_claude_calls_per_hour=_int_env("STS_VISITOR_CLAUDE_CALLS_PER_HOUR", 10),
            fake_claude=os.environ.get("STS_FAKE_CLAUDE", "").strip().lower() in ("1", "true", "yes"),
        )


class StartupError(RuntimeError):
    """The settings can't be used together. The message says why."""
