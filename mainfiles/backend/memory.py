"""
memory.py — Cross-session conversation memory using the existing ChromaDB.

Separate collection ("conversation_memories") from the document RAG
collection ("document_chunks"), same persistent client. Mirrors rag.py's
graceful-degradation contract: any failure is caught and logged; retrieval
returns [] so a broken memory never takes down a chat request.

Single-user app (chats/messages carry no user_id), so memories are scoped
by chat_id; user_id is stored as metadata for forward compatibility.
"""
from __future__ import annotations

import logging
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from .rag import _get_client  # reuse the persistent client singleton

logger = logging.getLogger(__name__)

COLLECTION_NAME = "conversation_memories"

_collection: Any = None


def _get_memory_collection() -> Any:
    global _collection
    if _collection is None:
        client = _get_client()
        try:
            _collection = client.get_collection(COLLECTION_NAME)
        except ValueError:
            _collection = client.create_collection(COLLECTION_NAME)
        except chromadb.errors.NotFoundError:
            _collection = client.create_collection(COLLECTION_NAME)
    return _collection


def reset_memory_for_testing() -> None:
    """Drop the cached collection handle (tests point CHROMA_DB_PATH at tmp)."""
    global _collection
    _collection = None


async def store_memory(chat_id: str, summary: str, key_topics: list[str], user_id: str = "") -> bool:
    """Upsert a conversation summary as a searchable memory.

    One memory per chat (id = chat_id), overwritten on re-summarize.
    Returns True on success, False on any failure (never raises).
    """
    try:
        summary = (summary or "").strip()
        if not summary:
            return False
        col = _get_memory_collection()
        col.upsert(
            documents=[summary],
            ids=[chat_id],
            metadatas=[{
                "chat_id": chat_id,
                "user_id": user_id,
                "topics": ",".join(key_topics)[:500],
            }],
        )
        return True
    except Exception as exc:  # noqa: BLE001 — memory must never break chat
        logger.warning("store_memory failed: %s", exc)
        return False


async def retrieve_memories(query: str, user_id: str = "", top_k: int = 2) -> list[str]:
    """Return up to top_k relevant past-conversation summaries for the query.

    Filters out the current chat's own memory is the caller's job (the caller
    knows the chat_id). Degrades to [] on any failure.
    """
    try:
        query = (query or "").strip()
        if not query:
            return []
        col = _get_memory_collection()
        kwargs: dict[str, Any] = {"n_results": top_k}
        if user_id:
            kwargs["where"] = {"user_id": user_id}
        results = col.query(query_texts=[query], **kwargs)
        docs = results.get("documents") or []
        return list(docs[0]) if docs else []
    except Exception as exc:  # noqa: BLE001
        logger.warning("retrieve_memories failed: %s", exc)
        return []
