"""
memory/scoring.py — importance heuristics and retrieval ranking.

No LLM calls: everything is local regex/arithmetic so memory stays fast,
offline, and free. Scores are explainable: final rank blends semantic
similarity with recency, importance, and access frequency.
"""
from __future__ import annotations

import math
import re
from datetime import UTC, datetime

from .models import MemoryKind, MemoryRecord

# (pattern, importance, kind) — first match wins.
IMPORTANCE_TRIGGERS: list[tuple[re.Pattern, float, MemoryKind]] = [
    (re.compile(r"\bremember (this|that|it)\b", re.I), 0.90, MemoryKind.SEMANTIC),
    (re.compile(r"\bdon'?t forget\b", re.I), 0.90, MemoryKind.SEMANTIC),
    (re.compile(r"\bmy name is\b", re.I), 0.85, MemoryKind.SEMANTIC),
    (re.compile(r"\bi (am|work as a|live in|am from)\b", re.I), 0.80, MemoryKind.SEMANTIC),
    (re.compile(r"\bmy (dog|cat|wife|husband|partner|son|daughter|kid|project|company|team|boss)\b", re.I), 0.80, MemoryKind.SEMANTIC),
    (re.compile(r"\bi (prefer|like|love|hate|dislike|can'?t stand)\b", re.I), 0.75, MemoryKind.SEMANTIC),
    (re.compile(r"\b(never|don'?t) .*again\b", re.I), 0.75, MemoryKind.PROCEDURAL),
    (re.compile(r"\balways .*(format|use|prefer|start with)\b", re.I), 0.75, MemoryKind.PROCEDURAL),
    (re.compile(r"\bactually,|that'?s (not |)right|you'?re wrong|correction:", re.I), 0.70, MemoryKind.EPISODIC),
    (re.compile(r"\bno,? (i meant|that'?s not)\b", re.I), 0.70, MemoryKind.EPISODIC),
]

DEFAULT_IMPORTANCE = 0.40
RECENCY_HALFLIFE_DAYS = 30.0
DECAY_FLOOR = 0.10


def score_importance(text: str) -> tuple[float, MemoryKind]:
    """Heuristic importance + kind for a candidate memory sentence."""
    for pattern, importance, kind in IMPORTANCE_TRIGGERS:
        if pattern.search(text):
            return importance, kind
    return DEFAULT_IMPORTANCE, MemoryKind.EPISODIC


def recency_factor(last_accessed: datetime, now: datetime | None = None) -> float:
    """Exponential decay with a 30-day half-life, floored so old memories
    can still surface when highly relevant."""
    now = now or datetime.now(UTC)
    age_days = max(0.0, (now - last_accessed).total_seconds() / 86400.0)
    return max(0.2, 0.5 ** (age_days / RECENCY_HALFLIFE_DAYS))


def access_boost(access_count: int) -> float:
    """Frequently recalled memories rank slightly higher (capped)."""
    return min(1.5, 1.0 + 0.1 * max(0, access_count))


def rank_score(record: MemoryRecord, now: datetime | None = None) -> float:
    """Combined retrieval score: similarity × recency × importance × access."""
    now = now or datetime.now(UTC)
    importance = max(0.0, min(1.0, record.importance))
    return (
        record.similarity
        * (0.5 + 0.5 * recency_factor(record.last_accessed, now))
        * (0.6 + 0.4 * importance)
        * access_boost(record.access_count)
    )


def rank(records: list[MemoryRecord], now: datetime | None = None) -> list[MemoryRecord]:
    """Score in place and return best-first."""
    for record in records:
        record.score = rank_score(record, now)
    records.sort(key=lambda r: r.score, reverse=True)
    return records


def decayed_importance(record: MemoryRecord, now: datetime | None = None) -> float:
    """Importance after time-based decay (consolidation). Untouched memories
    fade 5% per consolidation pass; floor keeps them retrievable."""
    now = now or datetime.now(UTC)
    age_days = (now - record.last_accessed).total_seconds() / 86400.0
    if age_days < RECENCY_HALFLIFE_DAYS:
        return record.importance
    return max(DECAY_FLOOR, record.importance * 0.95)


def should_prune(record: MemoryRecord, now: datetime | None = None) -> bool:
    """Prune only when a memory is unimportant AND old AND never recalled."""
    now = now or datetime.now(UTC)
    age_days = (now - record.created_at).total_seconds() / 86400.0
    return record.importance < 0.15 and age_days > 90 and record.access_count == 0


def split_sentences(text: str) -> list[str]:
    """Naive sentence splitter for memory extraction (offline, no NLP deps)."""
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p.strip() for p in parts if len(p.strip()) >= 12]
