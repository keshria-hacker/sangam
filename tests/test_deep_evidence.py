"""Wave-2 message-evidence persistence tests.

Proves the fix for the Wave-1 UX finding: POST /chats/{id}/messages
persisted only role/content and the messages table had no
tool_calls/citations/artifacts column, so reloaded chats lost evidence
and the Inspector only worked in-session.

Covers, TestClient only (no Playwright, no servers on shared ports):
1. Append endpoint: save a message carrying tool_calls/citations/
   artifacts -> GET /chats/{id} (reload) returns them verbatim.
2. Chat stream: a mocked canonical stream emitting tool/citation/
   artifact events -> the persisted assistant message carries that
   evidence, and reload returns it.
3. MessageOut serialization: ORM columns (including malformed JSON)
   map to the wire lists without breaking reload.
4. Frontend render path (unit-level, no browser here): the Devices
   module renders restart-hydrated pairings (code:null) as
   "approve by device name", and message_view.js normalizes persisted
   evidence shapes (object tool arguments, title-less citations)
   before rendering.

Pattern follows tests/test_batch7_writing_diagrams_images.py: fresh
SQLite DB per test file fixture, TestClient, register-then-use.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from backend.config import settings  # noqa: E402
from backend.database import Base, get_engine, reset_engine_for_testing  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.ratelimit_redis import reset_rate_limit_store_for_testing  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _api_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/evidence.db")
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
    creds = {"username": "ev_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


def _create_chat_row():
    """Insert a Chat row directly (avoids model resolution on POST /chats)."""
    from backend.database import AsyncSessionLocal
    from backend.models import Chat

    async def _go():
        async with AsyncSessionLocal() as db:
            chat = Chat(title="evidence chat", model="test-model")
            db.add(chat)
            await db.commit()
            await db.refresh(chat)
            return chat.id

    return asyncio.run(_go())


TOOL_CALL = {"id": "call-1", "name": "web_search", "arguments": '{"q": "x"}',
             "result": "result text", "status": "completed"}
CITATION = {"title": "Doc A", "url": "https://example.com/a", "text": "citation text"}
ARTIFACT = {"id": "art-1", "type": "code", "title": "Snippet", "content": "artifact body"}


# ------------------------------------------------------------------ append

def test_append_persists_evidence_and_reload_returns_it(client):
    h = _auth_headers(client)
    chat_id = _create_chat_row()
    r = client.post(f"/api/chats/{chat_id}/messages", json={"messages": [
        {"role": "user", "content": "search please"},
        {"role": "assistant", "content": "here it is",
         "tool_calls": [TOOL_CALL], "citations": [CITATION], "artifacts": [ARTIFACT]},
    ]}, headers=h)
    assert r.status_code == 200, r.text

    # Reload path: GET /chats/{id} must carry the evidence back.
    r = client.get(f"/api/chats/{chat_id}", headers=h)
    assert r.status_code == 200, r.text
    messages = r.json()["messages"]
    assert len(messages) == 2
    asst = next(m for m in messages if m["role"] == "assistant")
    assert asst["tool_calls"] == [TOOL_CALL]
    assert asst["citations"] == [CITATION]
    assert asst["artifacts"] == [ARTIFACT]
    # The user turn has no evidence: empty lists, not nulls or errors.
    user = next(m for m in messages if m["role"] == "user")
    assert user["tool_calls"] == [] and user["citations"] == [] and user["artifacts"] == []


def test_append_ignores_non_list_evidence(client):
    h = _auth_headers(client)
    chat_id = _create_chat_row()
    r = client.post(f"/api/chats/{chat_id}/messages", json={"messages": [
        {"role": "assistant", "content": "x", "tool_calls": "not-a-list",
         "citations": [CITATION, "junk-string"]},
    ]}, headers=h)
    assert r.status_code == 200, r.text
    r = client.get(f"/api/chats/{chat_id}", headers=h)
    asst = r.json()["messages"][0]
    assert asst["tool_calls"] == []  # non-list degrades to NULL -> []
    assert asst["citations"] == [CITATION]  # non-dict items dropped


# ------------------------------------------------------------- serialization

def test_message_out_maps_columns_and_tolerates_bad_json():
    import json as _json

    from backend.models import Message
    from backend.schemas import MessageOut

    from datetime import UTC, datetime

    # id/created_at defaults only apply on flush; set them explicitly
    # for this unflushed, pure-serialization check.
    msg = Message(id="msg-evidence1", chat_id="c", role="assistant", content="hi",
                  tool_calls_json=_json.dumps([TOOL_CALL]),
                  citations_json="this is not json",
                  artifacts_json=None,
                  created_at=datetime.now(UTC))
    out = MessageOut.model_validate(msg)
    assert out.tool_calls == [TOOL_CALL]
    assert out.citations == []  # malformed JSON never breaks reload
    assert out.artifacts == []


# ------------------------------------------------------------------- stream

def test_stream_persists_evidence_and_reload_returns_it(client, monkeypatch):
    """Mocked canonical stream -> persisted assistant message -> reload."""
    import backend.api_routes.chat_stream_routes as csr
    from backend.providers.base import ModelInfo
    from backend.response_events import ResponseEventBuilder, ResponseEventType

    h = _auth_headers(client)

    monkeypatch.setattr(
        csr.llm, "_resolve_model",
        lambda model_id: ModelInfo(id="test-model", name="Test", provider_id="test",
                                   provider_label="Test", litellm_id="gpt-4o",
                                   context_window=4096))

    async def _no_guidance(*args, **kwargs):
        return None

    monkeypatch.setattr(csr, "analyze_request", _no_guidance)

    async def _no_recall(*args, **kwargs):
        return []

    monkeypatch.setattr(csr, "recall", _no_recall)

    async def _never_summarize(*args, **kwargs):
        return False

    monkeypatch.setattr(csr, "should_summarize", _never_summarize)

    import backend.memory as memory_mod
    monkeypatch.setattr(memory_mod, "extract_from_turn_background", lambda *a, **k: None)
    monkeypatch.setattr(memory_mod, "extract_from_turn_llm_background", lambda *a, **k: None)

    async def _fake_stream(**kwargs):
        b = ResponseEventBuilder(provider="test", model="test-model",
                                 message_id="resp1", request_id="req1")
        yield b.message_start()
        for ev in b.text_delta("Hello evidence"):
            yield ev
        yield b.event(ResponseEventType.TOOL_START, content="",
                      metadata={"tool_call_id": "call-1", "name": "web_search",
                                "arguments": {"q": "x"}})
        yield b.event(ResponseEventType.TOOL_INPUT_DELTA, content="",
                      metadata={"tool_call_id": "call-1", "arguments": {"q": "x"}})
        yield b.event(ResponseEventType.TOOL_RESULT, content="result text",
                      metadata={"tool_call_id": "call-1", "name": "web_search"})
        yield b.event(ResponseEventType.CITATION, content="citation text",
                      metadata={"title": "Doc A", "url": "https://example.com/a"})
        yield b.event(ResponseEventType.ARTIFACT_START, content="artifact body",
                      metadata={"id": "art-1", "type": "code", "title": "Snippet"})
        yield b.event(ResponseEventType.ARTIFACT_END, content="artifact body",
                      metadata={"id": "art-1", "type": "code", "title": "Snippet"})
        end = b.text_end()
        if end is not None:
            yield end
        yield b.message_end()

    monkeypatch.setattr(csr.llm, "stream_response_events", _fake_stream)

    r = client.post("/api/chat/stream", json={
        "model": "test-model",
        "messages": [{"role": "user", "content": "search please"}],
    }, headers=h)
    assert r.status_code == 200, r.text
    assert "[DONE]" in r.text

    # chat_id is the first SSE frame; reload that chat and check evidence.
    chat_id = None
    for block in r.text.split("\n\n"):
        if "event: chat_id" in block:
            chat_id = block.split("data:", 1)[1].strip()
            break
    assert chat_id, r.text[:500]

    r = client.get(f"/api/chats/{chat_id}", headers=h)
    assert r.status_code == 200, r.text
    asst = next(m for m in r.json()["messages"] if m["role"] == "assistant")
    assert asst["content"] == "Hello evidence"
    tc = asst["tool_calls"]
    assert len(tc) == 1
    assert tc[0]["name"] == "web_search"
    assert tc[0]["arguments"] == '{"q": "x"}'  # dict args stored as a string
    assert tc[0]["result"] == "result text"
    assert tc[0]["status"] == "completed"
    assert any(c["title"] == "Doc A" for c in asst["citations"])
    assert any(a["title"] == "Snippet" and a["content"] == "artifact body"
               for a in asst["artifacts"])


# ------------------------------------------------------- frontend render path

def test_devices_renders_hydrated_pairing_by_device_name():
    src = (_ROOT / "mainfiles/frontend/js/features/settings/devices.js").read_text()
    assert "code unavailable after restart — approve by device name" in src
    # The old placeholder made a null code look like a hidden real code.
    assert "p.code || '••••••'" not in src


def test_message_view_normalizes_reloaded_evidence():
    src = (_ROOT / "mainfiles/frontend/js/features/chat/message_view.js").read_text()
    # Object tool arguments must not render as "[object Object]".
    assert "JSON.stringify(tc.arguments)" in src
    # Title-less citations fall back to label/text instead of blank "Source".
    assert "c.text.slice(0, 80)" in src
    # The assistant branch renders the normalized arrays, not the raw msg fields.
    assert "reloadToolCalls.length" in src
    assert "reloadCitations.length" in src
    assert "reloadArtifacts.length" in src
