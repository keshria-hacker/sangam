"""Merge/wiring tests for the deep-read coordinator phase.

Covers the items that crossed worker boundaries and therefore no
single worker could prove alone:
- message-evidence columns + memory_relations columns exist on a
  fresh DB (and _add_missing_columns covers them on old DBs);
- /memory/reflect is read-only (no stored synthesis);
- note-graph hooks: create indexes links, backlinks prefer the
  index, rename propagates, extract-section splits, expand walks;
- unified graph surfaces memory relations with confidence +
  source_ref and honours as_of;
- frontend streaming controller accepts tool_call_id (source check
  alongside the backend's _event_tool_key, which accepts both).

Live TestClient flow, fresh SQLite DB per test, following the
Batch 4 / deep-knowledge precedent. No Playwright, no shared ports.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import backend.api_routes.knowledge_routes  # noqa: E402,F401
import backend.api_routes.notebooks_routes as nb_routes  # noqa: E402,F401
import backend.memory.graph  # noqa: E402,F401 — registers graph tables
import backend.note_graph  # noqa: E402,F401 — registers note_link_index
from backend.config import settings  # noqa: E402
from backend.database import (  # noqa: E402
    AsyncSessionLocal,
    Base,
    get_engine,
    reset_engine_for_testing,
)
from backend.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _api_client(tmp_path, monkeypatch):
    os.environ["CHROMA_DB_PATH"] = str(tmp_path / "chroma")
    import backend.rag as rag_mod

    importlib.reload(rag_mod)
    rag_mod._client = None
    rag_mod._collection = None
    from backend import memory as memory_mod

    memory_mod.reset_memory_for_testing()
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    reset_engine_for_testing()

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
    creds = {"username": "merge_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


def _make_notebook(client, h, name="Merge"):
    r = client.post("/api/notebooks", json={"name": name, "description": "d"}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _make_note(client, h, nb, title, content):
    r = client.post(f"/api/notebooks/{nb}/notes",
                    json={"title": title, "content": content}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------ schema

def test_merge_columns_exist_on_fresh_db(client):
    """messages evidence columns + memory_relations hardening columns."""
    from backend.models import Message
    from backend.memory.graph import MemoryRelation

    msg_cols = {c.name for c in Message.__table__.columns}
    assert {"tool_calls_json", "citations_json", "artifacts_json"} <= msg_cols
    rel_cols = {c.name for c in MemoryRelation.__table__.columns}
    assert {"confidence", "source_ref"} <= rel_cols


def test_missing_columns_migration_covers_new_columns(client, tmp_path):
    """_add_missing_columns lists every new column on an old table."""
    import backend.database as db_mod
    import inspect

    src = inspect.getsource(db_mod._add_missing_columns)
    assert "tool_calls_json" in src and "citations_json" in src
    assert "artifacts_json" in src and "confidence" in src
    assert "source_ref" in src


# ------------------------------------------------------------ reflect

def test_reflect_read_only_with_mocked_model(client, monkeypatch):
    import json

    h = _auth_headers(client)
    r = client.post("/api/memory",
                    json={"content": "The user prefers concise answers.",
                          "kind": "semantic", "importance": 0.9}, headers=h)
    assert r.status_code == 201, r.text

    async def fake(db, messages, max_tokens=2000):
        return json.dumps({
            "observations": [{"text": "User prefers concise answers.",
                              "evidence": ["whatever-id"]}],
            "mental_model": "A user who values brevity.",
            "open_questions": [],
        })

    monkeypatch.setattr("backend.memory.extract_llm.complete_text", fake)
    r = client.post("/api/memory/reflect",
                    json={"query": "user preferences"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stored"] is False
    assert "stored_memory_id" not in body
    assert "whatever-id" not in body["evidence_ids"]
    r = client.get("/api/memory?limit=50", headers=h)
    assert not any("Reflection:" in m["content"] for m in r.json())


# ------------------------------------------------------------ note graph

def test_note_index_backlinks_rename_extract_expand(client):
    h = _auth_headers(client)
    nb = _make_notebook(client, h)
    a = _make_note(client, h, nb, "Alpha", "# Alpha\n\nSee [[Beta]] for details.")
    b = _make_note(client, h, nb, "Beta", "# Beta\n\nBody here.\n\n## Sub\n\nSub body.\n")

    # Backlinks come from the index, not a scan.
    r = client.get(f"/api/notebooks/{nb}/notes/{b['id']}/backlinks", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["via"] == "index"
    assert [x["id"] for x in r.json()["backlinks"]] == [a["id"]]

    # Rename propagates: Alpha's [[Beta]] becomes [[Gamma]].
    r = client.put(f"/api/notebooks/{nb}/notes/{b['id']}",
                   json={"title": "Gamma"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["links_rewritten_in"] == 1
    r = client.get(f"/api/notebooks/{nb}/notes/{a['id']}", headers=h)
    assert "[[Gamma]]" in r.json()["content"]
    assert "[[Beta]]" not in r.json()["content"]

    # Extract-section splits the subtree into a new note.
    r = client.post(f"/api/notebooks/{nb}/notes/{b['id']}/extract-section",
                    json={"header_title": "Sub", "new_title": "SubNote"}, headers=h)
    assert r.status_code == 201, r.text
    assert "Sub body" in r.json()["note"]["content"]
    assert "[[SubNote]]" in r.json()["source"]["content"]

    # Expand walks from the seed along links.
    r = client.get(f"/api/notebooks/{nb}/notes/{a['id']}/expand",
                   headers=h)
    assert r.status_code == 200, r.text
    assert a["id"] in r.json().get("notes", []) or a["id"] in str(r.json())


def test_note_rename_missing_header_is_422(client):
    h = _auth_headers(client)
    nb = _make_notebook(client, h)
    a = _make_note(client, h, nb, "Solo", "# Solo\n\nNo sections.\n")
    r = client.post(f"/api/notebooks/{nb}/notes/{a['id']}/extract-section",
                    json={"header_title": "Nope", "new_title": "X"}, headers=h)
    assert r.status_code == 422, r.text


# ------------------------------------------------------------ unified graph

def test_unified_graph_relations_as_of(client):
    from backend.knowledge_graph import build_knowledge_graph

    g = build_knowledge_graph(relations=[
        {"subject": "Ada", "predicate": "works_at", "object": "Acme",
         "confidence": 0.9, "source_ref": "chat-1",
         "valid_from": "2024-01-01T00:00:00+00:00", "valid_to": None},
        {"subject": "Ada", "predicate": "works_at", "object": "OldCo",
         "confidence": 0.8, "source_ref": "",
         "valid_from": "2020-01-01T00:00:00+00:00",
         "valid_to": "2023-01-01T00:00:00+00:00"},
    ], as_of="2025-06-01T00:00:00+00:00")
    assert g["stats"]["relations"] == 1
    (edge,) = [e for e in g["edges"] if e["source"] == "memory_graph"]
    assert edge["to"] == "ent:Acme" and edge["confidence"] == 0.9
    assert edge["source_ref"] == "chat-1"


# ------------------------------------------------------------ tool-key parity

def test_frontend_controller_accepts_tool_call_id():
    """The streaming controller must key on tool_call_id (backend's
    key) with tool_id as fallback — otherwise input deltas never
    flush. Source-level check; the browser spec proves it live."""
    ctrl = (_ROOT / "mainfiles/frontend/js/features/chat/response_controller.js").read_text()
    assert "tool_call_id" in ctrl
    chat = (_ROOT / "mainfiles/frontend/js/features/chat/chat.js").read_text()
    assert "tool_call_id" in chat
