"""
memory/transcripts.py — Batch 4: verbatim transcript storage (MemPalace-style).

Unlike extracted memories (capped at 2000 chars in store.py), a
transcript keeps the FULL message text — no cap. Transcripts are the
verbatim record; extraction reads from them but never replaces them.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class MemoryTranscript(Base):
    """One verbatim chat message, full text, newest-first listing."""
    __tablename__ = "memory_transcripts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    chat_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))  # "user" | "assistant"
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


def transcript_out(row: MemoryTranscript) -> dict:
    return {
        "id": row.id, "chat_id": row.chat_id, "role": row.role,
        "text": row.text,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def save_transcript(
    db: AsyncSession, user_id: str, chat_id: str, role: str, text: str
) -> MemoryTranscript:
    row = MemoryTranscript(
        id=f"tr-{uuid.uuid4().hex[:12]}", user_id=user_id,
        chat_id=chat_id, role=role, text=text)
    db.add(row)
    await db.flush()
    return row


async def list_transcripts(
    db: AsyncSession, user_id: str, chat_id: str = "", limit: int = 50
) -> list[MemoryTranscript]:
    stmt = select(MemoryTranscript).where(MemoryTranscript.user_id == user_id)
    if chat_id:
        stmt = stmt.where(MemoryTranscript.chat_id == chat_id)
    stmt = stmt.order_by(desc(MemoryTranscript.created_at), desc(MemoryTranscript.id))
    stmt = stmt.limit(min(max(1, limit), 200))
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)
