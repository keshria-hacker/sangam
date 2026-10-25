"""
memory/graph.py — Batch 4: entity + temporal graph (MemPalace-style),
plus Wave-2 deep-knowledge hardening.

Validity windows, not overwrites: adding a relation with the same
(subject, predicate) and a different object closes the old open row
(valid_to=now, superseded_by=new id) and opens a new row. ``valid_to``
NULL means the relation is currently true. Timelines therefore show
open + closed rows ordered by valid_from — "what changed" queries
work without losing history.

Wave-2 hardening (MemPalace + Hindsight ports, algorithms only):

* Predicate normalization (``"Lives In"`` -> ``"lives_in"``) so the
  same relation spelled differently does not fork into parallel rows.
* Entity canonicalization via an alias table: ``upsert_entity``
  resolves case-insensitive names and registered aliases to one
  canonical entity row; relation subjects/objects are rewritten to
  the canonical display name when a match exists.
* ``confidence`` + ``source_ref`` columns on every relation row.
* As-of queries with half-open intervals: a row is true at instant
  ``t`` iff ``valid_from <= t < valid_to`` (or ``valid_to`` is NULL).
  An inverted interval (``valid_to < valid_from``) is rejected.
* Pre-write contradiction flagging: ``flag_contradiction`` surfaces
  "previously X, now Y" before a write; ``supersede`` performs the
  close-and-reopen at one shared instant and returns both rows.

Tables live here (not models.py), following the Batch 2 precedent in
security_guardrails.py: importing a route module registers these
tables with Base.metadata.

Honest limits:
* Alias matching is string-based (case/whitespace + explicit aliases);
  it is not embedding-based entity resolution.
* New columns on an already-created SQLite database need the
  ``_add_missing_columns`` treatment in database.py (not edited by
  this worker); fresh databases get them from create_all.
* The unified-graph file (knowledge_graph.py) is owned by another
  worker and is NOT touched here; wiring ``confidence``/``source_ref``
  and as-of filtering into its output is logged for the parent.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def normalize_predicate(predicate: str) -> str:
    """Canonical predicate form: trimmed, lowercased, runs of
    non-alphanumerics collapsed to a single underscore."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", (predicate or "").strip().lower())
    return cleaned.strip("_")


def canonical_name(name: str) -> str:
    """Display-name canonicalization: trim + collapse inner
    whitespace. Case is preserved for display; matching is
    case-insensitive (see ``_find_entity``)."""
    return re.sub(r"\s+", " ", (name or "").strip())


def _alias_norm(name: str) -> str:
    return canonical_name(name).lower()


class MemoryEntity(Base):
    """A named thing seen in memories / extractions."""
    __tablename__ = "memory_entities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(64), default="other")
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=_now)


class MemoryEntityAlias(Base):
    """Alias -> canonical entity. ``alias_norm`` is the lowercased,
    whitespace-collapsed alias; lookups never depend on case."""
    __tablename__ = "memory_entity_aliases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str] = mapped_column(String(32), ForeignKey("memory_entities.id"), index=True)
    alias: Mapped[str] = mapped_column(String(200))
    alias_norm: Mapped[str] = mapped_column(String(200), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


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
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    source_ref: Mapped[str] = mapped_column(String(512), default="")


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
        "confidence": row.confidence if row.confidence is not None else 1.0,
        "source_ref": row.source_ref or "",
    }


def decayed_confidence(confidence: float, age_days: float,
                       half_life_days: float = 90.0) -> float:
    """Batch 9 (graphify/shannon narrow gap): edge confidence decay.
    A relation's confidence halves every ``half_life_days`` of age
    (exponential decay, floored at 0.05 so old edges fade but never
    vanish silently). Pure function — callers decide whether the
    decayed or the stored value is displayed; nothing here rewrites
    stored rows."""
    import math

    base = max(0.0, min(1.0, float(confidence)))
    if age_days <= 0 or half_life_days <= 0:
        return base
    return max(0.05, base * (0.5 ** (age_days / half_life_days)))


def _check_interval(valid_from: datetime | None, valid_to: datetime | None) -> None:
    """Inverted-interval guard: a window that ends before it starts
    can never be true under half-open semantics, so reject it
    instead of storing a row as-of queries can never return.
    SQLite returns naive datetimes, so both sides are coerced to
    aware UTC before comparing (naive reads are UTC by storage)."""
    if valid_from is not None and valid_to is not None:
        if _as_aware(valid_to) < _as_aware(valid_from):
            raise ValueError("Inverted validity interval: valid_to is before valid_from")


def _as_aware(instant: datetime) -> datetime:
    if instant.tzinfo is None:
        return instant.replace(tzinfo=UTC)
    return instant


async def _find_entity(db: AsyncSession, user_id: str, name: str) -> MemoryEntity | None:
    """Exact name, then case-insensitive name, then alias table."""
    norm = _alias_norm(name)
    if not norm:
        return None
    row = (await db.execute(
        select(MemoryEntity).where(
            MemoryEntity.user_id == user_id, MemoryEntity.name == canonical_name(name))
    )).scalars().first()
    if row is not None:
        return row
    row = (await db.execute(
        select(MemoryEntity).where(
            MemoryEntity.user_id == user_id,
            func.lower(MemoryEntity.name) == norm)
    )).scalars().first()
    if row is not None:
        return row
    alias = (await db.execute(
        select(MemoryEntityAlias).where(
            MemoryEntityAlias.user_id == user_id,
            MemoryEntityAlias.alias_norm == norm)
    )).scalars().first()
    if alias is not None:
        return await db.get(MemoryEntity, alias.entity_id)
    return None


async def add_alias(
    db: AsyncSession, user_id: str, entity_id: str, alias: str
) -> MemoryEntityAlias:
    """Register ``alias`` as another name for an existing entity.
    Registering the entity's own canonical name is a no-op."""
    entity = await db.get(MemoryEntity, entity_id)
    if entity is None or entity.user_id != user_id:
        raise ValueError("Entity not found")
    norm = _alias_norm(alias)
    if not norm or norm == _alias_norm(entity.name):
        raise ValueError("Alias matches the entity's own name")
    existing = (await db.execute(
        select(MemoryEntityAlias).where(
            MemoryEntityAlias.user_id == user_id,
            MemoryEntityAlias.alias_norm == norm)
    )).scalars().first()
    if existing is not None:
        return existing
    row = MemoryEntityAlias(id=_new_id("als"), user_id=user_id,
                            entity_id=entity.id, alias=canonical_name(alias),
                            alias_norm=norm)
    db.add(row)
    await db.flush()
    return row


async def list_aliases(db: AsyncSession, user_id: str, entity_id: str) -> list[MemoryEntityAlias]:
    rows = (await db.execute(
        select(MemoryEntityAlias).where(
            MemoryEntityAlias.user_id == user_id,
            MemoryEntityAlias.entity_id == entity_id)
        .order_by(MemoryEntityAlias.alias)
    )).scalars().all()
    return list(rows)


async def upsert_entity(
    db: AsyncSession, user_id: str, name: str, kind: str = "other"
) -> MemoryEntity:
    """Create the entity or refresh last_seen. Names match via the
    alias table (case-insensitive) before a new row is created, so
    "Ada Lovelace", "ada lovelace" and a registered alias like "Ada"
    all resolve to one canonical row."""
    name = canonical_name(name)
    row = await _find_entity(db, user_id, name)
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


async def _canonical_side(db: AsyncSession, user_id: str, value: str) -> str:
    """Rewrite a subject/object string to its canonical entity name
    when an entity/alias match exists; otherwise keep it verbatim."""
    entity = await _find_entity(db, user_id, value)
    return entity.name if entity is not None else canonical_name(value)


async def _open_relations(
    db: AsyncSession, user_id: str, subject: str, predicate: str,
) -> list[MemoryRelation]:
    rows = (await db.execute(
        select(MemoryRelation).where(
            MemoryRelation.user_id == user_id,
            MemoryRelation.subject == subject,
            MemoryRelation.predicate == predicate,
            MemoryRelation.valid_to.is_(None))
    )).scalars().all()
    return list(rows)


async def add_relation(
    db: AsyncSession, user_id: str, subject: str, predicate: str, object_: str,
    confidence: float | None = None, source_ref: str = "",
) -> MemoryRelation:
    """Add a relation, closing any open row with the same (subject,
    predicate) but a different object. Re-adding the identical triple
    is a no-op (the existing open row is returned, no duplicate
    window). Predicates are normalized; subjects/objects are
    canonicalized through the alias table when a match exists."""
    subject = await _canonical_side(db, user_id, subject)
    object_ = await _canonical_side(db, user_id, object_)
    predicate = normalize_predicate(predicate)
    existing = await _open_relations(db, user_id, subject, predicate)
    for row in existing:
        if row.object == object_:
            return row
    new_id = _new_id("rel")
    now = _now()
    for row in existing:
        _check_interval(row.valid_from, now)
        row.valid_to = now
        row.superseded_by = new_id
    row = MemoryRelation(id=new_id, user_id=user_id, subject=subject,
                         predicate=predicate, object=object_, valid_from=now,
                         confidence=1.0 if confidence is None else float(confidence),
                         source_ref=source_ref or "")
    db.add(row)
    await db.flush()
    return row


async def flag_contradiction(
    db: AsyncSession, user_id: str, subject: str, predicate: str, object_: str,
) -> dict | None:
    """Pre-write check: if an open triple with the same (subject,
    predicate) holds a different object, return the "previously X,
    now Y" notice instead of letting the contradiction coexist
    silently. Returns None when there is nothing to contradict."""
    subject = await _canonical_side(db, user_id, subject)
    predicate = normalize_predicate(predicate)
    object_ = canonical_name(object_)
    for row in await _open_relations(db, user_id, subject, predicate):
        if row.object != object_:
            return {
                "subject": subject, "predicate": predicate,
                "previously": row.object, "now": object_,
                "previous_relation_id": row.id,
                "message": (f"previously {row.object}, now {object_} "
                            f"({subject} {predicate})"),
            }
    return None


async def supersede(
    db: AsyncSession, user_id: str, subject: str, predicate: str, object_: str,
    confidence: float | None = None, source_ref: str = "",
) -> tuple[MemoryRelation | None, MemoryRelation]:
    """Atomic close-and-reopen at one shared instant (MemPalace
    ``supersede()``): the old open triple is closed and the new one
    opened at the same ``now``, so as-of queries return only the
    successor at and after that instant. Returns (old, new)."""
    subject = await _canonical_side(db, user_id, subject)
    predicate = normalize_predicate(predicate)
    object_ = await _canonical_side(db, user_id, object_)
    existing = await _open_relations(db, user_id, subject, predicate)
    old = next((r for r in existing if r.object != object_), None)
    if old is None:
        same = next((r for r in existing if r.object == object_), None)
        if same is not None:
            return None, same
    new_id = _new_id("rel")
    now = _now()
    for row in existing:
        _check_interval(row.valid_from, now)
        row.valid_to = now
        row.superseded_by = new_id
    row = MemoryRelation(id=new_id, user_id=user_id, subject=subject,
                         predicate=predicate, object=object_, valid_from=now,
                         confidence=1.0 if confidence is None else float(confidence),
                         source_ref=source_ref or "")
    db.add(row)
    await db.flush()
    return old, row


async def query_as_of(
    db: AsyncSession, user_id: str, as_of: datetime,
    subject: str | None = None, predicate: str | None = None,
) -> list[MemoryRelation]:
    """Relations true at ``as_of`` under half-open intervals:
    ``valid_from <= as_of < valid_to`` (NULL ``valid_to`` = still
    true). Naive datetimes are read as UTC. The SQL comparison uses
    naive UTC because SQLite stores datetimes without tzinfo — an
    aware parameter would compare as a differently-shaped string."""
    instant = _as_aware(as_of).replace(tzinfo=None)
    stmt = select(MemoryRelation).where(
        MemoryRelation.user_id == user_id,
        MemoryRelation.valid_from <= instant,
        (MemoryRelation.valid_to.is_(None)) | (MemoryRelation.valid_to > instant),
    )
    if subject is not None:
        stmt = stmt.where(MemoryRelation.subject == await _canonical_side(db, user_id, subject))
    if predicate is not None:
        stmt = stmt.where(MemoryRelation.predicate == normalize_predicate(predicate))
    rows = (await db.execute(
        stmt.order_by(MemoryRelation.valid_from, MemoryRelation.id)
    )).scalars().all()
    return list(rows)


async def entity_timeline(
    db: AsyncSession, user_id: str, name: str,
    as_of: datetime | None = None,
) -> list[MemoryRelation]:
    """Open + closed relations mentioning ``name`` as subject or
    object, oldest first. With ``as_of``, only the relations true at
    that instant are returned (half-open intervals)."""
    name = await _canonical_side(db, user_id, name)
    stmt = select(MemoryRelation).where(
        MemoryRelation.user_id == user_id,
        (MemoryRelation.subject == name) | (MemoryRelation.object == name))
    if as_of is not None:
        # Naive UTC for the SQL comparison (see query_as_of).
        instant = _as_aware(as_of).replace(tzinfo=None)
        stmt = stmt.where(
            MemoryRelation.valid_from <= instant,
            (MemoryRelation.valid_to.is_(None)) | (MemoryRelation.valid_to > instant),
        )
    rows = (await db.execute(
        stmt.order_by(MemoryRelation.valid_from, MemoryRelation.id)
    )).scalars().all()
    return list(rows)


async def list_entities(db: AsyncSession, user_id: str) -> list[MemoryEntity]:
    rows = (await db.execute(
        select(MemoryEntity).where(MemoryEntity.user_id == user_id)
        .order_by(desc(MemoryEntity.last_seen))
    )).scalars().all()
    return list(rows)
