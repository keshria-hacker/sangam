"""Deep-memory chat wiring tests (Wave-1: MEMORY + CHAT-RECALL WIRING).

Covers the three builds, verified against the chat path — not just
against the endpoint that previously owned them:

1. LLM memory extraction wired into chat: additive prompt (last-10
   turns, both roles, remapped link ids, observation-date grounding),
   md5 dedup, unparseable -> empty (never invented), and the
   fire-and-forget wrapper that returns before the LLM call finishes
   (extraction runs post-response, never delaying the reply).
2. Hybrid memory recall: an exact-term memory that the vector ranking
   missed is found via the keyword pool + RRF + 0.6/0.4 rerank, and a
   keyword-pool failure degrades to the vector ranking instead of
   crashing chat. Entity-graph boost is tested as a pure function.
3. ADHD prompt style: on/off changes the prompt path (helper level),
   the chat route calls it, and GET /api/quality/adhd-style reports
   wired_into_chat=true.

Pytest TestClient only — no Playwright, no servers on shared ports.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from backend.memory import (  # noqa: E402
    MemoryRecord,
    extract_chat_memories_llm,
    extract_from_turn_llm_background,
    list_memories,
    recall,
)
from backend.memory.extract_llm import (  # noqa: E402
    build_additive_prompt,
    md5_dedup_key,
    parse_additive_extraction,
)
from backend.memory.retrieval import entity_boosts  # noqa: E402
from backend.response_quality.adhd import (  # noqa: E402
    adhd_style_enabled,
    adhd_style_text,
    apply_adhd_style_to_messages,
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


# ---------------------------------------------------------------------------
# 1a. Additive prompt construction (pure)
# ---------------------------------------------------------------------------

def test_additive_prompt_caps_turns_and_remaps_ids():
    messages = [{"role": "user", "content": f"user turn {i}"} for i in range(15)]
    messages.append({"role": "system", "content": "system noise must be dropped"})
    existing = [
        MemoryRecord(id="real-aaa", content="User's dog is named Biscuit."),
        MemoryRecord(id="real-bbb", content="User prefers concise answers."),
    ]
    prompt, id_map = build_additive_prompt(messages, existing, observation_date="2026-10-24")
    assert id_map == {"0": "real-aaa", "1": "real-bbb"}
    assert "real-aaa" not in prompt and "real-bbb" not in prompt  # ids never leak
    assert "[0] User's dog is named Biscuit." in prompt
    assert "Observation Date: 2026-10-24" in prompt
    assert "system noise" not in prompt
    # Last 10 turns only: turn 0..4 dropped, turn 14 kept.
    assert "user turn 0\n" not in prompt and "user turn 14" in prompt


def test_additive_prompt_keeps_both_roles():
    messages = [
        {"role": "user", "content": "I need a morning routine."},
        {"role": "assistant", "content": "I recommend a nightly walk routine."},
    ]
    prompt, _ = build_additive_prompt(messages, [])
    assert "user: I need a morning routine." in prompt
    assert "assistant: I recommend a nightly walk routine." in prompt


def test_parse_additive_remaps_links_and_drops_invented_ids():
    raw = json.dumps({"memory": [
        {"text": "User was recommended a nightly walk routine",
         "attributed_to": "assistant", "linked_memory_ids": ["0"]},
        {"text": "User invented a link to nowhere",
         "attributed_to": "user", "linked_memory_ids": ["99", "real-xyz"]},
        {"text": "   ", "attributed_to": "user", "linked_memory_ids": []},
    ]})
    facts = parse_additive_extraction(raw, {"0": "real-aaa"})
    assert len(facts) == 2
    assert facts[0]["linked_memory_ids"] == ["real-aaa"]
    assert facts[0]["attributed_to"] == "assistant"
    # "99" is invented (not in the map) and dropped; a real id echoed
    # back is kept only if it was in the map's values — "real-xyz"
    # was never shown, so it is dropped too.
    assert facts[1]["linked_memory_ids"] == []


def test_parse_additive_unparseable_is_empty_never_invented():
    assert parse_additive_extraction("this is not json at all") == []
    assert parse_additive_extraction("") == []
    assert parse_additive_extraction(None) == []
    assert parse_additive_extraction('{"facts": ["not the additive shape"]}') == []


def test_md5_dedup_key_ignores_case_and_whitespace():
    assert md5_dedup_key("User's Dog Is Named Biscuit.") == md5_dedup_key(
        "  user's   dog is named biscuit. ")


# ---------------------------------------------------------------------------
# 1b. Chat LLM extraction (real Chroma, mocked model)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_chat_llm_extraction_saves_assistant_fact_with_link(chroma_tmp, monkeypatch):
    import backend.memory.extract_llm as extract_llm_mod

    recalled = [MemoryRecord(id="real-aaa", content="User's dog is named Biscuit.")]
    payload = json.dumps({"memory": [
        {"text": "User was recommended a nightly walk routine with Biscuit",
         "attributed_to": "assistant", "linked_memory_ids": ["0"]},
    ]})

    async def fake_complete(db, messages, max_tokens=2000):
        return payload

    monkeypatch.setattr(extract_llm_mod, "complete_text", fake_complete)
    result = await extract_chat_memories_llm(
        [{"role": "user", "content": "What routine should Biscuit and I follow?"}],
        assistant_text="I recommend a nightly walk routine with Biscuit.",
        chat_id="chat-1", recalled=recalled,
    )
    assert result["model_used"] is True
    assert len(result["saved"]) == 1
    assert result["saved"][0]["linked_memory_ids"] == ["real-aaa"]
    assert result["saved"][0]["attributed_to"] == "assistant"
    stored = await list_memories(limit=50)
    assert any("nightly walk routine" in r.content for r in stored)
    assert any(r.linked_memory_ids == ["real-aaa"] for r in stored)


@pytest.mark.asyncio
async def test_chat_llm_extraction_unparseable_and_no_model_save_nothing(chroma_tmp, monkeypatch):
    import backend.memory.extract_llm as extract_llm_mod

    async def fake_garbage(db, messages, max_tokens=2000):
        return "not json, not a fact, do not store this"

    monkeypatch.setattr(extract_llm_mod, "complete_text", fake_garbage)
    result = await extract_chat_memories_llm(
        [{"role": "user", "content": "Remember this: my preferred database is Postgres."}],
        chat_id="chat-1", recalled=[],
    )
    assert result["saved"] == [] and result["facts"] == []
    assert await list_memories(limit=50) == []

    async def fake_none(db, messages, max_tokens=2000):
        return None

    monkeypatch.setattr(extract_llm_mod, "complete_text", fake_none)
    result = await extract_chat_memories_llm(
        [{"role": "user", "content": "Remember this: my preferred database is Postgres."}],
        chat_id="chat-1", recalled=[],
    )
    assert result["model_used"] is False and result["saved"] == []


@pytest.mark.asyncio
async def test_chat_llm_extraction_md5_dedup(chroma_tmp, monkeypatch):
    import backend.memory.extract_llm as extract_llm_mod

    recalled = [MemoryRecord(id="r1", content="User prefers concise answers.")]
    payload = json.dumps({"memory": [
        {"text": "User prefers concise answers.", "attributed_to": "user", "linked_memory_ids": []},
        {"text": "User likes morning runs.", "attributed_to": "user", "linked_memory_ids": []},
        {"text": "User likes morning runs.", "attributed_to": "user", "linked_memory_ids": []},
    ]})

    async def fake_complete(db, messages, max_tokens=2000):
        return payload

    monkeypatch.setattr(extract_llm_mod, "complete_text", fake_complete)
    result = await extract_chat_memories_llm(
        [{"role": "user", "content": "I like morning runs and concise answers."}],
        chat_id="chat-1", recalled=recalled,
    )
    # Exact duplicate of recalled text skipped; batch duplicate saved once.
    assert [s["content"] for s in result["saved"]] == ["User likes morning runs."]


@pytest.mark.asyncio
async def test_llm_background_wrapper_returns_before_model_finishes(chroma_tmp, monkeypatch):
    """Post-response, non-blocking: the wrapper returns immediately and
    the memory only appears once the background task completes."""
    import backend.memory.extract_llm as extract_llm_mod

    payload = json.dumps({"memory": [
        {"text": "User prefers concise answers.", "attributed_to": "user", "linked_memory_ids": []},
    ]})

    async def slow_complete(db, messages, max_tokens=2000):
        await asyncio.sleep(0.3)
        return payload

    monkeypatch.setattr(extract_llm_mod, "complete_text", slow_complete)
    extract_from_turn_llm_background(
        [{"role": "user", "content": "I prefer concise answers, don't pad them."}],
        assistant_text="Got it, concise from now on.",
        chat_id="chat-1",
    )
    # Wrapper has returned; the slow model has not finished yet.
    assert await list_memories(limit=50) == []
    # Poll: the background task also pays first-use Chroma embedding
    # init, so a fixed short sleep is flaky — poll up to 20s instead.
    stored = []
    for _ in range(40):
        await asyncio.sleep(0.5)
        stored = await list_memories(limit=50)
        if any("concise answers" in r.content for r in stored):
            break
    assert any("concise answers" in r.content for r in stored)


# ---------------------------------------------------------------------------
# 2. Hybrid memory recall (fake collection: vector miss, keyword hit)
# ---------------------------------------------------------------------------

def _meta(importance=0.5):
    now = datetime.now(UTC).isoformat()
    return {
        "kind": "episodic", "chat_id": "", "user_id": "",
        "importance": importance, "created_at": now,
        "last_accessed": now, "access_count": 0,
        "room": "default", "drawer": "general",
    }


class _FakeCollection:
    """Vector query misses the exact-term doc; the pool contains it."""

    def __init__(self, fail_get=False):
        self.fail_get = fail_get
        self.vector_rows = [
            ("vec-a", "General chat about the weather lately", 0.9),
            ("vec-b", "Something else entirely different", 1.2),
        ]
        self.pool_rows = [
            ("vec-a", "General chat about the weather lately"),
            ("vec-b", "Something else entirely different"),
            ("kw-c", "The quasiflobber protocol requires nightly rotation"),
        ]

    def query(self, query_texts, include=None, **kwargs):
        return {
            "ids": [[r[0] for r in self.vector_rows]],
            "documents": [[r[1] for r in self.vector_rows]],
            "metadatas": [[_meta() for _ in self.vector_rows]],
            "distances": [[r[2] for r in self.vector_rows]],
        }

    def get(self, where=None, limit=None, include=None, **kwargs):
        if self.fail_get:
            raise RuntimeError("keyword pool down")
        return {
            "ids": [r[0] for r in self.pool_rows],
            "documents": [r[1] for r in self.pool_rows],
            "metadatas": [_meta() for _ in self.pool_rows],
        }


@pytest.mark.asyncio
async def test_hybrid_recall_finds_exact_term_vector_missed(monkeypatch):
    import backend.memory.retrieval as retrieval_mod

    monkeypatch.setattr(retrieval_mod, "_get_collection", lambda: _FakeCollection())
    results = await recall("quasiflobber nightly rotation", top_k=2, touch=False)
    assert results, "hybrid recall returned nothing"
    # The vector ranking alone could only return vec-a/vec-b; the
    # keyword pool rescues the exact-term memory into first place.
    assert "quasiflobber" in results[0].content
    assert any("quasiflobber" in r.content for r in results)


@pytest.mark.asyncio
async def test_hybrid_recall_degrades_to_vector_only_on_pool_failure(monkeypatch):
    import backend.memory.retrieval as retrieval_mod

    monkeypatch.setattr(
        retrieval_mod, "_get_collection", lambda: _FakeCollection(fail_get=True))
    results = await recall("quasiflobber nightly rotation", top_k=2, touch=False)
    assert len(results) == 2
    assert all("quasiflobber" not in r.content for r in results)


def test_entity_boosts_query_entity_only_damped_and_capped():
    now = datetime.now(UTC)
    records = [
        MemoryRecord(id="a", content="Project Quasiflobber launches Monday.", last_accessed=now),
        MemoryRecord(id="b", content="Project Quasiflobber needs a logo.", last_accessed=now),
        MemoryRecord(id="c", content="Unrelated weather note.", last_accessed=now),
    ]
    boosts = entity_boosts(
        "Tell me about Project Quasiflobber", records, ["Project Quasiflobber"])
    assert boosts["a"] == boosts["b"] > 0
    assert boosts.get("c", 0.0) == 0.0
    assert all(v <= 0.5 for v in boosts.values())
    # An entity absent from the query boosts nothing, even if in text.
    assert entity_boosts("weather today", records, ["Project Quasiflobber"]) == {}


# ---------------------------------------------------------------------------
# 3. ADHD prompt style
# ---------------------------------------------------------------------------

def test_adhd_style_enabled_on_off_and_invalid():
    assert adhd_style_enabled('{"adhdFriendly": true}') is True
    assert adhd_style_enabled('{"adhdFriendly": false}') is False
    assert adhd_style_enabled('{"other": true}') is False
    assert adhd_style_enabled(None) is False
    assert adhd_style_enabled("not json") is False


def test_adhd_style_application_prepends_and_does_not_mutate():
    messages = [{"role": "user", "content": "Explain this."}]
    out = apply_adhd_style_to_messages(messages)
    assert len(out) == 2
    assert out[0]["role"] == "system"
    assert out[0]["content"] == adhd_style_text()
    assert "Lead with the next action" in out[0]["content"]
    assert out[1] == messages[0]
    assert len(messages) == 1  # input untouched


def test_chat_route_wires_adhd_and_llm_extraction_post_response():
    src = (_ROOT / "mainfiles/backend/api_routes/chat_stream_routes.py").read_text()
    assert "apply_adhd_style_to_messages" in src
    assert "adhd_style_enabled" in src
    assert "graph_user_id" in src
    # LLM extraction is invoked after the post-response commit block,
    # i.e. after the "Memory++" fire-and-forget comment, not pre-stream.
    # (Search for the call with "(" so the top-of-file import, which
    # has no paren, does not count as the call site.)
    comment_idx = src.index("Memory++: fire-and-forget")
    assert src.index("extract_from_turn_llm_background(", comment_idx) > comment_idx


# Endpoint honesty: TestClient, same shape as the Batch 7 fixture.
def _api_client(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from backend.ratelimit_redis import reset_rate_limit_store_for_testing
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    reset_engine_for_testing()
    reset_rate_limit_store_for_testing()

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


@pytest.fixture
def client(tmp_path, monkeypatch):
    return _api_client(tmp_path, monkeypatch)


def _auth_headers(client):
    creds = {"username": "deepmem_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


def test_adhd_style_endpoint_reports_wired(client):
    h = _auth_headers(client)
    r = client.get("/api/quality/adhd-style", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["wired_into_chat"] is True
    assert body["wired_behind_setting"] == "adhdFriendly"
    assert body["style"] == adhd_style_text()
