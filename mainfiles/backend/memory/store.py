"""
memory/store.py — ChromaDB-backed memory persistence.

Same collection as the legacy module ("conversation_memories") so existing
memories keep working; new metadata fields default gracefully on read.
Graceful-degradation contract preserved: failures are logged, never raised.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import chromadb

from ..rag import _get_client  # reuse the persistent client singleton
from .models import MemoryKind, MemoryRecord

logger = logging.getLogger(__name__)

COLLECTION_NAME = "conversation_memories"

_collection: Any = None


def _get_collection() -> Any:
    global _collection
    if _collection is None:
        client = _get_client()
        try:
            _collection = client.get_collection(COLLECTION_NAME)
        except (ValueError, chromadb.errors.NotFoundError):
            _collection = client.create_collection(COLLECTION_NAME)
    return _collection


def reset_memory_for_testing() -> None:
    """Drop the cached collection handle (tests point CHROMA_DB_PATH at tmp)."""
    global _collection
    _collection = None


async def save_memory(
    content: str,
    kind: MemoryKind | str = MemoryKind.EPISODIC,
    chat_id: str = "",
    user_id: str = "",
    importance: float | None = None,
    room: str = "default",
    drawer: str = "general",
) -> MemoryRecord | None:
    """Persist one memory record. Returns the record, or None on failure."""
    try:
        content = (content or "").strip()
        if not content:
            return None
        if isinstance(kind, str):
            kind = MemoryKind(kind)
        record = MemoryRecord(
            id=uuid.uuid4().hex[:12],
            content=content[:2000],
            kind=kind,
            chat_id=chat_id,
            user_id=user_id,
            importance=importance if importance is not None else 0.4,
            room=room,
            drawer=drawer,
        )
        col = _get_collection()
        col.add(
            documents=[record.content],
            ids=[record.id],
            metadatas=[record.to_metadata()],
        )
        return record
    except Exception as exc:  # noqa: BLE001 — memory must never break chat
        logger.warning("save_memory failed: %s", exc)
        return None


async def get_memory(memory_id: str) -> MemoryRecord | None:
    try:
        col = _get_collection()
        result = col.get(ids=[memory_id], include=["documents", "metadatas"])
        ids = result.get("ids") or []
        if not ids:
            return None
        docs = result.get("documents") or [""]
        metas = result.get("metadatas") or [{}]
        return MemoryRecord.from_chroma(ids[0], docs[0], metas[0])
    except Exception as exc:  # noqa: BLE001
        logger.warning("get_memory failed: %s", exc)
        return None


async def delete_memory(memory_id: str) -> bool:
    try:
        _get_collection().delete(ids=[memory_id])
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("delete_memory failed: %s", exc)
        return False


async def list_memories(
    kind: MemoryKind | str | None = None,
    user_id: str = "",
    limit: int = 50,
) -> list[MemoryRecord]:
    """Most-recent memories first (no query text)."""
    try:
        col = _get_collection()
        where: dict[str, Any] = {}
        if kind is not None:
            kind = MemoryKind(kind) if isinstance(kind, str) else kind
            where["kind"] = kind.value
        if user_id:
            where["user_id"] = user_id
        result = col.get(
            where=where or None,
            limit=min(max(1, limit), 200),
            include=["documents", "metadatas"],
        )
        ids = result.get("ids") or []
        docs = result.get("documents") or []
        metas = result.get("metadatas") or []
        records = [
            MemoryRecord.from_chroma(i, d, m)
            for i, d, m in zip(ids, docs, metas)
        ]
        records.sort(key=lambda r: r.last_accessed, reverse=True)
        return records
    except Exception as exc:  # noqa: BLE001
        logger.warning("list_memories failed: %s", exc)
        return []


async def touch_memory(record: MemoryRecord) -> None:
    """Bump access stats after a successful recall (best-effort)."""
    try:
        record.access_count += 1
        record.last_accessed = datetime.now(UTC)
        _get_collection().update(ids=[record.id], metadatas=[record.to_metadata()])
    except Exception as exc:  # noqa: BLE001
        logger.debug("touch_memory failed: %s", exc)


async def update_importance(memory_id: str, importance: float) -> bool:
    try:
        record = await get_memory(memory_id)
        if record is None:
            return False
        record.importance = max(0.0, min(1.0, importance))
        _get_collection().update(ids=[record.id], metadatas=[record.to_metadata()])
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("update_importance failed: %s", exc)
        return False


async def memory_stats(user_id: str = "") -> dict[str, Any]:
    """Counts by kind + totals for the settings UI."""
    try:
        col = _get_collection()
        where = {"user_id": user_id} if user_id else None
        total = col.count()
        by_kind: dict[str, int] = {}
        for kind in MemoryKind:
            # Collection.count() takes no `where` — count via get().
            got = col.get(
                where={**(where or {}), "kind": kind.value},
                include=[],
            )
            by_kind[kind.value] = len(got.get("ids") or [])
        return {"total": total, "by_kind": by_kind}
    except Exception as exc:  # noqa: BLE001
        logger.warning("memory_stats failed: %s", exc)
        return {"total": 0, "by_kind": {k.value: 0 for k in MemoryKind}}


# --- Legacy compatibility (summarizer.py) ------------------------------------

async def store_memory(chat_id: str, summary: str, key_topics: list[str], user_id: str = "") -> bool:
    """Legacy: one summary memory per chat (id = chat_id), overwritten on
    re-summarize. Kept for summarizer.py; new code should use save_memory."""
    try:
        summary = (summary or "").strip()
        if not summary:
            return False
        record = MemoryRecord(
            id=chat_id,
            content=summary[:2000],
            kind=MemoryKind.EPISODIC,
            chat_id=chat_id,
            user_id=user_id,
            importance=0.5,
        )
        meta = record.to_metadata()
        meta["topics"] = ",".join(key_topics)[:500]
        col = _get_collection()
        col.upsert(documents=[record.content], ids=[record.id], metadatas=[meta])
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("store_memory failed: %s", exc)
        return False
