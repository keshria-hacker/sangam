"""Wave-2 deep-knowledge tests (KNOWLEDGE worker).

Covers: notebook URL ingest-on-add + dedupe + token budget +
saved transforms/insights, BFS deep crawl against a LOCAL fixture
HTTP server (never the public internet), graph hardening (alias,
predicate normalization, confidence/source_ref, as-of, supersede +
contradiction flagging), read-only evidence-backed reflections +
triage consolidation planning, goal/task threads, lesson player,
and corrective RAG grading/rewriting.

Live TestClient flow (register -> Bearer <redacted>), fresh SQLite DB +
fresh ChromaDB dir per test, following the Batch 4 test precedent.
No Playwright, no servers on shared ports, no public internet.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import backend.api_routes.goals_routes  # noqa: E402,F401 — registers routes + tables
import backend.api_routes.knowledge_routes  # noqa: E402,F401
import backend.api_routes.notebooks_routes as nb_routes  # noqa: E402,F401
import backend.crawl_job  # noqa: E402,F401 — registers crawl tables
import backend.memory.graph  # noqa: E402,F401 — registers graph tables
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
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
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
    creds = {"username": "dk_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


def _make_notebook(client, h, name="Research"):
    r = client.post("/api/notebooks", json={"name": name, "description": "d"}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _mock_complete(monkeypatch, output):
    async def fake(db, messages, max_tokens=2000):
        return output

    monkeypatch.setattr(
        "backend.memory.extract_llm.complete_text", fake)


# ------------------------------------------------------------ fixture site

def _fixture_server():
    """Local docs site: index + 24 topic pages, one robots-disallowed
    page, one external link. All content is unique per page."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/robots.txt":
                body = "User-agent: *\nDisallow: /secret\n"
                return self._send(body, "text/plain")
            if self.path in ("/", "/index.html"):
                links = "".join(
                    f'<a href="/page{i}.html">page {i}</a> '
                    for i in range(24))
                links += '<a href="/secret.html">secret</a> '
                links += '<a href="https://example.com/out.html">external</a>'
                return self._send(
                    f"<html><head><title>Index</title></head><body>{links}</body></html>",
                    "text/html")
            if self.path == "/secret.html":
                return self._send(
                    "<html><body>SECRET-PAGE-TEXT should not be crawled</body></html>",
                    "text/html")
            if self.path.startswith("/page") and self.path.endswith(".html"):
                name = self.path.strip("/").replace(".html", "")
                nxt = (int(name.replace("page", "")) + 1) % 24
                body = (
                    f"<html><head><title>{name}</title></head><body>"
                    f"<p>TOPIC-BODY-{name} alpha beta gamma</p>"
                    f'<a href="/index.html">home</a> '
                    f'<a href="/page{nxt}.html">next</a></body></html>')
                return self._send(body, "text/html")
            self.send_response(404)
            self.end_headers()

        def _send(self, body, ctype):
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture
def fixture_site():
    server = _fixture_server()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


# ------------------------------------------------------------ graph hardening

def _setup_db(tmp_path, monkeypatch, dbname="test.db"):
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/{dbname}")
    reset_engine_for_testing()

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())


def _db_session(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch, dbname="graph.db")
    return AsyncSessionLocal()


def test_graph_predicate_normalization_and_as_of(tmp_path, monkeypatch):
    from datetime import UTC, datetime

    from backend.memory.graph import (
        add_relation,
        entity_timeline,
        flag_contradiction,
        normalize_predicate,
        query_as_of,
        supersede,
    )

    async def _run():
        async with AsyncSessionLocal() as db:
            assert normalize_predicate("Lives In") == "lives_in"
            old = await add_relation(db, "u1", "Ada", "Lives In", "London",
                                     confidence=0.8, source_ref="chat-1")
            await db.commit()
            assert old.predicate == "lives_in"
            assert old.confidence == 0.8
            assert old.source_ref == "chat-1"
            # Pre-write flagging surfaces the contradiction.
            flag = await flag_contradiction(db, "u1", "Ada", "lives_in", "Paris")
            assert flag is not None
            assert flag["previously"] == "London" and flag["now"] == "Paris"
            assert "previously London, now Paris" in flag["message"]
            prev, new = await supersede(db, "u1", "Ada", "lives_in", "Paris")
            await db.commit()
            assert prev is not None and prev.id == old.id
            assert new.object == "Paris"
            # As-of the old row's start: only the successor-free past.
            at_old = await query_as_of(db, "u1", old.valid_from)
            assert [r.object for r in at_old] == ["London"]
            at_now = await query_as_of(db, "u1", datetime.now(UTC))
            assert [r.object for r in at_now] == ["Paris"]
            timeline_now = await entity_timeline(db, "u1", "Ada", as_of=datetime.now(UTC))
            assert [r.object for r in timeline_now] == ["Paris"]

    _setup_db(tmp_path, monkeypatch, dbname="graph.db")
    asyncio.run(_run())


def test_graph_alias_canonicalization(tmp_path, monkeypatch):
    from backend.memory.graph import add_alias, add_relation, upsert_entity

    async def _run():
        async with AsyncSessionLocal() as db:
            ent = await upsert_entity(db, "u1", "Ada Lovelace", kind="person")
            await add_alias(db, "u1", ent.id, "Ada")
            same = await upsert_entity(db, "u1", "ada")
            assert same.id == ent.id
            rel = await add_relation(db, "u1", "Ada", "works_on", "Engine")
            assert rel.subject == "Ada Lovelace"
            await db.commit()

    _setup_db(tmp_path, monkeypatch, dbname="graph.db")
    asyncio.run(_run())


def test_graph_inverted_interval_guard():
    from datetime import UTC, datetime, timedelta

    from backend.memory.graph import _check_interval

    now = datetime.now(UTC)
    _check_interval(now, now + timedelta(seconds=1))  # fine
    with pytest.raises(ValueError):
        _check_interval(now, now - timedelta(seconds=1))


# ------------------------------------------------------------ reflection (read-only)

def test_reflection_read_only_and_trend():
    from datetime import UTC, datetime, timedelta

    from backend.reflection import (
        compute_trend,
        plan_consolidation,
        reflect_read_only,
        triage_new,
    )

    now = datetime(2026, 10, 25, tzinfo=UTC)
    records = [
        {"id": "m1", "content": "Ada lives in London",
         "created_at": now - timedelta(days=5)},
        {"id": "m2", "content": "Ada works on the Engine",
         "created_at": now - timedelta(days=40)},
    ]
    raw = ('{"observations": [{"text": "Ada is in London", "evidence": ["m1", "bogus"]}], '
           '"mental_model": "Ada model", "open_questions": []}')
    out = reflect_read_only(records, raw, now=now)
    assert out is not None
    assert out["stored"] is False  # read-only: nothing was persisted
    assert out["evidence_ids"] == ["m1"]  # bogus id filtered out
    assert out["proof_count"] == 1
    assert out["trend"] == "new"
    assert compute_trend([], now=now) == "stale"
    assert compute_trend([now - timedelta(days=100)], now=now) == "stale"
    assert triage_new("Ada lives in London", records) == "restates"
    assert triage_new("ok", records) == "chatter"
    assert triage_new("Ada adopted a cat named Pixel", records) == "new"
    plan = plan_consolidation([
        {"id": "a", "content": "Ada lives in London", "created_at": "2026-01-01"},
        {"id": "b", "content": "Ada lives in London", "created_at": "2026-01-02"},
        {"id": "c", "content": "Ada lives in London!", "created_at": "2026-01-03"},
    ])
    assert plan["delete"] == ["b", "c"]  # exact + near dup collapse
    assert plan["decisions"][0]["verdict"] == "new"


# ------------------------------------------------------------ lesson player

def test_lesson_player_pause_question_resume_same_scene():
    from backend.lesson_player import LessonPlayer, lesson_from_outline

    lesson = lesson_from_outline("Photosynthesis", [
        {"title": "Light", "points": ["Chlorophyll absorbs light"], "duration_min": 5},
        {"title": "Dark", "points": ["Calvin cycle fixes carbon"], "duration_min": 5},
    ])
    spoken = []
    player = LessonPlayer.__new__(LessonPlayer)
    from backend.lesson_player import LessonScene

    scenes = [LessonScene.from_dict(s) for s in lesson["scenes"]]
    player = LessonPlayer(scenes, narrate=lambda text: spoken.append(text) or "audio:1")
    assert player.start()["mode"] == "playing"
    step = player.play_step()
    assert step["action"] == "speech" and "Chlorophyll" in step["text"]
    step = player.play_step()
    assert step["action"] == "question" and player.mode == "paused"
    assert player.awaiting_answer is True
    # Interrupt-style resume check: answering resumes at the NEXT scene,
    # and a mid-lesson interrupt returns to the same scene.
    resumed = player.answer_question("Light energy becomes chemical energy")
    assert resumed["mode"] == "playing"
    assert resumed["scene_index"] == 1
    player.interrupt("What is chlorophyll?")
    assert player.mode == "live"
    assert player.scene_index == 1
    paused = player.end_discussion()
    assert paused["mode"] == "paused" and paused["scene_index"] == 1
    assert player.resume()["scene_index"] == 1  # same scene, not restart
    # Snapshot round-trip preserves the cursor.
    snap = player.to_dict()
    restored = LessonPlayer.from_dict(snap)
    assert (restored.scene_index, restored.action_index) == (
        player.scene_index, player.action_index)
    with pytest.raises(ValueError):
        LessonPlayer([])


# ------------------------------------------------------------ crawl (local fixture)

def test_crawl_bfs_fixture_site(fixture_site):
    from backend.crawl_job import (
        fetch_page_http,
        robots_allowed,
        run_crawl,
        score_url,
    )

    assert robots_allowed("User-agent: *\nDisallow: /secret\n", "/secret") is False
    assert robots_allowed("User-agent: *\nDisallow: /secret\n", "/page1.html") is True
    assert score_url("http://x/docs/alpha-guide", ["alpha"], 3) > score_url(
        "http://x/docs/other", ["alpha"], 3)

    async def _run():
        robots_cache: dict = {}

        async def fetcher(url):
            return await fetch_page_http(url, robots_cache=robots_cache,
                                         allow_local=True)

        return await run_crawl(
            f"{fixture_site}/index.html", max_depth=2, max_pages=30,
            fetcher=fetcher, validate_discovered=False)

    summary = asyncio.run(_run())
    urls = [p["url"] for p in summary["pages"]]
    assert len(summary["pages"]) >= 24
    assert f"{fixture_site}/index.html" in urls
    assert not any("example.com" in u for u in urls)  # external excluded
    assert not any("secret" in u for u in urls)  # robots-disallowed excluded
    assert all(p["depth"] <= 2 for p in summary["pages"])
    non_seed = [p for p in summary["pages"] if p["url"] != f"{fixture_site}/index.html"]
    assert non_seed and all(p["parent_url"] for p in non_seed)


def test_crawl_endpoint_approval_and_pages(client, fixture_site):
    with client:
        h = _auth_headers(client)
        r = client.post("/api/knowledge/crawl",
                        json={"seed_url": f"{fixture_site}/index.html",
                              "max_depth": 2, "max_pages": 30},
                        headers=h)
        assert r.status_code == 422  # approval gate
        r = client.post("/api/knowledge/crawl",
                        json={"seed_url": f"{fixture_site}/index.html",
                              "approved": True, "allow_local": True,
                              "max_depth": 2, "max_pages": 30},
                        headers=h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["job"]["status"] == "done"
        assert len(data["pages"]) >= 24
        assert all(p["parent_url"] for p in data["pages"]
                   if p["url"] != f"{fixture_site}/index.html")
        job_id = data["job"]["id"]
        r = client.get(f"/api/knowledge/crawls/{job_id}", headers=h)
        assert r.status_code == 200, r.text
        assert len(r.json()["pages"]) >= 24
        from backend.contracts import run_store

        record = run_store.get(job_id)
        assert record is not None and record.state.value == "succeeded"


# ------------------------------------------------------------ notebooks

def test_notebook_url_ingest_on_add_and_dedupe(client, monkeypatch):
    import backend.api_routes.notebooks_routes as nb

    calls = []

    async def fake_fetch(url):
        calls.append(url)
        return ("UNIQUE-PAGE-TEXT-12345 about photosynthesis", "text/html")

    monkeypatch.setattr(nb, "fetch_page_text", fake_fetch)
    with client:
        h = _auth_headers(client)
        nb_id = _make_notebook(client, h)
        r = client.post(f"/api/notebooks/{nb_id}/sources",
                        json={"kind": "url", "ref": "https://example.com/guide",
                              "context_mode": "full"}, headers=h)
        assert r.status_code == 201, r.text
        first = r.json()
        assert first["ingest_status"] == "ingested"
        assert first["file_id"]
        # Same URL (trailing-slash variant) dedupes to the same row.
        r = client.post(f"/api/notebooks/{nb_id}/sources",
                        json={"kind": "url", "ref": "https://example.com/guide/",
                              "context_mode": "full"}, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["id"] == first["id"]
        # Retrieve returns the page's own text — the broken promise fixed.
        r = client.get(f"/api/notebooks/{nb_id}/retrieve?q=photosynthesis", headers=h)
        assert r.status_code == 200, r.text
        texts = " ".join(e.get("text", "") for e in r.json()["context"])
        assert "UNIQUE-PAGE-TEXT-12345" in texts
        # Cross-notebook reuse: no second fetch.
        nb2 = _make_notebook(client, h, name="Second")
        r = client.post(f"/api/notebooks/{nb2}/sources",
                        json={"kind": "url", "ref": "https://example.com/guide",
                              "context_mode": "full"}, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["file_id"] == first["file_id"]
        assert len(calls) == 1


def test_notebook_failed_ingest_never_blocks_add(client, monkeypatch):
    import backend.api_routes.notebooks_routes as nb

    async def failing_fetch(url):
        raise RuntimeError("boom")

    monkeypatch.setattr(nb, "fetch_page_text", failing_fetch)
    with client:
        h = _auth_headers(client)
        nb_id = _make_notebook(client, h)
        r = client.post(f"/api/notebooks/{nb_id}/sources",
                        json={"kind": "url", "ref": "https://example.com/down",
                              "context_mode": "full"}, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["ingest_status"] == "failed"
        r = client.get(f"/api/notebooks/{nb_id}/retrieve?q=x", headers=h)
        assert r.status_code == 200, r.text
        entry = [e for e in r.json()["context"] if e.get("ref") == "https://example.com/down"]
        assert entry and "failed" in (entry[0].get("note") or "")


def test_notebook_token_budget_truncates(client):
    with client:
        h = _auth_headers(client)
        nb_id = _make_notebook(client, h)
        for i in range(3):
            r = client.post(f"/api/notebooks/{nb_id}/notes",
                            json={"title": f"Long{i}", "content": "B" * 2000},
                            headers=h)
            assert r.status_code == 201, r.text
        r = client.get(f"/api/notebooks/{nb_id}/retrieve?q=B&budget_tokens=100",
                       headers=h)
        assert r.status_code == 200, r.text
        notes = " ".join(e.get("note", "") for e in r.json()["context"])
        assert "token budget" in notes


def test_notebook_saved_transforms_insights_promotion(client, monkeypatch):
    _mock_complete(monkeypatch, "TRANSFORM-OUTPUT-XYZ")
    with client:
        h = _auth_headers(client)
        nb_id = _make_notebook(client, h)
        r = client.post(f"/api/notebooks/{nb_id}/saved-transforms",
                        json={"name": "Summarize", "prompt": "Summarize this",
                              "apply_default": False}, headers=h)
        assert r.status_code == 201, r.text
        r = client.post(f"/api/notebooks/{nb_id}/notes",
                        json={"title": "Src", "content": "SOURCE-CONTENT"}, headers=h)
        note_id = r.json()["id"]
        r = client.post(f"/api/notebooks/{nb_id}/sources",
                        json={"kind": "note", "ref": note_id, "context_mode": "full"},
                        headers=h)
        assert r.status_code == 201, r.text
        source_id = r.json()["id"]
        r = client.post(f"/api/notebooks/{nb_id}/transforms",
                        json={"name": "Summarize", "prompt": "Summarize this",
                              "source_ids": [source_id]}, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["transform"]["output"] == "TRANSFORM-OUTPUT-XYZ"
        r = client.get(f"/api/notebooks/{nb_id}/insights", headers=h)
        assert r.status_code == 200, r.text
        insights = r.json()["insights"]
        assert insights and insights[0]["content"] == "TRANSFORM-OUTPUT-XYZ"
        r = client.post(
            f"/api/notebooks/{nb_id}/insights/{insights[0]['id']}/save-as-note",
            headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["content"] == "TRANSFORM-OUTPUT-XYZ"


def test_notebook_apply_default_transform_on_add(client, monkeypatch):
    _mock_complete(monkeypatch, "AUTO-INSIGHT-123")
    with client:
        h = _auth_headers(client)
        nb_id = _make_notebook(client, h)
        r = client.post(f"/api/notebooks/{nb_id}/saved-transforms",
                        json={"name": "AutoSum", "prompt": "Summarize",
                              "apply_default": True}, headers=h)
        assert r.status_code == 201, r.text
        r = client.post(f"/api/notebooks/{nb_id}/notes",
                        json={"title": "N", "content": "SOME-NOTE-TEXT"}, headers=h)
        note_id = r.json()["id"]
        r = client.post(f"/api/notebooks/{nb_id}/sources",
                        json={"kind": "note", "ref": note_id, "context_mode": "full"},
                        headers=h)
        assert r.status_code == 201, r.text
        r = client.get(f"/api/notebooks/{nb_id}/insights", headers=h)
        assert any(i["content"] == "AUTO-INSIGHT-123" for i in r.json()["insights"])


# ------------------------------------------------------------ goals / tasks

def test_goals_tasks_tree_lifecycle_and_work_ref(client):
    with client:
        h = _auth_headers(client)
        r = client.post("/api/goals", json={"title": "Ship Sangam"}, headers=h)
        assert r.status_code == 201, r.text
        goal_id = r.json()["id"]
        r = client.post("/api/goals", json={"title": "Sub goal", "parent_id": goal_id},
                        headers=h)
        assert r.status_code == 201, r.text
        r = client.post(f"/api/goals/{goal_id}/tasks",
                        json={"title": "Write crawler", "priority": "high",
                              "work_ref_type": "workflow", "work_ref_id": "wf-1"},
                        headers=h)
        assert r.status_code == 201, r.text
        task = r.json()
        assert task["status"] == "backlog" and task["status_version"] == 0
        assert task["work_ref_type"] == "workflow" and task["work_ref_id"] == "wf-1"
        r = client.patch(f"/api/tasks/{task['id']}",
                         json={"status": "in_progress"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "in_progress"
        assert r.json()["status_version"] == 1
        r = client.patch(f"/api/tasks/{task['id']}",
                         json={"status": "done"}, headers=h)
        assert r.status_code == 200
        # Open-tasks list excludes the done task: work remaining is visible.
        r = client.get("/api/tasks?open_only=true", headers=h)
        assert r.status_code == 200, r.text
        assert all(t["id"] != task["id"] for t in r.json()["tasks"])
        r = client.get(f"/api/goals/{goal_id}", headers=h)
        assert r.status_code == 200, r.text
        tree = r.json()
        assert tree["task_count"] == 1 and tree["open_task_count"] == 0
        assert len(tree["subgoals"]) == 1
        r = client.patch(f"/api/tasks/{task['id']}",
                         json={"status": "bogus"}, headers=h)
        assert r.status_code == 422


# ------------------------------------------------------------ corrective RAG + ingest dedupe

def test_corrective_rag_grade_and_rewrite():
    from backend.api_routes.knowledge_routes import grade_results, rewrite_query

    assert grade_results([], threshold=0.35) == ("weak", 0.0)
    assert grade_results([{"score": 0.9}], threshold=0.35)[0] == "strong"
    assert grade_results([{"score": 0.1}], threshold=0.35)[0] == "weak"
    assert rewrite_query("what is the capital of France") == "capital france"


def test_ingest_url_dedupe(client, monkeypatch):
    import httpx

    class FakeResp:
        status_code = 200
        headers = {"content-type": "text/html"}

        def __init__(self):
            self.content = b"<html><body>DEDUP-PAGE-TEXT</body></html>"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr("backend.ingest_url.validate_url", lambda url: "example.com")
    with client:
        h = _auth_headers(client)
        r = client.post("/api/knowledge/ingest-url",
                        json={"url": "https://example.com/dedup"}, headers=h)
        assert r.status_code == 200, r.text
        first = r.json()
        assert first["deduped"] is False
        r = client.post("/api/knowledge/ingest-url",
                        json={"url": "https://example.com/dedup"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["deduped"] is True
        assert r.json()["file_id"] == first["file_id"]


def test_retrieve_endpoint_shows_grade(client):
    with client:
        h = _auth_headers(client)
        r = client.get("/api/knowledge/retrieve?q=nothing-matches-anything",
                       headers=h)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["grade"] == "weak"
        assert data["fallback_used"] == "none"
        assert data["results"] == []
