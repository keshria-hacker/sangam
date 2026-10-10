"""
memory/retrieval.py — ranked memory recall.

Overfetches from ChromaDB, then re-ranks with the explainable score
(similarity × recency × importance × access). Recalled memories get their
access stats bumped so frequently useful memories rank higher over time.
"""
from __future__ import annotations

import logging
from typing import Any

from .models import MemoryKind, MemoryRecord
from .scoring import rank
from .store import _get_collection, touch_memory

logger = logging.getLogger(__name__)

DUPLICATE_DISTANCE = 0.25  # below this L2 distance, a memory is a near-duplicate


async def recall(
    query: str,
    user_id: str = "",
    top_k: int = 3,
    kinds: list[MemoryKind | str] | None = None,
    exclude_chat_id: str = "",
    touch: bool = True,
) -> list[MemoryRecord]:
    """Return the top_k memories for a query, best-first. Never raises."""
    try:
        query = (query or "").strip()
        if not query:
            return []
        col = _get_collection()
        kwargs: dict[str, Any] = {"n_results": max(top_k * 3, 10)}
        where: dict[str, Any] = {}
        if user_id:
            where["user_id"] = user_id
        if kinds:
            kind_values = [k.value if isinstance(k, MemoryKind) else str(k) for k in kinds]
            if len(kind_values) == 1:
                where["kind"] = kind_values[0]
            else:
                where["$or"] = [{"kind": v} for v in kind_values]
        if where:
            kwargs["where"] = where
        results = col.query(
            query_texts=[query],
            include=["documents", "metadatas", "distances"],
            **kwargs,
        )
        ids = (results.get("ids") or [[]])[0]
        docs = (results.get("documents") or [[]])[0]
        metas = (results.get("metadatas") or [[]])[0]
        distances = (results.get("distances") or [[]])[0]
        records = [
            MemoryRecord.from_chroma(i, d, m, dist)
            for i, d, m, dist in zip(ids, docs, metas, distances)
        ]
        if exclude_chat_id:
            records = [r for r in records if r.chat_id != exclude_chat_id]
        ranked = rank(records)[:top_k]
        if touch:
            for record in ranked:
                await touch_memory(record)
        return ranked
    except Exception as exc:  # noqa: BLE001 — memory must never break chat
        logger.warning("recall failed: %s", exc)
        return []


async def find_near_duplicate(
    content: str,
    user_id: str = "",
    threshold: float = DUPLICATE_DISTANCE,
) -> MemoryRecord | None:
    """Return an existing near-duplicate memory, if any (for dedup on save)."""
    candidates = await recall(content, user_id=user_id, top_k=1, touch=False)
    if not candidates:
        return None
    record = candidates[0]
    # ChromaDB squared-L2 distance back-converted from similarity.
    distance = 1.0 - record.similarity
    return record if distance < threshold else None


async def retrieve_memories(query: str, user_id: str = "", top_k: int = 2) -> list[str]:
    """Legacy string API (chat pipeline + summarizer compat)."""
    records = await recall(query, user_id=user_id, top_k=top_k)
    return [r.content for r in records]
