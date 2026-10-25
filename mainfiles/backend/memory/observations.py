"""
memory/observations.py — Batch 9: observation ledger (hindsight-inspired,
Sangam-native; NOT a copy of hindsight's closed engine).

An Observation is a consolidated belief minted from evidence, not a
chat line:

- ``claim`` — one durable statement (fact / decision / preference /
  correction), normalized for dedup.
- ``evidence`` — exact quotes + source ids (memory / document / code
  location). Quotes are stored verbatim; refinement never rewrites
  history, it appends to ``refinement_history``.
- ``proof_count`` — how many distinct evidence items support it.
  Supporting evidence strengthens it; contradicting evidence WEAKENS
  it (strength floor 0.05) without deleting history — a correction is
  a new observation that supersedes the old one, never a silent edit.
- ``strength`` — 0.0–1.0 confidence, moved only by refine/supersede.
- ``expires_at`` / ``superseded_by`` — temporal close-out, mirroring
  the graph relation windows in memory/graph.py.

Minting is explicit (API / consolidation job), never inline in chat.
Chat recall reads observations through ``observation_context_block``:
the strongest open observations, ahead of raw memories, each cited
by id so the model can be told what it is standing on.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base

OBSERVATION_KINDS = ("fact", "decision", "preference", "correction")
VERDICTS = ("supports", "contradicts", "extends")


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return f"obs-{uuid.uuid4().hex[:12]}"


def normalize_claim(claim: str) -> str:
    """Dedup key: trimmed, whitespace-collapsed, lowercased, trailing
    punctuation stripped. Display text keeps its original casing."""
    text = re.sub(r"\s+", " ", (claim or "").strip()).lower()
    return text.rstrip(".!?")


class Observation(Base):
    """A consolidated, evidence-backed belief. Tables live here (not
    models.py), following the Batch 4 precedent in memory/graph.py:
    importing the route module registers this table."""

    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="fact")
    claim: Mapped[str] = mapped_column(Text)
    claim_norm: Mapped[str] = mapped_column(Text, index=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    refinement_history_json: Mapped[str] = mapped_column(Text, default="[]")
    proof_count: Mapped[int] = mapped_column(Integer, default=0)
    strength: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(16), default="open")
    superseded_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


def observation_out(row: Observation) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "claim": row.claim,
        "evidence": json.loads(row.evidence_json or "[]"),
        "refinement_history": json.loads(row.refinement_history_json or "[]"),
        "proof_count": row.proof_count,
        "strength": round(float(row.strength), 3),
        "status": row.status,
        "superseded_by": row.superseded_by,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "expired": _is_expired(row.expires_at),
    }


def _is_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    aware = expires_at if expires_at.tzinfo is not None else expires_at.replace(tzinfo=UTC)
    return aware <= _now()


def _evidence_key(ev: dict) -> tuple[str, str]:
    return (str(ev.get("quote", "")), str(ev.get("source_id", "")))


async def mint_observation(
    db: AsyncSession, user_id: str, kind: str, claim: str,
    evidence: list[dict], expires_at: datetime | None = None,
) -> tuple[Observation, bool]:
    """Mint, or strengthen an existing open observation with the same
    normalized claim. Returns (row, created_flag). New evidence items
    (by quote+source) are appended and proof_count grows; an exact
    re-mint with no new evidence is a no-op, not a duplicate row."""
    kind = kind if kind in OBSERVATION_KINDS else "fact"
    claim = (claim or "").strip()
    if not claim:
        raise ValueError("claim must not be empty")
    norm = normalize_claim(claim)
    existing = (await db.execute(
        select(Observation).where(
            Observation.user_id == user_id,
            Observation.claim_norm == norm,
            Observation.status == "open",
        )
    )).scalars().first()
    if existing is not None:
        seen = {_evidence_key(e) for e in json.loads(existing.evidence_json or "[]")}
        fresh = [e for e in (evidence or []) if _evidence_key(e) not in seen]
        if fresh:
            items = json.loads(existing.evidence_json or "[]") + fresh
            existing.evidence_json = json.dumps(items)
            existing.proof_count = len(items)
            existing.strength = min(1.0, float(existing.strength) + 0.1 * len(fresh))
            existing.updated_at = _now()
            await db.commit()
            await db.refresh(existing)
        return existing, False
    row = Observation(
        id=_new_id(), user_id=user_id, kind=kind, claim=claim, claim_norm=norm,
        evidence_json=json.dumps(list(evidence or [])),
        proof_count=len(evidence or []),
        strength=0.5, expires_at=expires_at,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row, True


async def refine_observation(
    db: AsyncSession, user_id: str, observation_id: str,
    evidence: list[dict], verdict: str,
) -> Observation | None:
    """Apply one refinement step. ``supports`` strengthens and counts
    new proof; ``extends`` appends evidence with a small strength bump;
    ``contradicts`` weakens WITHOUT deleting history or evidence —
    the caller mints a superseding observation for the correction."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    row = await db.get(Observation, observation_id)
    if row is None or row.user_id != user_id:
        return None
    items = json.loads(row.evidence_json or "[]")
    seen = {_evidence_key(e) for e in items}
    fresh = [e for e in (evidence or []) if _evidence_key(e) not in seen]
    history = json.loads(row.refinement_history_json or "[]")
    history.append({
        "verdict": verdict, "at": _now().isoformat(),
        "new_evidence": len(fresh), "strength_before": float(row.strength),
    })
    if verdict == "supports":
        items += fresh
        row.proof_count = len(items)
        row.strength = min(1.0, float(row.strength) + 0.1 * max(1, len(fresh)))
    elif verdict == "extends":
        items += fresh
        row.proof_count = len(items)
        row.strength = min(1.0, float(row.strength) + 0.05)
    else:  # contradicts
        row.strength = max(0.05, float(row.strength) - 0.2)
    history[-1]["strength_after"] = float(row.strength)
    row.evidence_json = json.dumps(items)
    row.refinement_history_json = json.dumps(history)
    row.updated_at = _now()
    await db.commit()
    await db.refresh(row)
    return row


async def supersede_observation(
    db: AsyncSession, user_id: str, observation_id: str,
    replacement_id: str | None = None,
) -> Observation | None:
    """Close an observation. History stays queryable; the replacement
    (if any) must already exist — supersede never invents one."""
    row = await db.get(Observation, observation_id)
    if row is None or row.user_id != user_id:
        return None
    if replacement_id is not None:
        replacement = await db.get(Observation, replacement_id)
        if replacement is None or replacement.user_id != user_id:
            raise ValueError("replacement observation not found")
    row.status = "superseded"
    row.superseded_by = replacement_id
    row.updated_at = _now()
    await db.commit()
    await db.refresh(row)
    return row


async def list_observations(
    db: AsyncSession, user_id: str, kind: str | None = None,
    include_closed: bool = False, limit: int = 50,
) -> list[Observation]:
    stmt = select(Observation).where(Observation.user_id == user_id)
    if kind:
        stmt = stmt.where(Observation.kind == kind)
    if not include_closed:
        stmt = stmt.where(Observation.status == "open")
    stmt = stmt.order_by(desc(Observation.strength), desc(Observation.created_at))
    rows = (await db.execute(stmt.limit(min(max(1, limit), 200)))).scalars().all()
    now = _now()
    out = []
    for row in rows:
        exp = row.expires_at
        if exp is not None:
            aware = exp if exp.tzinfo is not None else exp.replace(tzinfo=UTC)
            if aware <= now and not include_closed:
                continue
        out.append(row)
    return out


async def observation_context_block(
    db: AsyncSession, user_id: str, limit: int = 3,
) -> tuple[str, list[str]]:
    """Chat-recall surface: the strongest open, unexpired observations
    as one system-prompt block, plus the ids used (for provenance).
    Empty block + empty ids when there is nothing to recall."""
    rows = await list_observations(db, user_id, limit=limit)
    if not rows:
        return "", []
    lines = [
        f"- [{r.id}] {r.claim} (evidence items: {r.proof_count})"
        for r in rows
    ]
    return ("[Consolidated observations — beliefs backed by evidence, "
            "stronger than single memories]\n" + "\n".join(lines)), [r.id for r in rows]
