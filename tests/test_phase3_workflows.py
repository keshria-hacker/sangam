"""Phase 3 tests: DAG workflow engine (validation, topo order, templates,
transforms, retries, timeouts, dead letters, idempotency, replay) and
the workflows API (CRUD, manual run, webhook token, replay).

Engine tests are pure async; API tests use a real app + temp DB.
No LLM calls: retrieve/memory/http nodes are mocked where used.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from unittest.mock import AsyncMock, MagicMock, patch

from backend.workflows import WorkflowError, execute_definition, validate_definition


def _def(nodes, edges=None):
    return {"nodes": nodes, "edges": edges or []}


def test_validate_rejects_cycle_duplicate_unknown():
    with pytest.raises(WorkflowError):
        validate_definition(_def([{"id": "a", "type": "text"}, {"id": "a", "type": "text"}]))
    with pytest.raises(WorkflowError):
        validate_definition(_def([{"id": "a", "type": "nope"}]))
    with pytest.raises(WorkflowError):
        validate_definition(_def(
            [{"id": "a", "type": "text"}, {"id": "b", "type": "text"}],
            [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]))
    with pytest.raises(WorkflowError):
        validate_definition(_def([{"id": "a", "type": "text"}], [{"from": "a", "to": "ghost"}]))
    with pytest.raises(WorkflowError):
        validate_definition(_def([{"id": "a", "type": "transform", "config": {"op": "explode"}}]))


def test_topo_order_and_templates():
    d = _def([
        {"id": "greet", "type": "text", "config": {"template": "Hello {{input.name}}"}},
        {"id": "shout", "type": "transform", "config": {"op": "upper"}},
    ], [{"from": "greet", "to": "shout"}])
    assert validate_definition(d) == ["greet", "shout"]
    outputs, results, error = asyncio.run(execute_definition(d, {"name": "Ada"}))
    assert error is None
    assert outputs == {"greet": "Hello Ada", "shout": "HELLO ADA"}
    assert results["shout"]["attempts"] == 1


def test_transform_reverse_and_missing_template_key():
    d = _def([
        {"id": "a", "type": "text", "config": {"template": "x{{input.missing}}y"}},
        {"id": "b", "type": "transform", "config": {"op": "reverse"}},
    ], [{"from": "a", "to": "b"}])
    outputs, _, error = asyncio.run(execute_definition(d, {}))
    assert error is None and outputs["b"] == "yx"


def test_failed_node_dead_letters_rest_and_retries():
    # http_fetch to a private address fails validation on every attempt:
    # 0 retries configured on the failing node via retries=1 -> 2 attempts.
    d = _def([
        {"id": "bad", "type": "http_fetch", "config": {"url": "http://127.0.0.1/secret"}, "retries": 1},
        {"id": "after", "type": "text", "config": {"template": "never"}},
    ], [{"from": "bad", "to": "after"}])
    outputs, results, error = asyncio.run(execute_definition(d, {}))
    assert error is not None
    assert results["bad"]["status"] == "failed" and results["bad"]["attempts"] == 2
    assert results["after"]["status"] == "skipped"
    assert "after" not in outputs


def test_node_timeout():
    # A text node cannot hang, so simulate with a slow transform via
    # monkeypatched _run_node through a custom node type path: use
    # http_fetch with a mocked slow httpx client instead.
    d = _def([{"id": "slow", "type": "http_fetch",
               "config": {"url": "https://example.com/slow"}, "timeout_seconds": 1}])

    class SlowClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            await asyncio.sleep(5)
            return MagicMock(status_code=200, content=b"late")

    with patch("httpx.AsyncClient", SlowClient), \
         patch("backend.ingest_url.socket.getaddrinfo",
               return_value=[(2, None, None, None, ("93.184.216.34", 0))]):
        _, results, error = asyncio.run(execute_definition(d, {}))
    assert error is not None
    assert results["slow"]["status"] == "failed"


def _api_client(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/phase3.db")
    reset_engine_for_testing()
    import asyncio as _a

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    _a.run(_create_all())
    return TestClient(create_app())


def _auth(client):
    creds = {"username": "phase3_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


_WORKFLOW = {
    "name": "Greet and shout",
    "definition": {
        "nodes": [
            {"id": "greet", "type": "text", "config": {"template": "Hello {{input.name}}"}},
            {"id": "shout", "type": "transform", "config": {"op": "upper"}},
        ],
        "edges": [{"from": "greet", "to": "shout"}],
    },
    "trigger": "manual",
}


def test_workflows_api_end_to_end(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)
    r = client.post("/api/workflows", json=_WORKFLOW, headers=h)
    assert r.status_code == 201, r.text
    wf = r.json()
    assert wf["webhook_token"] and wf["webhook_url"]
    wid = wf["id"]

    # Invalid definition rejected.
    bad = dict(_WORKFLOW)
    bad["definition"] = {"nodes": [{"id": "a", "type": "text"}, {"id": "b", "type": "text"}],
                         "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]}
    assert client.post("/api/workflows", json=bad, headers=h).status_code == 422

    # Manual run.
    r = client.post(f"/api/workflows/{wid}/run", json={"input": {"name": "Ada"}}, headers=h)
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["status"] == "succeeded" and run["output"]["shout"] == "HELLO ADA"

    # Idempotency: same key returns the same run, no second execution.
    r1 = client.post(f"/api/workflows/{wid}/run",
                     json={"input": {"name": "Ada"}, "idempotency_key": "k1"}, headers=h).json()
    r2 = client.post(f"/api/workflows/{wid}/run",
                     json={"input": {"name": "Bob"}, "idempotency_key": "k1"}, headers=h).json()
    assert r1["id"] == r2["id"] and r2["output"]["shout"] == "HELLO ADA"

    # Replay: new run, same input, linked.
    r = client.post(f"/api/workflows/{wid}/runs/{run['id']}/replay", headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["replay_of"] == run["id"] and r.json()["id"] != run["id"]

    # Webhook: wrong token -> 404 (no existence leak); right token runs.
    # Use a fresh client (no auth cookies): the main client's session
    # cookie would trigger CSRF middleware, which external webhook
    # callers never have.
    from backend.main import create_app
    from fastapi.testclient import TestClient as _TC

    webhook_client = _TC(create_app())
    assert webhook_client.post(f"/api/workflows/{wid}/webhook?token=wrong",
                               json={"name": "Zed"}).status_code == 404
    r = webhook_client.post(f"/api/workflows/{wid}/webhook?token={wf['webhook_token']}",
                            json={"name": "Zed"})
    assert r.status_code == 201, r.text
    assert r.json()["output"]["shout"] == "HELLO ZED"

    # Runs list shows all runs.
    r = client.get(f"/api/workflows/{wid}/runs", headers=h)
    assert r.status_code == 200 and len(r.json()["runs"]) >= 4

    # Versioning: same definition keeps version, changed definition bumps it.
    r = client.get(f"/api/workflows/{wid}", headers=h)
    assert r.json()["version"] == 1
    upd = dict(_WORKFLOW)
    r = client.put(f"/api/workflows/{wid}", json=upd, headers=h)
    assert r.status_code == 200 and r.json()["version"] == 1
    upd["definition"]["nodes"][0]["config"]["template"] = "Hi {{input.name}}"
    r = client.put(f"/api/workflows/{wid}", json=upd, headers=h)
    assert r.status_code == 200 and r.json()["version"] == 2
