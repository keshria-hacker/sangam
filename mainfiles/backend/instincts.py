"""
Agent instincts — learned patterns from past sessions (ECC-style, Sangam-native).

Instincts are small, reusable lessons like "run pytest after editing Python"
or "check for SQL injection in raw queries". Each has a confidence score
that rises when the pattern helps and falls when it doesn't.

Stored in ``mainfiles/instincts.json`` (gitignored). Injected into the
Code Agent's prompt when relevant to the task.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

_PATH = Path(__file__).resolve().parent / "instincts.json"
_lock = threading.RLock()

# Seed instincts — generally useful coding patterns
_SEED = [
    {"pattern": "After editing Python files, run the relevant tests before declaring done.",
     "tags": ["python", "testing"], "confidence": 0.9},
    {"pattern": "When a bash command fails, read stderr fully before retrying with a fix.",
     "tags": ["bash", "debugging"], "confidence": 0.9},
    {"pattern": "List files and read the relevant code before making changes — never edit blind.",
     "tags": ["planning"], "confidence": 0.95},
    {"pattern": "For web prototypes, keep everything in one self-contained index.html.",
     "tags": ["html", "design"], "confidence": 0.85},
    {"pattern": "Validate user input at boundaries; never trust raw strings in SQL or shell commands.",
     "tags": ["security"], "confidence": 0.9},
]


def _read() -> list[dict]:
    try:
        data = json.loads(_PATH.read_text())
        if isinstance(data, list):
            return data
    except (OSError, ValueError):
        pass
    return [dict(s) for s in _SEED]


def _write(items: list[dict]) -> None:
    _PATH.write_text(json.dumps(items, indent=2))


def get_relevant_instincts(task: str, limit: int = 4) -> list[str]:
    """Return instinct patterns relevant to the task text."""
    task_l = task.lower()
    items = _read()
    scored = []
    for it in items:
        tags = it.get("tags", [])
        hits = sum(1 for t in tags if t in task_l)
        # Always include high-confidence general instincts
        score = hits * 2 + it.get("confidence", 0.5)
        if hits or "planning" in tags or "debugging" in tags:
            scored.append((score, it["pattern"]))
    scored.sort(reverse=True)
    return [p for _, p in scored[:limit]]


def record_instinct(pattern: str, tags: list[str]) -> None:
    """Add a new instinct (e.g., learned from a session)."""
    with _lock:
        items = _read()
        if any(i["pattern"] == pattern for i in items):
            return
        items.append({"pattern": pattern, "tags": tags, "confidence": 0.6})
        _write(items)


def reinforce_instinct(pattern: str, helped: bool) -> None:
    """Adjust confidence based on whether the instinct helped."""
    with _lock:
        items = _read()
        for it in items:
            if it["pattern"] == pattern:
                delta = 0.1 if helped else -0.15
                it["confidence"] = max(0.1, min(1.0, it.get("confidence", 0.5) + delta))
        _write(items)
