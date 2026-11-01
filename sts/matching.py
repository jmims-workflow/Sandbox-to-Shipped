"""Checking for existing tools.

Whatever produces match suggestions (Claude in live mode, recorded results or
the simple word match in demo mode), the suggestions pass through
clean_matches() so only real, usable tools ever reach the screen.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from .models import MATCHABLE_STATUSES, Tool

MAX_MATCHES = 2
RELATED_MIN_SHARED = 3
CONFIDENCE = ("close", "possible")

STOPWORDS = set(
    """
    a about after all also an and any are as at be been before but by can could do
    does each every for from get gets got has have how i if in into is it its just
    me more my need needs new of on or our out over so some than that the their them
    then there these they this to turn turns up us use used using want was we what
    when which who will with would you your tool tools help helps make makes something
    """.split()
)


def eligible_tools(inventory: Iterable[Tool]) -> list[Tool]:
    """Only tools that are approved, approved with limits or being tried."""
    return [t for t in inventory if t.status in MATCHABLE_STATUSES]


def clean_matches(raw: Iterable[Any], inventory: Iterable[Tool]) -> list[dict[str, str]]:
    """Drop unknown or retired tool ids, bad confidences and duplicates. Keep at most 2."""
    allowed = {t.id for t in eligible_tools(inventory)}
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw or []:
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        if not isinstance(item, dict):
            continue
        tool_id = str(item.get("tool_id", "")).strip()
        confidence = str(item.get("confidence", "")).strip().lower()
        reason = str(item.get("reason", "")).strip()
        if tool_id not in allowed or tool_id in seen or confidence not in CONFIDENCE:
            continue
        seen.add(tool_id)
        cleaned.append({"tool_id": tool_id, "confidence": confidence, "reason": reason})
        if len(cleaned) == MAX_MATCHES:
            break
    return cleaned


def clean_related(raw: Any, past_decisions: Iterable[dict]) -> Optional[dict[str, str]]:
    """Keep a related past decision only if its id was in the list sent. Otherwise drop it."""
    if raw is None:
        return None
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if not isinstance(raw, dict):
        return None
    request_id = str(raw.get("request_id", "")).strip()
    reason = str(raw.get("reason", "")).strip()
    if not request_id or request_id not in {str(d.get("id")) for d in past_decisions}:
        return None
    return {"request_id": request_id, "reason": reason}


def _words(text: str) -> set[str]:
    words = set()
    for w in re.findall(r"[a-z]+", (text or "").lower()):
        if len(w) < 3 or w in STOPWORDS:
            continue
        # A very light stem so "emails" matches "email" and "notes" matches "note".
        if w.endswith("ies") and len(w) > 4:
            w = w[:-3] + "y"
        elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
            w = w[:-1]
        words.add(w)
    return words


def word_overlap_matches(task: str, inventory: Iterable[Tool]) -> list[dict[str, str]]:
    """The demo's simple word match against tool names and purposes."""
    task_words = _words(task)
    if not task_words:
        return []
    scored = []
    for tool in eligible_tools(inventory):
        shared = task_words & _words(f"{tool.name} {tool.purpose}")
        if len(shared) >= 2:
            scored.append((len(shared), tool, sorted(shared)))
    scored.sort(key=lambda s: (-s[0], s[1].name))
    out = []
    for score, tool, shared in scored[:MAX_MATCHES]:
        out.append(
            {
                "tool_id": tool.id,
                "confidence": "close" if score >= 4 else "possible",
                "reason": "Shares these words with your request: " + ", ".join(shared) + ".",
            }
        )
    return out


def word_overlap_related(task: str, past_decisions: Iterable[dict]) -> Optional[dict[str, str]]:
    """The demo's simple word match against past decisions. Returns the best one, or None."""
    task_words = _words(task)
    best = None
    for d in past_decisions:
        shared = task_words & _words(f"{d.get('title', '')} {d.get('task', '')}")
        if len(shared) >= RELATED_MIN_SHARED and (best is None or len(shared) > len(best[1])):
            best = (d, sorted(shared))
    if best is None:
        return None
    d, shared = best
    words = ", ".join(shared[:-1]) + " and " + shared[-1]
    return {"request_id": str(d["id"]), "reason": f"It was about a similar task: it shares the words {words} with yours."}
