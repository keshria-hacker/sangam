"""Batch 4 (Memory V2 + Research Notebooks) tests.

Covers: relation supersede windows + timeline order, verbatim
transcripts beyond the 2000-char extracted-memory cap, PATCH-style
memory update, notebook context modes, wiki-link backlinks, transform
stored as transform + note (model mocked), reflect with no model ->
503 (never fake content), extract with unparseable model output ->
empty facts (never invented), entities/extract heuristic fallback,
and notes/from-chat 404.

Live TestClient flow (register -> Bearer headers), fresh SQLite DB +
fresh ChromaDB dir per test, following the Batch 2 test precedent.
No real model calls: complete_text is patched where a model response
is needed; the 503 test deliberately runs unpatched.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import backend.api_routes.memory_v2_routes  # noqa: E402,F401 — registers tables
import backend.api_routes.notebooks_routes  # noqa: E402,F401 — registers tables
from backend.config import settings  # noqa: E402
from backend.database import Base, get_engine, reset_engine_for_testing  # noqa: E402
from backend.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _api_client(tmp_path, monkeypatch):
    # Fresh ChromaDB: rag reads CHROMA_DB_PATH at import, so reload it
    # after rebinding the env var (in-place reload keeps other modules'
    # references valid) and drop the cached handles.
    os.environ["CHROMA_DB_PATH"] = str(tmp_path / "chroma")
    import backend.rag as rag_mod
    importlib.reload(rag_mod)
    rag_mod._client = None
    rag_mod._collection = None
    from backend import memory as memory_mod
    memory_mod.reset_memory_for_testing()

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/b4.db")
    reset_engine_for_testing()

    import asyncio

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
    creds = {"username": "b4_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


def _mock_complete(monkeypatch, output):
    async def fake(db, messages, max_tokens=2000):
        return output
    monkeypatch.setattr("backend.memory.extract_llm.complete_text", fake)


def _llm_json(facts=(), entities=(), relations=()):
    import json
    return json.dumps({"facts": list(facts), "entities": list(entities),
                       "relations": list(relations)})


# ------------------------------------------------------- graph / timeline

def test_relation_supersede_closes_old_window_and_timeline_order(client, monkeypatch):
    with client:
        h = _auth_headers(client)
        rel1 = {"subject": "Ada", "predicate": "works_at", "object": "Acme"}
        _mock_complete(monkeypatch, _llm_json(relations=[rel1]))
        r = client.post("/api/memory/entities/extract",
                        json={"text": "Ada works at Acme."}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["model_used"] is True

        rel2 = {"subject": "Ada", "predicate": "works_at", "object": "Beta"}
        _mock_complete(monkeypatch, _llm_json(relations=[rel2]))
        r = client.post("/api/memory/entities/extract",
                        json={"text": "Ada now works at Beta."}, headers=h)
        assert r.status_code == 200, r.text

        r = client.get("/api/memory/entities/Ada/timeline", headers=h)
        assert r.status_code == 200, r.text
        rels = r.json()["relations"]
        # Open + closed both shown, oldest first.
        assert [x["object"] for x in rels] == ["Acme", "Beta"]
        old, new = rels
        assert old["open"] is False and old["valid_to"] is not None
        assert old["superseded_by"] == new["id"]
        assert new["open"] is True and new["valid_to"] is None
        # Re-adding the identical triple is a no-op, not a new window.
        _mock_complete(monkeypatch, _llm_json(relations=[rel2]))
        client.post("/api/memory/entities/extract",
                    json={"text": "Ada works at Beta."}, headers=h)
        r = client.get("/api/memory/entities/Ada/timeline", headers=h)
        assert len(r.json()["relations"]) == 2
        # Entities list contains Ada.
        r = client.get("/api/memory/entities", headers=h)
        assert any(e["name"] == "Ada" for e in r.json()["entities"])
        # Unknown entity timeline -> 404.
        assert client.get("/api/memory/entities/Nobody/timeline", headers=h).status_code == 404


def test_entities_extract_heuristic_fallback_without_model(client):
    # Unpatched: no provider keys in the fresh DB, so no model is
    # configured. The fallback must say so and only yield Capitalized
    # phrases — never fake LLM output.
    with client:
        h = _auth_headers(client)
        r = client.post("/api/memory/entities/extract",
                        json={"text": "Planning the Mount Everest Expedition with the team."},
                        headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["model_used"] is False
        assert body["fallback"] == "heuristic-capitalized"
        names = [e["name"] for e in body["entities"]]
        assert "Mount Everest Expedition" in names
        assert body["relations"] == []


# ------------------------------------------------------------ transcripts

def test_transcript_stores_full_text_beyond_2000_chars(client):
    with client:
        h = _auth_headers(client)
        long_text = "x" * 3000 + " UNIQUE-TAIL-MARKER"
        r = client.post("/api/memory/transcripts",
                        json={"chat_id": "chat1", "role": "user", "text": long_text},
                        headers=h)
        assert r.status_code == 201, r.text
        transcript_id = r.json()["id"]
        r = client.get("/api/memory/transcripts?chat_id=chat1", headers=h)
        assert r.status_code == 200, r.text
        rows = r.json()["transcripts"]
        assert len(rows) == 1
        assert rows[0]["text"] == long_text
        assert rows[0]["text"].endswith("UNIQUE-TAIL-MARKER")
        # Bad role is rejected, not stored.
        r = client.post("/api/memory/transcripts",
                        json={"chat_id": "chat1", "role": "system", "text": "hi"},
                        headers=h)
        assert r.status_code == 422
        r = client.get("/api/memory/transcripts?chat_id=other", headers=h)
        assert r.json()["transcripts"] == []


def test_extract_from_transcript_id(client, monkeypatch):
    with client:
        h = _auth_headers(client)
        r = client.post("/api/memory/transcripts",
                        json={"chat_id": "chat9", "role": "user",
                              "text": "The user prefers concise answers."}, headers=h)
        tid = r.json()["id"]
        _mock_complete(monkeypatch, _llm_json(
            facts=["The user prefers concise answers."]))
        r = client.post("/api/memory/extract", json={"transcript_id": tid}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["facts"] == ["The user prefers concise answers."]
        assert len(r.json()["saved"]) == 1
        # Unknown transcript -> 404, not an empty extraction.
        r = client.post("/api/memory/extract", json={"transcript_id": "tr-nope"}, headers=h)
        assert r.status_code == 404
        # Neither text nor transcript -> 422.
        r = client.post("/api/memory/extract", json={}, headers=h)
        assert r.status_code == 422


def test_extract_unparseable_model_output_returns_empty_facts(client, monkeypatch):
    with client:
        h = _auth_headers(client)
        _mock_complete(monkeypatch, "this is not json {{{ garbage")
        r = client.post("/api/memory/extract",
                        json={"text": "Ada likes tea."}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        # Never invented: no facts, nothing saved, despite model "output".
        assert body["facts"] == [] and body["saved"] == []
        assert body["entities"] == [] and body["relations"] == []
        assert body["model_used"] is True


# --------------------------------------------------------- memory update

def test_memory_update_changes_content_keeps_other_fields(client):
    with client:
        h = _auth_headers(client)
        r = client.post("/api/memory",
                        json={"content": "Original fact.", "kind": "semantic",
                              "importance": 0.8, "room": "work", "drawer": "notes"},
                        headers=h)
        assert r.status_code == 201, r.text
        mem_id = r.json()["id"]
        # Content-only update: kind/importance/room/drawer preserved.
        r = client.put(f"/api/memory/{mem_id}",
                       json={"content": "Corrected fact."}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["content"] == "Corrected fact."
        assert body["kind"] == "semantic"
        assert body["importance"] == 0.8
        assert body["room"] == "work" and body["drawer"] == "notes"
        # Importance-only update keeps content.
        r = client.put(f"/api/memory/{mem_id}", json={"importance": 0.3}, headers=h)
        assert r.status_code == 200
        assert r.json()["content"] == "Corrected fact."
        assert r.json()["importance"] == 0.3
        # Unknown memory -> 404.
        assert client.put("/api/memory/nope123", json={"content": "x"}, headers=h).status_code == 404


# --------------------------------------------------------------- reflect

def test_reflect_without_model_returns_503_not_fake(client):
    # Unpatched, fresh DB: no model configured -> 503, plain message.
    with client:
        h = _auth_headers(client)
        r = client.post("/api/memory/reflect",
                        json={"query": "what do we know about the user?"}, headers=h)
        assert r.status_code == 503, r.text
        assert "model" in r.text.lower()
        # Nothing stored as a fake reflection.
        r = client.get("/api/memory?limit=50", headers=h)
        assert not any("Reflection:" in m["content"] for m in r.json())


def test_reflect_with_mocked_model_is_read_only(client, monkeypatch):
    # Deep-read Wave-2: reflect must NOT write its synthesis as a memory
    # (that polluted recall with its own output). It returns evidence,
    # proof counts, and trend with stored=False.
    import json
    with client:
        h = _auth_headers(client)
        r = client.post("/api/memory",
                        json={"content": "The user prefers concise answers.",
                              "kind": "semantic", "importance": 0.9}, headers=h)
        assert r.status_code == 201, r.text
        _mock_complete(monkeypatch, json.dumps({
            "observations": [{"text": "User prefers concise answers.",
                              "evidence": ["whatever-id"]}],
            "mental_model": "A user who values brevity.",
            "open_questions": ["Does brevity apply to code too?"],
        }))
        r = client.post("/api/memory/reflect",
                        json={"query": "user preferences"}, headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mental_model"] == "A user who values brevity."
        assert body["open_questions"] == ["Does brevity apply to code too?"]
        # Evidence is filtered to actually-recalled ids: the mock's
        # invented id must not survive.
        assert "whatever-id" not in body["evidence_ids"]
        assert body["stored"] is False
        assert "stored_memory_id" not in body
        # Nothing new was stored by the reflection.
        r = client.get("/api/memory?limit=50", headers=h)
        assert not any("Reflection:" in m["content"] for m in r.json())


# -------------------------------------------------------------- notebooks

def _make_notebook(client, h, name="Research"):
    r = client.post("/api/notebooks", json={"name": name, "description": "d"}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_notebook_context_modes(client):
    with client:
        h = _auth_headers(client)
        nb = _make_notebook(client, h)
        # A note to reference as a note-kind source.
        r = client.post(f"/api/notebooks/{nb}/notes",
                        json={"title": "SourceNote", "content": "FULL-NOTE-CONTENT-0123456789"}, headers=h)
        assert r.status_code == 201, r.text
        note_id = r.json()["id"]
        # Excluded URL source: must be absent from retrieve output.
        r = client.post(f"/api/notebooks/{nb}/sources",
                        json={"kind": "url", "ref": "https://example.com/hidden",
                              "context_mode": "excluded"}, headers=h)
        assert r.status_code == 201, r.text
        # Summary note-kind source with stored summary text.
        r = client.post(f"/api/notebooks/{nb}/sources",
                        json={"kind": "note", "ref": note_id,
                              "context_mode": "summary",
                              "summary_text": "SUMMARY-OF-NOTE"}, headers=h)
        assert r.status_code == 201, r.text
        summary_source_id = r.json()["id"]
        # Full note-kind source.
        r = client.post(f"/api/notebooks/{nb}/sources",
                        json={"kind": "note", "ref": note_id, "context_mode": "full"},
                        headers=h)
        assert r.status_code == 201, r.text
        # Bad context mode rejected; bad source ref rejected.
        r = client.put(f"/api/notebooks/{nb}/sources/{summary_source_id}/context",
                       json={"context_mode": "everything"}, headers=h)
        assert r.status_code == 422
        r = client.post(f"/api/notebooks/{nb}/sources",
                        json={"kind": "file", "ref": "missing-file-id"}, headers=h)
        assert r.status_code == 404
        r = client.post(f"/api/notebooks/{nb}/sources",
                        json={"kind": "url", "ref": "not-a-url"}, headers=h)
        assert r.status_code == 422

        r = client.get(f"/api/notebooks/{nb}/retrieve?q=note", headers=h)
        assert r.status_code == 200, r.text
        ctx = r.json()["context"]
        by_source = {e.get("source_id"): e for e in ctx if e.get("source_id")}
        assert "https://example.com/hidden" not in [e.get("ref") for e in ctx]
        summary_entry = by_source[summary_source_id]
        assert summary_entry["mode"] == "summary"
        assert summary_entry["text"] == "SUMMARY-OF-NOTE"
        full_entries = [e for e in ctx if e.get("mode") == "full"
                        and e.get("text") == "FULL-NOTE-CONTENT-0123456789"]
        assert full_entries
        # Switching the summary source to excluded removes it.
        r = client.put(f"/api/notebooks/{nb}/sources/{summary_source_id}/context",
                       json={"context_mode": "excluded"}, headers=h)
        assert r.status_code == 200, r.text
        r = client.get(f"/api/notebooks/{nb}/retrieve?q=note", headers=h)
        by_source = {e.get("source_id"): e for e in r.json()["context"] if e.get("source_id")}
        assert summary_source_id not in by_source
        # Retrieve on a missing notebook -> 404.
        assert client.get("/api/notebooks/nb-nope/retrieve?q=x", headers=h).status_code == 404


def test_notebook_summary_extractive_fallback_labelled(client):
    with client:
        h = _auth_headers(client)
        nb = _make_notebook(client, h)
        body = "A" * 600
        r = client.post(f"/api/notebooks/{nb}/notes",
                        json={"title": "LongNote", "content": body}, headers=h)
        note_id = r.json()["id"]
        # Summary mode WITHOUT stored summary_text -> first 500 chars,
        # labelled as an extractive fallback.
        r = client.post(f"/api/notebooks/{nb}/sources",
                        json={"kind": "note", "ref": note_id, "context_mode": "summary"},
                        headers=h)
        source_id = r.json()["id"]
        r = client.get(f"/api/notebooks/{nb}/retrieve?q=long", headers=h)
        entries = [e for e in r.json()["context"] if e.get("source_id") == source_id]
        assert len(entries) == 1
        assert entries[0]["text"] == "A" * 500
        assert "extractive fallback" in (entries[0].get("note") or "")


def test_wiki_link_backlinks_and_outgoing_links(client):
    with client:
        h = _auth_headers(client)
        nb = _make_notebook(client, h)
        r = client.post(f"/api/notebooks/{nb}/notes",
                        json={"title": "Alpha", "content": "Root note."}, headers=h)
        a_id = r.json()["id"]
        r = client.post(f"/api/notebooks/{nb}/notes",
                        json={"title": "Beta", "content": "See [[Alpha]] for context."}, headers=h)
        b_id = r.json()["id"]
        assert r.json()["outgoing_links"] == ["Alpha"]
        # B links [[Alpha]] -> A's backlinks include B.
        r = client.get(f"/api/notebooks/{nb}/notes/{a_id}/backlinks", headers=h)
        assert r.status_code == 200, r.text
        assert [b["id"] for b in r.json()["backlinks"]] == [b_id]
        # A links nothing -> B's backlinks are empty.
        r = client.get(f"/api/notebooks/{nb}/notes/{b_id}/backlinks", headers=h)
        assert r.json()["backlinks"] == []
        # Single-note read exposes outgoing links.
        r = client.get(f"/api/notebooks/{nb}/notes/{b_id}", headers=h)
        assert r.json()["outgoing_links"] == ["Alpha"]


def test_note_from_chat_404_and_transform_stores_note(client, monkeypatch):
    with client:
        h = _auth_headers(client)
        nb = _make_notebook(client, h)
        # Unknown chat -> 404, not an empty note.
        r = client.post(f"/api/notebooks/{nb}/notes/from-chat",
                        json={"chat_id": "no-such-chat"}, headers=h)
        assert r.status_code == 404, r.text
        # Transform with a mocked model: stored as transform AND note.
        client.post(f"/api/notebooks/{nb}/notes",
                    json={"title": "Seed", "content": "Seed content here."}, headers=h)
        _mock_complete(monkeypatch, "TRANSFORMED-OUTPUT-123")
        r = client.post(f"/api/notebooks/{nb}/transforms",
                        json={"name": "Key insights", "prompt": "Summarize."}, headers=h)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["transform"]["output"] == "TRANSFORMED-OUTPUT-123"
        assert body["note"]["content"] == "TRANSFORMED-OUTPUT-123"
        assert body["note"]["title"] == "Key insights"
        r = client.get(f"/api/notebooks/{nb}/transforms", headers=h)
        assert any(t["output"] == "TRANSFORMED-OUTPUT-123" for t in r.json()["transforms"])
        r = client.get(f"/api/notebooks/{nb}/notes", headers=h)
        assert any(n["content"] == "TRANSFORMED-OUTPUT-123" for n in r.json()["notes"])
        # Transform without a model -> 503, nothing stored.
        _mock_complete(monkeypatch, None)
        # (None return simulates "no model configured" at the seam.)
        r = client.post(f"/api/notebooks/{nb}/transforms",
                        json={"name": "Second", "prompt": "Summarize."}, headers=h)
        assert r.status_code == 503, r.text


def test_notebook_crud_and_delete(client):
    with client:
        h = _auth_headers(client)
        nb = _make_notebook(client, h, name="ToRename")
        r = client.put(f"/api/notebooks/{nb}", json={"name": "Renamed"}, headers=h)
        assert r.status_code == 200 and r.json()["name"] == "Renamed"
        r = client.get("/api/notebooks", headers=h)
        assert any(n["id"] == nb for n in r.json()["notebooks"])
        r = client.delete(f"/api/notebooks/{nb}", headers=h)
        assert r.status_code == 200, r.text
        assert client.get(f"/api/notebooks/{nb}", headers=h).status_code == 404
