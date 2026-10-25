"""A3 (perfect-flow Projects, Memory & Knowledge) tests.

Covers, with a real TestClient app and a fresh temp SQLite DB per test:
- project CRUD, soft-delete, hard-delete unlink semantics
- instruction versioning (new save supersedes the current one)
- project sources incl. URL ingest-on-add (fetch mocked, no network)
- project tasks REUSE the goals Task system (no second task table)
- project chats scoped per project
- THE SCOPING PROOF: same prompt in two projects with different
  instructions/sources yields project-scoped context, and project
  retrieve only ever passes that project's own file ids to hybrid
  retrieval (asserted on the mock's call args, not on Chroma)
- hybrid citations carry provenance "verified"; graph edges carry
  "inferred"; knowledge-graph backlinks reverse index
- notebook URL source returns its own text from retrieve, and a
  source added while excluded gains its text when switched to full
- memory privacy dashboard shape + retention preview
- chat-stream file path now uses hybrid retrieval (wiring guard)
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


def _api_client(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/a3.db")
    reset_engine_for_testing()
    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth(client, username="a3_user"):
    creds = {"username": username, "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def _project(client, h, name="Alpha", scope="project"):
    r = client.post("/api/projects", json={"name": name, "memory_scope": scope}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _url_source(client, h, project_id, url, fetch_text):
    """Add a URL source with the notebook fetch + indexer mocked."""
    with patch("backend.api_routes.notebooks_routes.fetch_page_text",
               new=AsyncMock(return_value=(fetch_text, "text/html"))), \
         patch("backend.rag.index_document", return_value=1):
        r = client.post(f"/api/projects/{project_id}/sources",
                        json={"kind": "url", "ref": url, "context_mode": "full"}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ projects

def test_project_crud_soft_delete_and_hard_unlink(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    p = _project(client, h, "Alpha")
    pid = p["id"]
    r = client.put(f"/api/projects/{pid}", json={"description": "d1"}, headers=h)
    assert r.status_code == 200 and r.json()["description"] == "d1"
    r = client.post(f"/api/projects/{pid}/tasks", json={"title": "Keep me"}, headers=h)
    assert r.status_code == 201, r.text
    task_id = r.json()["id"]
    # Soft delete: hidden from list + detail, task still exists globally.
    r = client.delete(f"/api/projects/{pid}", headers=h)
    assert r.status_code == 200 and r.json()["hard"] is False
    assert client.get("/api/projects", headers=h).json()["projects"] == []
    assert client.get(f"/api/projects/{pid}", headers=h).status_code == 404
    # Hard delete unlinks (never deletes) tasks: task survives, project_id None.
    r = client.delete(f"/api/projects/{pid}?hard=true", headers=h)
    assert r.status_code == 200 and r.json()["hard"] is True
    tasks = client.get("/api/tasks?open_only=false", headers=h).json()["tasks"]
    mine = [t for t in tasks if t["id"] == task_id]
    assert len(mine) == 1 and mine[0]["project_id"] is None


def test_instructions_versioned_current_wins(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    pid = _project(client, h)["id"]
    client.post(f"/api/projects/{pid}/instructions", json={"content": "v1 rules"}, headers=h)
    client.post(f"/api/projects/{pid}/instructions", json={"content": "v2 rules"}, headers=h)
    data = client.get(f"/api/projects/{pid}/instructions", headers=h).json()
    assert data["current"]["content"] == "v2 rules"
    assert len(data["history"]) == 2
    assert sum(1 for row in data["history"] if row["is_current"]) == 1
    home = client.get(f"/api/projects/{pid}", headers=h).json()
    assert home["instruction"] == "v2 rules"


def test_project_tasks_reuse_goals_task_system(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    pid = _project(client, h)["id"]
    r = client.post(f"/api/projects/{pid}/tasks",
                    json={"title": "Ship it", "priority": "high"}, headers=h)
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["project_id"] == pid and task["goal_id"] is None
    assert task["status"] == "backlog" and task["status_version"] == 0
    r = client.patch(f"/api/projects/{pid}/tasks/{task['id']}",
                     json={"status": "done"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "done" and r.json()["status_version"] == 1
    # Unknown status is a 422, not a silent accept.
    assert client.patch(f"/api/projects/{pid}/tasks/{task['id']}",
                        json={"status": "teleported"}, headers=h).status_code == 422
    # A task from another project cannot be patched through this one.
    pid2 = _project(client, h, "Beta")["id"]
    assert client.patch(f"/api/projects/{pid2}/tasks/{task['id']}",
                        json={"status": "todo"}, headers=h).status_code == 404


def test_project_chats_scoped_per_project(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    a = _project(client, h, "A")["id"]
    b = _project(client, h, "B")["id"]
    client.post(f"/api/projects/{a}/chats", json={"title": "chat-a"}, headers=h)
    client.post(f"/api/projects/{b}/chats", json={"title": "chat-b"}, headers=h)
    chats_a = client.get(f"/api/projects/{a}/chats", headers=h).json()["chats"]
    assert [c["title"] for c in chats_a] == ["chat-a"]
    assert all(c["project_id"] == a for c in chats_a)


def test_project_source_dedupe_and_unknown_refs(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    pid = _project(client, h)["id"]
    s1 = _url_source(client, h, pid, "https://example.com/guide", "Guide text here.")
    s2 = _url_source(client, h, pid, "https://example.com/guide/", "Guide text here.")
    assert s1["id"] == s2["id"]  # same normalized URL -> same row
    assert s1["ingest_status"] == "ingested" and s1["file_id"]
    assert client.post(f"/api/projects/{pid}/sources",
                       json={"kind": "file", "ref": "nope"}, headers=h).status_code == 404
    assert client.post(f"/api/projects/{pid}/sources",
                       json={"kind": "url", "ref": "ftp://example.com/x"}, headers=h).status_code == 422


# ------------------------------------------------------------- scoping proof

def test_project_scoping_no_cross_project_leak(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    a = _project(client, h, "Alpha")["id"]
    b = _project(client, h, "Beta")["id"]
    client.post(f"/api/projects/{a}/instructions", json={"content": "ALPHA-ONLY-RULE"}, headers=h)
    client.post(f"/api/projects/{b}/instructions", json={"content": "BETA-ONLY-RULE"}, headers=h)
    src_a = _url_source(client, h, a, "https://example.com/alpha-page", "ALPHA-SOURCE-TEXT zebras")
    src_b = _url_source(client, h, b, "https://example.com/beta-page", "BETA-SOURCE-TEXT quokkas")

    # Context without a query: stored texts only, strictly per project.
    ctx_a = client.get(f"/api/projects/{a}/context", headers=h).json()
    ctx_b = client.get(f"/api/projects/{b}/context", headers=h).json()
    assert ctx_a["instruction"] == "ALPHA-ONLY-RULE"
    assert ctx_b["instruction"] == "BETA-ONLY-RULE"
    assert any("ALPHA-SOURCE-TEXT" in (e.get("text") or "") for e in ctx_a["sources"])
    assert not any("BETA-SOURCE-TEXT" in (e.get("text") or "") for e in ctx_a["sources"])
    assert any("BETA-SOURCE-TEXT" in (e.get("text") or "") for e in ctx_b["sources"])
    assert not any("ALPHA-SOURCE-TEXT" in (e.get("text") or "") for e in ctx_b["sources"])

    # Retrieve: the file_ids handed to hybrid retrieval must be exactly
    # the calling project's own — asserted on the mock call args.
    seen_calls: list[list[str]] = []

    def _fake_hybrid(query, file_ids, top_k=5):
        seen_calls.append(list(file_ids))
        tag = "ALPHA" if src_a["file_id"] in file_ids else "BETA"
        return [{"text": f"{tag} chunk", "filename": "x.txt",
                 "citation": {"file_id": file_ids[0], "filename": "x.txt",
                              "chunk_index": 0, "excerpt": f"{tag} chunk"}}]

    with patch("backend.rag.retrieve_hybrid_chunks", side_effect=_fake_hybrid):
        ra = client.get(f"/api/projects/{a}/retrieve", params={"q": "zebras"}, headers=h).json()
        rb = client.get(f"/api/projects/{b}/retrieve", params={"q": "quokkas"}, headers=h).json()
    assert seen_calls[0] == [src_a["file_id"]]
    assert seen_calls[1] == [src_b["file_id"]]
    assert ra["results"][0]["text"] == "ALPHA chunk"
    assert rb["results"][0]["text"] == "BETA chunk"
    assert ra["results"][0]["citation"]["provenance"] == "verified"
    assert ra["results"][0]["citation"]["grade"] == ra["grade"]


# ------------------------------------------------------- hybrid + graph units

def test_hybrid_citation_provenance_verified():
    from backend.hybrid_retrieval import hybrid_rank

    out = hybrid_rank(
        "zebras",
        [{"id": "f_0", "text": "zebras roam the savanna", "filename": "a.txt",
          "file_id": "f", "chunk_index": 0, "vector_score": 0.1}],
        [{"id": "f_0", "text": "zebras roam the savanna", "filename": "a.txt",
          "file_id": "f", "chunk_index": 0}],
        top_k=1)
    assert len(out) == 1
    assert out[0]["citation"]["provenance"] == "verified"
    assert out[0]["citation"]["file_id"] == "f"
    assert out[0]["citation"]["chunk_index"] == 0


def test_knowledge_graph_backlinks_reverse_index():
    from backend.knowledge_graph import build_knowledge_graph

    graph = build_knowledge_graph(
        memories=[], documents=[], chats=[],
        relations=[{"subject": "Ada", "predicate": "works_on",
                    "object": "Sangam", "confidence": 0.9,
                    "source_ref": "test"}])
    assert "ent:Ada" in graph["backlinks"].get("ent:Sangam", [])
    assert graph["backlinks"].get("ent:Ada", []) == []


def test_knowledge_retrieve_provenance_and_graph_expansion(tmp_path, monkeypatch):
    import asyncio

    from backend.api_routes.knowledge_routes import graph_expansion_for_query

    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)

    # Seed one uploaded file so retrieve has ids to search (otherwise
    # it short-circuits to [] before hybrid is ever called).
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
    mock_resp.content = b"<html><body><p>Seed document.</p></body></html>"
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_resp
    with patch("httpx.AsyncClient", return_value=mock_client), \
         patch("backend.ingest_url.socket.getaddrinfo",
               return_value=[(2, None, None, None, ("93.184.216.34", 0))]):
        r = client.post("/api/knowledge/ingest-url",
                        json={"url": "https://example.com/seed-doc"}, headers=h)
    assert r.status_code == 200, r.text

    def _fake_hybrid(query, file_ids, top_k=5):
        return [{"text": "grounded chunk", "filename": "g.txt",
                 "citation": {"file_id": "f1", "filename": "g.txt",
                              "chunk_index": 0, "excerpt": "grounded chunk"}}]

    with patch("backend.rag.retrieve_hybrid_chunks", side_effect=_fake_hybrid):
        body = client.get("/api/knowledge/retrieve", params={"q": "grounded"}, headers=h).json()
    assert body["results"][0]["citation"]["provenance"] == "verified"
    assert body["results"][0]["citation"]["grade"] == body["grade"]
    assert body["graph_expansion"] == []  # no relations seeded -> empty, not invented

    # Graph expansion: a relation whose entity tokens appear in the
    # query is returned, labelled inferred, one hop, best-effort.
    row = MagicMock()
    row.id = "rel-1"
    row.subject = "Ada Lovelace"
    row.predicate = "works_on"
    row.object = "Analytical Engine"
    row.valid_from = None
    row.valid_to = None
    row.superseded_by = None
    row.confidence = 0.9
    row.source_ref = "test"

    async def _run():
        with patch("backend.memory.graph.query_as_of", new=AsyncMock(return_value=[row])):
            return await graph_expansion_for_query(MagicMock(), "u1", "ada lovelace engine")

    expansion = asyncio.run(_run())
    assert len(expansion) == 1
    assert expansion[0]["provenance"] == "inferred"
    assert expansion[0]["subject"] == "Ada Lovelace"


# ----------------------------------------------------------------- notebooks

def test_notebook_url_source_returns_own_text(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    nb = client.post("/api/notebooks", json={"name": "NB"}, headers=h).json()
    with patch("backend.api_routes.notebooks_routes.fetch_page_text",
               new=AsyncMock(return_value=("UNIQUE-NOTEBOOK-PAGE-TEXT about kelp", "text/html"))), \
         patch("backend.rag.index_document", return_value=1):
        r = client.post(f"/api/notebooks/{nb['id']}/sources",
                        json={"kind": "url", "ref": "https://example.com/kelp",
                              "context_mode": "full"}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["ingest_status"] == "ingested"
    body = client.get(f"/api/notebooks/{nb['id']}/retrieve",
                      params={"q": "kelp"}, headers=h).json()
    texts = [e.get("text", "") for e in body["context"]]
    assert any("UNIQUE-NOTEBOOK-PAGE-TEXT" in t for t in texts)


def test_notebook_excluded_then_full_ingests_on_unexclude(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    nb = client.post("/api/notebooks", json={"name": "NB2"}, headers=h).json()
    fetch = AsyncMock(return_value=("RESTORED-TEXT about moss", "text/html"))
    with patch("backend.api_routes.notebooks_routes.fetch_page_text", fetch), \
         patch("backend.rag.index_document", return_value=1):
        r = client.post(f"/api/notebooks/{nb['id']}/sources",
                        json={"kind": "url", "ref": "https://example.com/moss",
                              "context_mode": "excluded"}, headers=h)
        assert r.json()["ingest_status"] == "skipped"
        fetch.assert_not_called()  # excluded sources are never fetched
        sid = r.json()["id"]
        r = client.put(f"/api/notebooks/{nb['id']}/sources/{sid}/context",
                       json={"context_mode": "full"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["ingest_status"] == "ingested"
    body = client.get(f"/api/notebooks/{nb['id']}/retrieve",
                      params={"q": "moss"}, headers=h).json()
    assert any("RESTORED-TEXT" in (e.get("text") or "") for e in body["context"])


# ------------------------------------------------------------ memory dashboard

def _mem_rec(id_, kind, content, created):
    rec = MagicMock()
    rec.id = id_
    rec.content = content
    rec.kind = MagicMock()
    rec.kind.value = kind
    rec.importance = 0.9
    rec.room = "default"
    rec.drawer = "general"
    rec.chat_id = ""
    rec.access_count = 0
    rec.created_at = created
    return rec


def test_memory_dashboard_shape_and_retention_preview(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    old = datetime(2020, 1, 1, tzinfo=timezone.utc)
    new = datetime.now(timezone.utc)
    seeded = [_mem_rec("m1", "semantic", "old fact", old),
              _mem_rec("m2", "episodic", "new fact", new)]

    async def _list(limit=50, kind=None):
        return seeded

    async def _stats():
        return {"total": 2, "by_kind": {"semantic": 1, "episodic": 1}}

    with patch("backend.api_routes.memory_routes.list_memories", side_effect=_list), \
         patch("backend.api_routes.memory_routes.memory_stats", side_effect=_stats):
        body = client.get("/api/memory/dashboard?older_than_days=90", headers=h).json()
    assert body["total_memories"] == 2
    assert len(body["memories"]) == 2
    assert body["retention_preview"] == {"older_than_days": 90, "would_forget": 1}
    sep = body["separation"]
    assert sep["conversation_context"]["deleted_when"] == "its chat is deleted"
    assert "only via this dashboard" in sep["persistent_memory"]["deleted_when"]
    assert sep["conversation_context"]["chat_count"] == 0  # fresh test DB


# ------------------------------------------------------- wiring guard: chat

def test_chat_stream_uses_hybrid_retrieval():
    from backend.api_routes import chat_stream_routes

    assert hasattr(chat_stream_routes, "retrieve_hybrid_chunks")
    assert not hasattr(chat_stream_routes, "retrieve_relevant_chunks")
