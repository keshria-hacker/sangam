"""
memory/ops.py — Batch 9: mem0-style record-level op loop (ADD / UPDATE /
DELETE / NONE) over recalled memories.

Sangam previously only ADDED memories and superseded graph relations;
a corrected fact never systematically UPDATED or DELETED the stale
record itself (only ``store.update_memory``/``delete_memory``
primitives existed, with no decision step). This module adds the
decision step — and it is deliberately heuristic, not LLM, so it is
testable without a model:

- exact normalized match            -> NONE (no-op, never a duplicate)
- high word overlap + correction marker ("now", "actually",
  "corrected", "instead")            -> UPDATE the best-matching record
- retraction marker ("forget", "no longer", "delete that", "wrong")
  + overlap                          -> DELETE the best-matching record
- otherwise                          -> ADD a new record

``preview_ops`` never writes. ``apply_ops`` writes ONLY when
``confirm=True`` and only the decisions the caller passes back —
no silent overwrites, and a decision may never invent a memory id:
UPDATE/DELETE targets must be ids from the recalled list.
"""
from __future__ import annotations

import re

from .models import MemoryRecord

_CORRECTION = ("now ", "actually", "corrected", "instead", "changed to", "rather")
_RETRACTION = ("forget ", "no longer", "delete that", "was wrong", "not true anymore",
               "ignore that", "discard")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower())) - {
        "the", "a", "an", "is", "are", "was", "were", "i", "my", "it", "to", "of",
    }


def _overlap(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(1, len(wa | wb))


def preview_ops(new_content: str, existing: list[MemoryRecord]) -> list[dict]:
    """Decide one op per recalled memory + a possible ADD. Returns
    decisions: {op, target_id (or None), new_content, reason}."""
    text = (new_content or "").strip()
    if not text:
        return []
    lowered = text.lower()
    norm = re.sub(r"\s+", " ", text).strip().lower()
    scored = sorted(
        (( _overlap(text, r.content), r) for r in existing),
        key=lambda pair: pair[0], reverse=True,
    )
    for score, record in scored:
        if re.sub(r"\s+", " ", record.content).strip().lower() == norm:
            return [{"op": "NONE", "target_id": record.id,
                     "new_content": None,
                     "reason": "identical record already stored"}]
    is_retraction = any(marker in lowered for marker in _RETRACTION)
    is_correction = any(marker in lowered for marker in _CORRECTION)
    if scored and scored[0][0] >= 0.3:
        score, record = scored[0]
        if is_retraction:
            return [{"op": "DELETE", "target_id": record.id,
                     "new_content": None,
                     "reason": f"retraction overlaps stored record (overlap {score:.2f})"}]
        if is_correction:
            return [{"op": "UPDATE", "target_id": record.id,
                     "new_content": text,
                     "reason": f"correction overlaps stored record (overlap {score:.2f})"}]
    return [{"op": "ADD", "target_id": None, "new_content": text,
             "reason": "no overlapping stored record"}]


async def apply_ops(decisions: list[dict], known_ids: set[str],
                    confirm: bool = False) -> dict:
    """Apply previewed decisions. Raises unless confirm=True; raises
    on any target id outside ``known_ids`` (ids are never invented).
    Returns {added, updated, deleted, skipped} ids."""
    if not confirm:
        raise ValueError("apply requires confirm=True (no silent overwrites)")
    from .store import delete_memory, save_memory, update_memory

    result: dict[str, list] = {"added": [], "updated": [], "deleted": [], "skipped": []}
    for decision in decisions:
        op = decision.get("op")
        target = decision.get("target_id")
        if op in ("UPDATE", "DELETE") and target not in known_ids:
            raise ValueError(f"unknown target memory id: {target}")
        if op == "ADD":
            record = await save_memory(decision.get("new_content") or "")
            if record is not None:
                result["added"].append(record.id)
        elif op == "UPDATE":
            record = await update_memory(target, content=decision.get("new_content"))
            if record is not None:
                result["updated"].append(target)
        elif op == "DELETE":
            if await delete_memory(target):
                result["deleted"].append(target)
        else:  # NONE or unknown op: never write
            result["skipped"].append(target)
    return result
