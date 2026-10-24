"""
memory/graph.py — Batch 4: entity + temporal graph (MemPalace-style).

Tables live here (not models.py), following the Batch 2 precedent in
security_guardrails.py: importing a route module registers these
tables with Base.metadata.

Validity windows, not overwrites: adding a relation with the same
(subject, predicate) and a different object closes the old open row
(valid_to=now, superseded_by=new id) and opens a new row. ``valid_to``
NULL means the relation is currently true. Timelines therefore show
open + closed rows ordered by valid_from — "what changed" queries
work without losing history.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class MemoryEntity(Base):
    """A named thing seen in memories / extractions."""
    __tablename__ = "memory_entities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(64), default="other")
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=_now)


class MemoryRelation(Base):
    """A (subject, predicate, object) fact with a validity window."""
    __tablename__ = "memory_relations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    subject: Mapped[str] = mapped_column(String(200), index=True)
    predicate: Mapped[str] = mapped_column(String(128), index=True)
    object: Mapped[str] = mapped_column(String(200))
    valid_from: Mapped[datetime] = mapped_column(DateTime, default=_now)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    superseded_by: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)


def entity_out(row: MemoryEntity) -> dict:
    return {
        "id": row.id, "name": row.name, "kind": row.kind,
        "first_seen": row.first_seen.isoformat() if row.first_seen else None,
        "last_seen": row.last_seen.isoformat() if row.last_seen else None,
    }


def relation_out(row: MemoryRelation) -> dict:
    return {
        "id": row.id, "subject": row.subject, "predicate": row.predicate,
        "object": row.object,
        "valid_from": row.valid_from.isoformat() if row.valid_from else None,
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "superseded_by": row.superseded_by,
        "open": row.valid_to is None,
    }


async def upsert_entity(
    db: AsyncSession, user_id: str, name: str, kind: str = "other"
) -> MemoryEntity:
    """Create the entity or refresh last_seen (names match exactly)."""
    name = (name or "").strip()
    row = (await db.execute(
        select(MemoryEntity).where(
            MemoryEntity.user_id == user_id, MemoryEntity.name == name)
    )).scalars().first()
    if row is None:
        row = MemoryEntity(id=_new_id("ent"), user_id=user_id, name=name,
                           kind=kind or "other")
        db.add(row)
    else:
        row.last_seen = _now()
        if kind and row.kind == "other":
            row.kind = kind
    await db.flush()
    return row


async def add_relation(
    db: AsyncSession, user_id: str, subject: str, predicate: str, object_: str
) -> MemoryRelation:
    """Add a relation, closing any open row with the same (subject, predicate)
    but a different object. Re-adding the identical triple is a no-op
    (the existing open row is returned, no duplicate window)."""
    subject, predicate, object_ = subject.strip(), predicate.strip(), object_.strip()
    existing = (await db.execute(
        select(MemoryRelation).where(
            MemoryRelation.user_id == user_id,
            MemoryRelation.subject == subject,
            MemoryRelation.predicate == predicate,
            MemoryRelation.valid_to.is_(None))
    )).scalars().all()
    for row in existing:
        if row.object == object_:
            return row
    new_id = _new_id("rel")
    now = _now()
    for row in existing:
        row.valid_to = now
        row.superseded_by = new_id
    row = MemoryRelation(id=new_id, user_id=user_id, subject=subject,
                         predicate=predicate, object=object_, valid_from=now)
    db.add(row)
    await db.flush()
    return row


async def entity_timeline(
    db: AsyncSession, user_id: str, name: str
) -> list[MemoryRelation]:
    """Open + closed relations mentioning ``name`` as subject or object,
    oldest first (valid_from order)."""
    rows = (await db.execute(
        select(MemoryRelation).where(
            MemoryRelation.user_id == user_id,
            (MemoryRelation.subject == name) | (MemoryRelation.object == name))
        .order_by(MemoryRelation.valid_from, MemoryRelation.id)
    )).scalars().all()
    return list(rows)


async def list_entities(db: AsyncSession, user_id: str) -> list[MemoryEntity]:
    rows = (await db.execute(
        select(MemoryEntity).where(MemoryEntity.user_id == user_id)
        .order_by(desc(MemoryEntity.last_seen))
    )).scalars().all()
    return list(rows)
