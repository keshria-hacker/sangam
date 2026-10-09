"""
memory/models.py — memory record model (MemPalace-inspired).

Three memory kinds:
- EPISODIC:   things that happened ("user corrected the deployment steps")
- SEMANTIC:   durable facts about the user ("user's dog is named Biscuit")
- PROCEDURAL: how the user likes things done ("user prefers concise answers")
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class MemoryKind(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


@dataclass
class MemoryRecord:
    id: str
    content: str
    kind: MemoryKind = MemoryKind.EPISODIC
    chat_id: str = ""
    user_id: str = ""
    importance: float = 0.4          # 0.0–1.0; drives retention + ranking
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_accessed: datetime = field(default_factory=lambda: datetime.now(UTC))
    access_count: int = 0
    # Retrieval-time only (not persisted):
    similarity: float = 0.0
    score: float = 0.0

    def to_metadata(self) -> dict:
        """ChromaDB metadata (values must be str/int/float/bool)."""
        return {
            "kind": self.kind.value,
            "chat_id": self.chat_id,
            "user_id": self.user_id,
            "importance": float(max(0.0, min(1.0, self.importance))),
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "access_count": int(self.access_count),
        }

    @classmethod
    def from_chroma(
        cls,
        id: str,
        document: str,
        metadata: dict | None,
        distance: float | None = None,
    ) -> "MemoryRecord":
        meta = metadata or {}
        kind_raw = str(meta.get("kind", "episodic"))
        try:
            kind = MemoryKind(kind_raw)
        except ValueError:
            kind = MemoryKind.EPISODIC

        def _dt(value: object, fallback: datetime) -> datetime:
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value)
                except ValueError:
                    return fallback
            return fallback

        now = datetime.now(UTC)
        record = cls(
            id=id,
            content=document or "",
            kind=kind,
            chat_id=str(meta.get("chat_id", "")),
            user_id=str(meta.get("user_id", "")),
            importance=float(meta.get("importance", 0.4)),
            created_at=_dt(meta.get("created_at"), now),
            last_accessed=_dt(meta.get("last_accessed"), now),
            access_count=int(meta.get("access_count", 0) or 0),
        )
        if distance is not None:
            # ChromaDB default space is squared L2; map to a 0..1 similarity.
            record.similarity = max(0.0, min(1.0, 1.0 - float(distance)))
        return record
