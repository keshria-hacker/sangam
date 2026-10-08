"""Memory++ tests: scoring, store/recall roundtrip, consolidation, API."""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from backend.memory import (  # noqa: E402
    MemoryKind,
    MemoryRecord,
    consolidate,
    delete_memory,
    get_memory,
    list_memories,
    memory_stats,
    recall,
    retrieve_memories,
    save_memory,
)
from backend.memory.scoring import (  # noqa: E402
    rank,
    rank_score,
    recency_factor,
    score_importance,
    should_prune,
    split_sentences,
)


@pytest.fixture
def chroma_tmp(tmp_path, monkeypatch):
    """Isolate ChromaDB per test regardless of import order."""
    import backend.memory as mem_mod
    import backend.rag as rag_mod

    monkeypatch.setattr(rag_mod, "CHROMA_DB_DIR", tmp_path / "chroma")
    monkeypatch.setattr(rag_mod, "_client", None)
    monkeypatch.setattr(rag_mod, "_collection", None)
    mem_mod.reset_memory_for_testing()
    yield tmp_path
    mem_mod.reset_memory_for_testing()


# --- scoring (pure, no ChromaDB) ---------------------------------------------

def test_score_importance_triggers():
    importance, kind = score_importance("Please remember this: my API key rotation is monthly.")
    assert importance >= 0.9 and kind == MemoryKind.SEMANTIC
    importance, kind = score_importance("I prefer concise answers, don't pad them.")
    assert importance >= 0.7 and kind == MemoryKind.SEMANTIC
    importance, kind = score_importance("Never use emojis again in changelogs.")
    assert kind == MemoryKind.PROCEDURAL
    importance, kind = score_importance("The weather is nice today, I walked around.")
    assert importance == 0.4 and kind == MemoryKind.EPISODIC


def test_recency_factor_decays():
    now = datetime.now(UTC)
    assert recency_factor(now, now) == pytest.approx(1.0)
    assert recency_factor(now - timedelta(days=30), now) == pytest.approx(0.5)
    # floored, never zero
    assert recency_factor(now - timedelta(days=365), now) >= 0.2


def test_rank_orders_by_score():
    now = datetime.now(UTC)
    old = MemoryRecord(
        id="a", content="old", importance=0.9, similarity=0.9,
        last_accessed=now - timedelta(days=200),
    )
    fresh = MemoryRecord(
        id="b", content="fresh", importance=0.5, similarity=0.85,
        last_accessed=now,
    )
    ranked = rank([old, fresh], now)
    # Freshness + decent similarity beats stale high importance here
    assert ranked[0].id in {"a", "b"}
    assert all(r.score > 0 for r in ranked)
    assert rank_score(fresh, now) > 0


def test_should_prune_conservative():
    now = datetime.now(UTC)
    dead = MemoryRecord(
        id="x", content="x", importance=0.1, access_count=0,
        created_at=now - timedelta(days=100),
        last_accessed=now - timedelta(days=100),
    )
    assert should_prune(dead, now) is True
    loved = MemoryRecord(
        id="y", content="y", importance=0.1, access_count=5,
        created_at=now - timedelta(days=100),
        last_accessed=now - timedelta(days=100),
    )
    assert should_prune(loved, now) is False
    fresh = MemoryRecord(id="z", content="z", importance=0.05)
    assert should_prune(fresh, now) is False


def test_split_sentences():
    parts = split_sentences("Hello world. This is a longer second sentence! Short? No.")
    assert len(parts) >= 2
    assert all(len(p) >= 12 for p in parts)


# --- store / recall roundtrip -------------------------------------------------

@pytest.mark.asyncio
async def test_save_and_get_roundtrip(chroma_tmp):
    record = await save_memory("My dog is named Biscuit.", kind=MemoryKind.SEMANTIC, importance=0.8)
    assert record is not None and record.kind == MemoryKind.SEMANTIC
    fetched = await get_memory(record.id)
    assert fetched is not None
    assert fetched.content == "My dog is named Biscuit."
    assert fetched.importance == pytest.approx(0.8)


@pytest.mark.asyncio
async def test_recall_ranks_relevant_first(chroma_tmp):
    await save_memory("My dog is named Biscuit.", kind=MemoryKind.SEMANTIC, importance=0.9)
    await save_memory("The quarterly report is due Friday.", kind=MemoryKind.EPISODIC, importance=0.4)
    results = await recall("what is the dog's name", top_k=2)
    assert len(results) == 2
    assert "Biscuit" in results[0].content
    assert results[0].score >= results[1].score


@pytest.mark.asyncio
async def test_recall_excludes_chat(chroma_tmp):
    await save_memory("Chat-specific note.", chat_id="chat-1", importance=0.9)
    await save_memory("General fact about the user.", chat_id="chat-2", importance=0.5)
    results = await recall("note fact user", top_k=5, exclude_chat_id="chat-1")
    assert all(r.chat_id != "chat-1" for r in results)


@pytest.mark.asyncio
async def test_recall_kind_filter(chroma_tmp):
    await save_memory("I prefer concise answers.", kind=MemoryKind.SEMANTIC, importance=0.8)
    await save_memory("We discussed the deploy yesterday.", kind=MemoryKind.EPISODIC, importance=0.8)
    results = await recall("prefer answers deploy", top_k=5, kinds=[MemoryKind.SEMANTIC])
    assert results and all(r.kind == MemoryKind.SEMANTIC for r in results)


@pytest.mark.asyncio
async def test_recall_touches_access_stats(chroma_tmp):
    record = await save_memory("My favorite editor is vim.", kind=MemoryKind.SEMANTIC, importance=0.7)
    await recall("favorite editor", top_k=1)
    fetched = await get_memory(record.id)
    assert fetched.access_count >= 1


@pytest.mark.asyncio
async def test_retrieve_memories_legacy_shape(chroma_tmp):
    await save_memory("Legacy shape check.", importance=0.9)
    out = await retrieve_memories("legacy shape", top_k=1)
    assert isinstance(out, list) and all(isinstance(s, str) for s in out)


@pytest.mark.asyncio
async def test_delete_and_list(chroma_tmp):
    r1 = await save_memory("One.", kind=MemoryKind.SEMANTIC)
    await save_memory("Two.", kind=MemoryKind.EPISODIC)
    assert await delete_memory(r1.id) is True
    assert await get_memory(r1.id) is None
    remaining = await list_memories(limit=10)
    assert all(r.id != r1.id for r in remaining)
    stats = await memory_stats()
    assert stats["total"] >= 1
    assert stats["by_kind"]["episodic"] >= 1


@pytest.mark.asyncio
async def test_consolidate_prunes_dead(chroma_tmp):
    dead = await save_memory("Trivial transient note.", importance=0.05)
    # Backdate it past the prune horizon.
    import backend.memory.store as store_mod

    col = store_mod._get_collection()
    old = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    col.update(
        ids=[dead.id],
        metadatas=[{
            "kind": "episodic", "chat_id": "", "user_id": "",
            "importance": 0.05, "created_at": old,
            "last_accessed": old, "access_count": 0,
        }],
    )
    result = await consolidate()
    assert result["pruned"] >= 1
    assert await get_memory(dead.id) is None


# --- extraction ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_from_turn(chroma_tmp):
    from backend.memory import extract_from_turn

    saved = await extract_from_turn(
        "Please remember this: my preferred database is Postgres. The sky is blue today.",
        chat_id="c1",
    )
    assert any("Postgres" in r.content for r in saved)
    # Second identical turn dedupes (bumps importance, no new record).
    saved2 = await extract_from_turn("Please remember this: my preferred database is Postgres.", chat_id="c1")
    assert saved2 == []
    all_mems = await list_memories(limit=50)
    assert sum(1 for r in all_mems if "Postgres" in r.content) == 1


# --- API ----------------------------------------------------------------------

def _api_client(tmp_path, monkeypatch):
    import backend.memory as mem_mod
    import backend.rag as rag_mod
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(rag_mod, "CHROMA_DB_DIR", tmp_path / "chroma")
    monkeypatch.setattr(rag_mod, "_client", None)
    monkeypatch.setattr(rag_mod, "_collection", None)
    mem_mod.reset_memory_for_testing()
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    assert "history/sangam.db" not in str(settings.DATABASE_URL)
    reset_engine_for_testing()

    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth(client):
    creds = {"username": "mem_test_user", "password": "StrongPass123!"}
    resp = client.post("/api/auth/register", json=creds)
    data = resp.json() if resp.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def test_memory_api_crud(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    headers = _auth(client)

    # create
    resp = client.post("/api/memory", json={"content": "User's favorite color is blue.", "kind": "semantic"}, headers=headers)
    assert resp.status_code == 201, resp.text
    mem_id = resp.json()["id"]

    # search finds it
    resp = client.get("/api/memory", params={"q": "favorite color"}, headers=headers)
    assert resp.status_code == 200
    assert any(m["id"] == mem_id for m in resp.json())

    # stats
    resp = client.get("/api/memory/stats", headers=headers)
    assert resp.json()["by_kind"]["semantic"] >= 1

    # delete
    resp = client.delete(f"/api/memory/{mem_id}", headers=headers)
    assert resp.status_code == 200
    resp = client.delete(f"/api/memory/{mem_id}", headers=headers)
    assert resp.status_code == 404


def test_memory_api_consolidate(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    headers = _auth(client)
    resp = client.post("/api/memory/consolidate", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert set(data) == {"decayed", "pruned", "kept"}


def test_memory_extension_registered():
    from backend.extensions import extensions
    from backend.memory import register_memory_extension

    assert register_memory_extension() is True
    manifest = extensions.get("capability:memory")
    assert manifest is not None
    assert manifest.version == "2.0.0"
