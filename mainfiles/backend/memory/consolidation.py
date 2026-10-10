"""
memory/consolidation.py — periodic memory maintenance.

Decay: untouched memories fade slowly. Prune: only memories that are
unimportant AND old AND never recalled are deleted. Conservative by design:
losing a memory is worse than keeping a stale one. Never raises.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .models import MemoryRecord
from .scoring import decayed_importance, should_prune
from .store import _get_collection, delete_memory, update_importance

logger = logging.getLogger(__name__)


async def consolidate(user_id: str = "", limit: int = 500) -> dict[str, int]:
    """Run one consolidation pass. Returns counts {decayed, pruned, kept}."""
    result = {"decayed": 0, "pruned": 0, "kept": 0}
    try:
        col = _get_collection()
        where: dict[str, Any] = {"user_id": user_id} if user_id else None  # type: ignore[assignment]
        fetched = col.get(
            where=where,
            limit=limit,
            include=["documents", "metadatas"],
        )
        ids = fetched.get("ids") or []
        docs = fetched.get("documents") or []
        metas = fetched.get("metadatas") or []
        now = datetime.now(UTC)
        for i, d, m in zip(ids, docs, metas):
            record = MemoryRecord.from_chroma(i, d, m)
            if should_prune(record, now):
                if await delete_memory(record.id):
                    result["pruned"] += 1
                continue
            new_importance = decayed_importance(record, now)
            if new_importance < record.importance - 1e-9:
                if await update_importance(record.id, new_importance):
                    result["decayed"] += 1
                    continue
            result["kept"] += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("consolidate failed: %s", exc)
    return result
