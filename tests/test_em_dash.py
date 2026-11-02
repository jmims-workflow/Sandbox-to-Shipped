"""Fail if any text file in the repo contains an em dash."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EM_DASH = chr(0x2014)
SKIP_DIRS = {".git", "data", "__pycache__", ".pytest_cache", ".venv", "node_modules"}
BINARY = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pyc", ".db", ".woff", ".woff2", ".mp4", ".webm"}


def test_no_em_dashes_anywhere():
    found = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix in BINARY:
            continue
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in path.relative_to(ROOT).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if EM_DASH in line:
                found.append(f"{path.relative_to(ROOT)}:{n}")
    assert not found, "Em dashes found: " + ", ".join(found)
