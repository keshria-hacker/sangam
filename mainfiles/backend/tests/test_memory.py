"""
Integration tests for cross-session memory + summarizer — Plan Phase 5.

SAFETY: per-test tmp_path SQLite file AND tmp ChromaDB dir, hard guard
against the production DB, TEST_MODE=1 before backend imports.

Covers:
- memory store/retrieve round-trip via ChromaDB (tmp path)
- should_summarize threshold logic
- GET /chats/{id}/summary endpoint (with and without summary)
- ChatOut exposes summary for the sidebar
"""

import os

os.environ["TEST_MODE"] = "1"

import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

_MAINFILES = Path(__file__).resolve().parents[2]
if str(_MAINFILES) not in sys.path:
    sys.path.insert(0, str(_MAINFILES))

from backend import ratelimit as _ratelimit  # noqa: E402
from backend.config import settings  # noqa: E402

_ratelimit.TEST_MODE = True

PROD_DB_MARKER = "history/sangam.db"


def _bind_test_engine(tmp_path) -> Path:
    test_db = tmp_path / "test.db"
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{test_db.as_posix()}"
    # Isolate ChromaDB per test via the env var rag.py reads at import-time
    # fallback... rag.py reads CHROMA_DB_PATH when the module is first
    # imported, so also reset cached handles after import.
    os.environ["CHROMA_DB_PATH"] = str(tmp_path / "chroma")
    settings.UPLOAD_DIR = tmp_path / "uploads"
    reset_engine_for_testing()
    assert PROD_DB_MARKER not in str(settings.DATABASE_URL), "SAFETY ABORT"
    return test_db


def reset_engine_for_testing():
    from backend.database import reset_engine_for_testing as _reset
    _reset()
    # Reset cached chroma handles so each test gets a fresh store.
    from backend import memory as memory_mod
    memory_mod.reset_memory_for_testing()
    import backend.rag as rag_mod
    rag_mod._client = None
    rag_mod._collection = None


@pytest.fixture
async def client(tmp_path):
    _bind_test_engine(tmp_path)
    engine = get_engine()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    await engine.dispose()


@pytest.fixture
async def auth_client(client):
    resp = await client.post(
        "/api/auth/register",
        json={"username": "tester", "password": "Password123"},
    )
    assert resp.status_code == 201, resp.text
    csrf = client.cookies.get("sangam_csrf")
    if csrf:
        client.headers["X-CSRF-Token"] = csrf
    return client


# ---------------------------------------------------------------------------
# Memory store/retrieve
# ---------------------------------------------------------------------------


async def test_memory_roundtrip(tmp_path):
    from backend.memory import retrieve_memories, store_memory

    ok = await store_memory("chatAAA", "Discussed FastAPI streaming and SSE formats.", ["fastapi", "streaming"], user_id="u1")
    assert ok is True
    await store_memory("chatBBB", "Planned the database migration strategy.", ["database", "migration"], user_id="u1")

    hits = await retrieve_memories("How do I stream SSE responses with FastAPI?", user_id="u1", top_k=2)
    assert isinstance(hits, list)
    assert any("FastAPI" in h for h in hits), f"expected streaming summary in {hits}"


async def test_memory_isolated_per_chroma_path(tmp_path):
    """A fresh ChromaDB path starts with no memories (isolation between stores)."""
    import importlib
    import backend.rag as rag_mod
    from backend import memory as memory_mod

    os.environ["CHROMA_DB_PATH"] = str(tmp_path / "fresh-chroma")
    rag_mod._client = None
    rag_mod._collection = None
    memory_mod.reset_memory_for_testing()
    importlib.reload(rag_mod)
    memory_mod.reset_memory_for_testing()

    from backend.memory import retrieve_memories
    hits = await retrieve_memories("anything at all", top_k=3)
    assert hits == []


async def test_store_memory_rejects_empty():
    from backend.memory import store_memory
    assert await store_memory("chatX", "   ", []) is False


# ---------------------------------------------------------------------------
# Summarizer threshold
# ---------------------------------------------------------------------------


async def _seed_chat_with_messages(n: int) -> str:
    from backend.database import AsyncSessionLocal
    from backend.models import Chat, Message
    async with AsyncSessionLocal() as db:
        chat = Chat(title="t", model="ollama::test-model")
        db.add(chat)
        await db.flush()
        for i in range(n):
            db.add(Message(chat_id=chat.id, role="user", content=f"msg {i}"))
        await db.commit()
        return chat.id


async def test_should_summarize_threshold(client, tmp_path):
    """20 messages -> True; 19 or 21 -> False (modulo check)."""
    from backend.database import AsyncSessionLocal
    from backend.summarizer import should_summarize

    chat_id = await _seed_chat_with_messages(20)
    async with AsyncSessionLocal() as db:
        assert await should_summarize(chat_id, db) is True

    chat_id = await _seed_chat_with_messages(19)
    async with AsyncSessionLocal() as db:
        assert await should_summarize(chat_id, db) is False


async def test_summarize_chat_persists_summary_and_memory(client, tmp_path, monkeypatch):
    """Mock the LLM stream; verify DB + vector-store persistence."""
    from backend.database import AsyncSessionLocal
    from backend.models import Chat
    from backend import summarizer as sum_mod

    async def fake_stream_completion(*args, **kwargs):
        yield "User asked about FastAPI streaming; assistant explained SSE patterns."
        return

    monkeypatch.setattr(sum_mod, "stream_completion", fake_stream_completion)

    chat_id = await _seed_chat_with_messages(3)
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        summary = await sum_mod.summarize_chat(chat_id, "ollama::test-model", db)
        assert summary and "FastAPI" in summary

        chat = (await db.execute(select(Chat).where(Chat.id == chat_id))).scalar_one()
        assert chat.summary == summary
        assert chat.summarized_at is not None
        # Topics are extracted from user turns; the fake summary mentions
        # FastAPI but the seeded user messages ("msg 0"...) yield none —
        # key_topics may be None when no meaningful words exist.
        if chat.key_topics is not None:
            assert isinstance(chat.key_topics, str)

    # Memory store got it too
    from backend.memory import retrieve_memories
    hits = await retrieve_memories("FastAPI streaming", top_k=2)
    assert any("FastAPI" in h for h in hits)


# ---------------------------------------------------------------------------
# Summary endpoint + ChatOut
# ---------------------------------------------------------------------------


async def test_summary_endpoint(auth_client):
    from backend.database import AsyncSessionLocal
    from backend.models import Chat
    chat_id = await _seed_chat_with_messages(1)
    async with AsyncSessionLocal() as db:
        chat = await db.get(Chat, chat_id)
        chat.summary = "A test summary."
        chat.key_topics = "alpha,beta"
        await db.commit()

    resp = await auth_client.get(f"/api/chats/{chat_id}/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] == "A test summary."
    assert body["key_topics"] == ["alpha", "beta"]


async def test_summary_endpoint_404(auth_client):
    resp = await auth_client.get("/api/chats/doesnotexist/summary")
    assert resp.status_code == 404


async def test_chat_list_exposes_summary(auth_client):
    """Sidebar subtitle depends on ChatOut.summary being serialized."""
    from backend.database import AsyncSessionLocal
    from backend.models import Chat
    chat_id = await _seed_chat_with_messages(1)
    async with AsyncSessionLocal() as db:
        chat = await db.get(Chat, chat_id)
        chat.summary = "Sidebar subtitle text."
        await db.commit()

    resp = await auth_client.get("/api/chats")
    assert resp.status_code == 200
    entry = next(c for c in resp.json() if c["id"] == chat_id)
    assert entry["summary"] == "Sidebar subtitle text."


from backend.database import Base, get_engine  # noqa: E402  (kept late to bind after env set)
from backend.main import create_app  # noqa: E402
