"""
Batch 9 (Unified Memory + Research) tests.

Covers: observation ledger (mint / strengthen-no-dup / contradict-
weakens-without-deleting / supersede / expiry / context block /
defense block), mem0-style ops preview (NONE/UPDATE/DELETE/ADD) +
apply guards, memory-as-Markdown notes (write / list / normalize
merge), research job state machine with stubbed search/fetch
(plan -> breadth -> depth -> curate -> compress -> done, Runs
mirror, cited report pass, uncited report 422, slides, source
graph), repomix-style pack (secret filtering, token estimate,
chunk reassembly), code memory (refresh-if-stale, change impact,
hubs, cross-layer links), catalogue search/dedupe, and graph edge
confidence decay.

Live TestClient flow (register -> Bearer token), fresh SQLite DB
per test, following the Batch 4 precedent. No live model, no live
network: research search/fetch are monkeypatched fakes.
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

import backend.api_routes.memory_research_routes  # noqa: E402,F401 — registers tables
import backend.api_routes.notebooks_routes  # noqa: E402,F401 — registers tables
from backend.config import settings  # noqa: E402
from backend.database import Base, get_engine, reset_engine_for_testing  # noqa: E402
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

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
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
    creds = {"username": "b9_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


def _mint(client, h, claim="I prefer concise answers", kind="preference"):
    r = client.post("/api/memory/observations", json={
        "kind": kind, "claim": claim,
        "evidence": [{"quote": "be concise please", "source_id": "mem-1",
                      "source_type": "memory"}]}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------ observations

def test_observation_mint_strengthen_no_dup_and_context(client, monkeypatch, tmp_path):
    with client:
        h = _auth_headers(client)
        first = _mint(client, h)
        assert first["created"] is True and first["proof_count"] == 1
        # Same claim, new evidence: strengthened, not duplicated.
        r = client.post("/api/memory/observations", json={
            "kind": "preference", "claim": "I prefer concise answers",
            "evidence": [{"quote": "short answers only", "source_id": "mem-2",
                          "source_type": "memory"}]}, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["created"] is False
        assert r.json()["id"] == first["id"]
        assert r.json()["proof_count"] == 2
        assert r.json()["strength"] > first["strength"]
        # Exact re-mint: no-op.
        r = client.post("/api/memory/observations", json={
            "kind": "preference", "claim": "I prefer concise answers",
            "evidence": [{"quote": "be concise please", "source_id": "mem-1",
                          "source_type": "memory"}]}, headers=h)
        assert r.json()["proof_count"] == 2
        r = client.get("/api/memory/observations", headers=h)
        assert len(r.json()["observations"]) == 1
        # Context block carries the observation id (chat recall surface).
        r = client.get("/api/memory/observations-context", headers=h)
        assert first["id"] in r.json()["observation_ids"]
        assert "concise" in r.json()["context_block"]


def test_observation_contradict_weakens_without_deleting(client):
    with client:
        h = _auth_headers(client)
        obs = _mint(client, h)
        before = obs["strength"]
        r = client.post(f"/api/memory/observations/{obs['id']}/refine", json={
            "verdict": "contradicts",
            "evidence": [{"quote": "actually give me detail", "source_id": "mem-9",
                          "source_type": "memory"}]}, headers=h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["strength"] < before
        assert data["strength"] >= 0.05
        # History + original evidence survive the contradiction.
        assert len(data["refinement_history"]) == 1
        assert data["refinement_history"][0]["verdict"] == "contradicts"
        assert any(e["source_id"] == "mem-1" for e in data["evidence"])


def test_observation_supersede_and_expired_excluded(client):
    with client:
        h = _auth_headers(client)
        old = _mint(client, h, claim="Old claim")
        new = _mint(client, h, claim="New claim")
        r = client.post(f"/api/memory/observations/{old['id']}/supersede",
                        json={"replacement_id": new["id"]}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "superseded"
        assert r.json()["superseded_by"] == new["id"]
        r = client.get("/api/memory/observations", headers=h)
        assert all(o["id"] != old["id"] for o in r.json()["observations"])
        r = client.get("/api/memory/observations?include_closed=true", headers=h)
        assert any(o["id"] == old["id"] for o in r.json()["observations"])
        # Expired observations are excluded from the open list.
        r = client.post("/api/memory/observations", json={
            "kind": "fact", "claim": "Expired claim", "evidence": [],
            "expires_at": "2000-01-01T00:00:00+00:00"}, headers=h)
        assert r.status_code == 201, r.text
        r = client.get("/api/memory/observations", headers=h)
        assert all(o["claim"] != "Expired claim" for o in r.json()["observations"])
        # Supersede with an unknown replacement is refused, not invented.
        r = client.post(f"/api/memory/observations/{new['id']}/supersede",
                        json={"replacement_id": "obs-doesnotexist"}, headers=h)
        assert r.status_code == 422


def test_observation_defense_blocks_credentials(client):
    with client:
        h = _auth_headers(client)
        r = client.post("/api/memory/observations", json={
            "kind": "fact", "claim": "my api_key = abcdefghijklmnop1234",
            "evidence": []}, headers=h)
        assert r.status_code == 422, r.text
        r = client.get("/api/memory/observations", headers=h)
        assert r.json()["observations"] == []


# ------------------------------------------------------------------- ops

def test_ops_preview_none_update_delete_add_pure():
    from backend.memory.models import MemoryRecord
    from backend.memory.ops import preview_ops

    stored = [MemoryRecord(id="m1", content="I prefer concise answers"),
              MemoryRecord(id="m2", content="My dog is named Biscuit")]
    assert preview_ops("I prefer concise answers", stored)[0]["op"] == "NONE"
    upd = preview_ops("I now prefer concise answers actually", stored)
    assert upd[0]["op"] == "UPDATE" and upd[0]["target_id"] == "m1"
    dele = preview_ops("Forget that I prefer concise answers", stored)
    assert dele[0]["op"] == "DELETE" and dele[0]["target_id"] == "m1"
    assert preview_ops("Something entirely new here", stored)[0]["op"] == "ADD"


def test_ops_apply_requires_confirm_and_known_ids(client):
    with client:
        h = _auth_headers(client)
        r = client.post("/api/memory/ops/preview", json={"content": "Brand new fact"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["decisions"][0]["op"] == "ADD"
        # Without confirm: refused, nothing written.
        r = client.post("/api/memory/ops/apply",
                        json={"decisions": r.json()["decisions"], "confirm": False}, headers=h)
        assert r.status_code == 422
        # Invented target id: refused.
        r = client.post("/api/memory/ops/apply",
                        json={"decisions": [{"op": "DELETE", "target_id": "m-nope"}],
                              "confirm": True}, headers=h)
        assert r.status_code == 422


# ------------------------------------------------------------ markdown notes

def test_memory_notes_write_list_normalize_merges(client, monkeypatch, tmp_path):
    monkeypatch.setenv("SANGAM_MEMORY_NOTES_DIR", str(tmp_path / "notes"))
    with client:
        h = _auth_headers(client)
        r = client.post("/api/memory/notes", json={
            "type": "preference", "title": "Concise answers",
            "body": "User prefers concise answers.", "source": "chat-1"}, headers=h)
        assert r.status_code == 201, r.text
        r = client.post("/api/memory/notes", json={
            "type": "preference", "title": "Concise answers",
            "body": "Also: short sentences.", "source": "chat-2"}, headers=h)
        assert r.status_code == 201, r.text
        r = client.get("/api/memory/notes", headers=h)
        assert len(r.json()["notes"]) == 2
        r = client.post("/api/memory/notes/normalize", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["merged_groups"] == 1
        assert len(r.json()["removed_files"]) == 1
        r = client.get("/api/memory/notes", headers=h)
        notes = r.json()["notes"]
        assert len(notes) == 1
        detail = client.get(f"/api/memory/notes/{notes[0]['filename']}", headers=h)
        assert "concise answers" in detail.json()["content"].lower()
        assert "short sentences" in detail.json()["content"].lower()
        # Secret-bearing note is refused and stores nothing.
        r = client.post("/api/memory/notes", json={
            "type": "note", "title": "Oops",
            "body": "-----BEGIN RSA PRIVATE KEY-----\nMII..."}, headers=h)
        assert r.status_code == 422


# ------------------------------------------------------------ research jobs

def _fake_search(monkeypatch):
    async def fake_search(query):
        return [
            {"title": f"Result about {query}", "url": "https://example.com/a",
             "snippet": "alpha beta gamma delta"},
            {"title": "Second source", "url": "https://other.org/b",
             "snippet": "epsilon zeta eta theta"},
        ]

    async def fake_fetch(url):
        return "retrieved full text about the topic " + url

    import backend.api_routes.memory_research_routes as routes_mod
    monkeypatch.setattr(routes_mod, "_default_search", fake_search)
    monkeypatch.setattr(routes_mod, "_default_fetch", fake_fetch)


def test_research_job_run_report_slides_source_graph(client, monkeypatch):
    _fake_search(monkeypatch)
    with client:
        h = _auth_headers(client)
        r = client.post("/api/research/jobs", json={
            "question": "What is Sangam?", "breadth": 2, "depth": 2,
            "word_budget": 500}, headers=h)
        assert r.status_code == 201, r.text
        job = r.json()
        assert job["status"] == "planned"
        r = client.post(f"/api/research/jobs/{job['id']}/run", headers=h)
        assert r.status_code == 200, r.text
        done = r.json()
        assert done["status"] == "done", done
        assert len(done["sources"]) == 2  # deduped by URL across queries
        assert done["sources"][0]["curator_score"] >= done["sources"][-1]["curator_score"]
        assert done["learnings"]
        # Mirrored into the Runs centre.
        r = client.get("/api/runs?kind=research", headers=h)
        assert r.status_code == 200, r.text
        assert any("Sangam" in run.get("title", "") for run in r.json()["runs"])
        # Uncited claim -> 422 (no evidence, no claim).
        r = client.post(f"/api/research/jobs/{job['id']}/report", json={
            "claims": [{"text": "Sangam is the best", "citations": []}]}, headers=h)
        assert r.status_code == 422, r.text
        # Cited claim passes; report cites only retrieved ids.
        cited = done["citations"][0]
        r = client.post(f"/api/research/jobs/{job['id']}/report", json={
            "claims": [{"text": "Sangam research works", "citations": [cited]}]}, headers=h)
        assert r.status_code == 200, r.text
        assert cited in r.json()["report"]
        # Slides carry only report citations; source graph is own sources only.
        r = client.post(f"/api/research/jobs/{job['id']}/slides", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["slide_count"] >= 1
        r = client.get(f"/api/research/jobs/{job['id']}/source-graph", headers=h)
        assert r.status_code == 200, r.text
        assert len(r.json()["nodes"]) == 2
        # Unknown job -> 404, not a fake report.
        assert client.get("/api/research/jobs/rj-nope", headers=h).status_code == 404


def test_research_job_word_budget_compression_pure():
    from backend.research.deep_research import compress_learnings

    learnings = [
        {"source_id": "src-1", "text": " ".join(["word"] * 300), "curator_score": 0.9},
        {"source_id": "src-2", "text": " ".join(["word"] * 300), "curator_score": 0.5},
    ]
    compressed = compress_learnings(learnings, 400)
    assert sum(len(i["text"].split()) for i in compressed) <= 400
    assert compressed[0]["source_id"] == "src-1"  # highest score survives


# -------------------------------------------------------------------- pack

def test_pack_filters_secrets_and_reassembles(client, monkeypatch, tmp_path):
    pack_root = tmp_path / "proj"
    (pack_root / "sub").mkdir(parents=True)
    (pack_root / "main.py").write_text("def hello():\n    return 1\n")
    (pack_root / "sub" / "util.py").write_text("x = 1\n")
    (pack_root / ".env").write_text("API_KEY=supersecret123456\n")
    (pack_root / "blob.bin").write_bytes(b"\x00\x01\x02binary")
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", pack_root)
    with client:
        h = _auth_headers(client)
        r = client.post("/api/knowledge/packs", json={"path": "", "max_tokens": 8000}, headers=h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert any(f["path"] == "main.py" for f in data["files"])
        assert "main.py" in data["tree"]
        filtered = {f["path"]: f["reason"] for f in data["filtered"]}
        assert ".env" in filtered and "blob.bin" in filtered
        assert data["total_tokens_estimate"] >= 1
        from backend.research.pack import reassemble
        bundle_text = reassemble(data)
        assert "def hello" in bundle_text
        assert "supersecret" not in bundle_text
        # Path escape is refused.
        r = client.post("/api/knowledge/packs", json={"path": ".."}, headers=h)
        assert r.status_code in (403, 422), r.text


# ------------------------------------------------------------- code memory

def test_code_memory_refresh_change_impact_hubs_pure(tmp_path):
    from backend.research.code_memory import (
        change_impact, detect_hubs, refresh_if_stale, surprising_links)

    root = tmp_path / "code"
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "app" / "core.py").write_text("def helper():\n    return 1\n")
    (root / "app" / "main.py").write_text(
        "from app.core import helper\n\n\ndef run():\n    return helper()\n")
    (root / "tests" / "test_core.py").write_text(
        "from app.core import helper\n\n\ndef test_helper():\n    assert helper() == 1\n")
    first = refresh_if_stale(root)
    assert first["rebuilt"] is True
    second = refresh_if_stale(root)
    assert second["stale"] is False and second["rebuilt"] is False
    # Different length on purpose: the probe is stat-based (size+mtime),
    # so a same-size, same-second edit is legitimately invisible to it.
    (root / "app" / "core.py").write_text("def helper():\n    return 22222\n")
    third = refresh_if_stale(root)
    assert third["stale"] is True and third["rebuilt"] is True
    assert any("core.py" in f for f in third["changed_files"])

    from backend import code_graph
    graph = code_graph.build_graph(root)
    impact = change_impact("helper", graph)
    assert impact["found"] is True
    assert impact["callers"], impact
    assert any("test_core" in t for t in impact["tests"])
    hubs = detect_hubs(graph)
    assert hubs and hubs[0]["incoming_calls"] >= 1
    links = surprising_links(graph)
    assert all(link["from_layer"] != link["to_layer"] for link in links)
    assert change_impact("no_such_symbol_xyz", graph)["found"] is False


# ----------------------------------------------------------------- catalogue

def test_catalogue_search_dedupe_and_risk_notes(client):
    with client:
        h = _auth_headers(client)
        r = client.get("/api/knowledge/catalogue", headers=h)
        assert r.status_code == 200, r.text
        entries = r.json()["entries"]
        assert entries
        ids = [e["id"] for e in entries]
        assert len(ids) == len(set(ids))  # deduped
        assert all(e.get("risk") and e.get("install") for e in entries)
        r = client.get("/api/knowledge/catalogue?q=corrective", headers=h)
        assert any(e["id"] == "pattern-corrective-rag" for e in r.json()["entries"])
        r = client.get("/api/knowledge/catalogue?kind=mcp_server", headers=h)
        assert all(e["kind"] == "mcp_server" for e in r.json()["entries"])
        r = client.get("/api/knowledge/catalogue?q=zzz-no-match", headers=h)
        assert r.json()["entries"] == []
        assert "empty_state" in r.json()


# ------------------------------------------------------- notebook timeline

def test_notebook_timeline_and_deep_research_link(client):
    with client:
        h = _auth_headers(client)
        r = client.post("/api/notebooks", json={"name": "NB1", "description": ""}, headers=h)
        assert r.status_code == 201, r.text
        nb = r.json()
        nb_id = nb.get("id") or nb.get("notebook", {}).get("id")
        assert nb_id
        r = client.post(f"/api/notebooks/{nb_id}/deep-research", json={
            "question": "Timeline test question?"}, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["notebook_id"] == nb_id
        r = client.get(f"/api/notebooks/{nb_id}/timeline", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["notebook_id"] == nb_id
        assert r.json()["events"] == []  # no sources yet: honest empty, not faked


# ------------------------------------------------------------- graph decay

def test_graph_edge_confidence_decay_pure():
    from backend.memory.graph import decayed_confidence

    assert decayed_confidence(1.0, 0) == 1.0
    assert decayed_confidence(1.0, 90) == pytest.approx(0.5)
    assert decayed_confidence(1.0, 900) == pytest.approx(0.05)  # floor, never zero
    assert decayed_confidence(0.8, 90) == pytest.approx(0.4)
