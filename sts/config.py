"""Settings read from the environment. The API key never leaves the server."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "claude-sonnet-5-5"


@dataclass
class Settings:
    requested_mode: str = "demo"
    api_key: str = field(default="", repr=False)
    model: str = DEFAULT_MODEL
    data_dir: Path = Path("./data")
    demo_dir: Path = ROOT / "demo"

    @property
    def mode(self) -> str:
        """The mode the app actually runs in."""
        if self.requested_mode == "live" and self.api_key:
            return "live"
        return "demo"

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    @property
    def fell_back(self) -> bool:
        """Live was asked for but there is no key, so we run the demo."""
        return self.requested_mode == "live" and not self.api_key

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / "sts.db"

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.environ.get("STS_MODE", "demo").strip().lower()
        if mode not in ("demo", "live"):
            mode = "demo"
        return cls(
            requested_mode=mode,
            api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip(),
            model=os.environ.get("STS_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
            data_dir=Path(os.environ.get("DATA_DIR", "./data")),
        )
