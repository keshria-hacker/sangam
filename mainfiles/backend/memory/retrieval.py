"""
memory/retrieval.py — ranked memory recall.

Deep-memory wiring: recall routes through the same hybrid machinery
documents already use (``backend.hybrid_retrieval``: BM25 keyword pool
+ RRF k=60 + deterministic 0.6 vector / 0.4 keyword rerank), then the
existing recency × importance × access multipliers, plus an entity-
graph boost when a DB session is supplied. Before this change recall
was vector-only, so a memory containing an exact rare term the
embedding paraphrased away was unfindable by chat while the same
query over documents would find it.

Degradation contract (unchanged): recall never raises. If the hybrid
keyword pool, the rerank, or the graph lookup fails, recall falls
back to the previous vector-only ranking instead of failing chat.
"""
from __future__ import annotations

import logging
from typing import Any

from .models import MemoryKind, MemoryRecord
from .scoring import access_boost, rank, recency_factor
from .store import _get_collection, touch_memory

logger = logging.getLogger(__name__)

DUPLICATE_DISTANCE = 0.25  # below this L2 distance, a memory is a near-duplicate
KEYWORD_POOL_LIMIT = 500  # same cap as document hybrid retrieval

# mem0's entity-boost cap (ENTITY_BOOST_WEIGHT = 0.5), damped for
# entities linked to many memories so a generic entity cannot dominate.
ENTITY_BOOST_CAP = 0.5


def entity_boosts(
    query: str,
    records: list[MemoryRecord],
    entity_names: list[str],
) -> dict[str, float]:
    """Pure entity-graph boost (mem0-style, no DB access).

    An entity counts only when its name appears in the *query* (the
    query-entity step) and in a candidate record's text (the linked-
    memory step). Boost per entity is capped at 0.5 and damped by
    ``1 / (1 + 0.001 * (n - 1) ** 2)`` where ``n`` is how many
    candidates mention the entity, so an entity linked to hundreds
    of memories barely boosts any single one. Returns {record_id: boost}.
    """
    boosts: dict[str, float] = {}
    query_l = (query or "").lower()
    if not query_l or not entity_names or not records:
        return boosts
    texts = {r.id: (r.content or "").lower() for r in records}
    for name in entity_names:
        name_l = (name or "").strip().lower()
        if not name_l or name_l not in query_l:
            continue
        linked = [r.id for r in records if name_l in texts[r.id]]
        if not linked:
            continue
        boost = ENTITY_BOOST_CAP / (1.0 + 0.001 * (len(linked) - 1) ** 2)
        for rid in linked:
            boosts[rid] = min(ENTITY_BOOST_CAP, boosts.get(rid, 0.0) + boost)
    return boosts


async def graph_entity_names(db: Any, user_id: str) -> list[str]:
    """Entity names for the user from the temporal graph (best-effort).

    Never raises: any DB problem yields [] and recall proceeds
    without the graph boost. This is the read side the graph
    previously lacked — chat recall never consulted it.
    """
    try:
        if db is None or not user_id:
            return []
        from .graph import list_entities

        rows = await list_entities(db, user_id)
        return [r.name for r in rows if r.name]
    except Exception as exc:  # noqa: BLE001 — graph must never break recall
        logger.warning("graph entity lookup failed: %s", exc)
        return []


async def recall(
    query: str,
    user_id: str = "",
    top_k: int = 3,
    kinds: list[MemoryKind | str] | None = None,
    exclude_chat_id: str = "",
    touch: bool = True,
    db: Any = None,
    graph_user_id: str = "",
) -> list[MemoryRecord]:
    """Return the top_k memories for a query, best-first. Never raises.

    ``db`` + ``graph_user_id`` are optional and only feed the entity
    boost: they never filter memories (chat-saved memories carry no
    user_id, so filtering by user here would hide them). Without a
    DB session the hybrid rerank still runs; without either, the
    vector-only ranking is the fallback.
    """
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
        # Distance map BEFORE exclusion: positions shift once a record
        # is dropped, so the hybrid path must look distances up by id.
        dist_by_id = {
            i: (d if isinstance(d, (int, float)) else None)
            for i, d in zip(ids, distances)
        }
        if exclude_chat_id:
            records = [r for r in records if r.chat_id != exclude_chat_id]
        # Vector-only baseline: kept as the fallback if anything below
        # fails, so a hybrid/graph error degrades chat, never breaks it.
        ranked = rank(list(records))[:top_k]
        try:
            hybrid = await _hybrid_recall(
                query, records, dist_by_id, col, where,
                exclude_chat_id=exclude_chat_id, top_k=top_k,
                db=db, graph_user_id=graph_user_id,
            )
            if hybrid:
                ranked = hybrid
        except Exception as exc:  # noqa: BLE001 — degrade, don't crash chat
            logger.warning("hybrid memory recall failed, vector-only: %s", exc)
        if touch:
            for record in ranked:
                await touch_memory(record)
        return ranked
    except Exception as exc:  # noqa: BLE001 — memory must never break chat
        logger.warning("recall failed: %s", exc)
        return []


async def _hybrid_recall(
    query: str,
    vector_records: list[MemoryRecord],
    dist_by_id: dict[str, float | None],
    col: Any,
    where: dict[str, Any],
    *,
    exclude_chat_id: str = "",
    top_k: int = 3,
    db: Any = None,
    graph_user_id: str = "",
) -> list[MemoryRecord]:
    """Hybrid rerank of the vector pool + full keyword pool.

    Returns [] when there is nothing to rerank (caller keeps the
    vector baseline). Raises only on unexpected errors, which the
    caller converts into the vector-only fallback.
    """
    from ..hybrid_retrieval import hybrid_rank

    if not vector_records:
        return []
    vector_candidates = [
        {"id": r.id, "text": r.content, "vector_score": dist_by_id.get(r.id)}
        for r in vector_records
    ]
    # Keyword pool: the full memory pool for this filter (cap 500),
    # fetched keyword-side only — a keyword-only hit that vector
    # search missed is exactly what this path rescues.
    pool = col.get(
        where=where or None,
        limit=KEYWORD_POOL_LIMIT,
        include=["documents", "metadatas"],
    ) or {}
    pool_ids = pool.get("ids") or []
    pool_docs = pool.get("documents") or []
    pool_metas = pool.get("metadatas") or []
    pool_records: dict[str, MemoryRecord] = {}
    keyword_candidates: list[dict[str, Any]] = []
    for pid, doc, meta in zip(pool_ids, pool_docs, pool_metas):
        if not doc:
            continue
        rec = MemoryRecord.from_chroma(pid, doc, meta)
        if exclude_chat_id and rec.chat_id == exclude_chat_id:
            continue
        pool_records[pid] = rec
        keyword_candidates.append({"id": pid, "text": doc})
    # Pool records fill in keyword-only ids; vector records MUST win
    # for shared ids — they carry the similarity/distance that
    # near-duplicate detection (1 - similarity) depends on. Overwriting
    # them with distance-less pool rows silently broke dedup.
    by_id: dict[str, MemoryRecord] = dict(pool_records)
    by_id.update({r.id: r for r in vector_records})
    fused = hybrid_rank(
        query, vector_candidates, keyword_candidates,
        top_k=len(vector_candidates) + len(keyword_candidates),
    )
    if not fused:
        return []
    boosts = entity_boosts(
        query, [by_id[c["id"]] for c in fused if c["id"] in by_id],
        await graph_entity_names(db, graph_user_id),
    )
    now = None  # rank helpers default to now
    scored: list[MemoryRecord] = []
    for cand in fused:
        record = by_id.get(cand["id"])
        if record is None:
            continue
        blend = float(cand.get("score") or 0.0) + boosts.get(record.id, 0.0)
        # Same multipliers as rank_score, with the hybrid blend in
        # place of raw vector similarity.
        record.score = (
            blend
            * (0.5 + 0.5 * recency_factor(record.last_accessed, now))
            * (0.6 + 0.4 * max(0.0, min(1.0, record.importance)))
            * access_boost(record.access_count)
        )
        # Keep `similarity` as the vector similarity: near-duplicate
        # detection (1 - similarity as L2 distance) depends on it.
        scored.append(record)
    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:top_k]


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
