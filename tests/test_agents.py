"""Agent Hub tests: CustomAgent model, CRUD API, ownership, run endpoint."""
from __future__ import annotations

import os
from pathlib import Path

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

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/agents.db")
    reset_engine_for_testing()

    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth_headers(client):
    creds = {"username": "agent_hub_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def _other_headers(client):
    creds = {"username": "agent_hub_other", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def test_agent_crud(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth_headers(client)

    # Create
    r = client.post("/api/agents", json={
        "name": "Test Agent",
        "description": "A test",
        "system_prompt": "Be helpful.",
        "model_id": "openai::gpt-4o",
        "tool_names": ["web_search", "bogus_tool"],
        "max_steps": 5,
    }, headers=h)
    assert r.status_code == 200, r.text
    agent = r.json()
    assert agent["name"] == "Test Agent"
    assert agent["tool_names"] == ["web_search"]  # bogus filtered
    aid = agent["id"]

    # List
    r = client.get("/api/agents", headers=h)
    assert r.status_code == 200
    assert len(r.json()) == 1

    # Get one
    r = client.get(f"/api/agents/{aid}", headers=h)
    assert r.status_code == 200
    assert r.json()["system_prompt"] == "Be helpful."

    # Update
    r = client.put(f"/api/agents/{aid}", json={
        "name": "Renamed", "tool_names": [], "max_steps": 3,
    }, headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"
    assert r.json()["max_steps"] == 3

    # Delete
    r = client.delete(f"/api/agents/{aid}", headers=h)
    assert r.status_code == 200
    assert client.get("/api/agents", headers=h).json() == []


def test_agent_ownership(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h1 = _auth_headers(client)
    h2 = _other_headers(client)

    r = client.post("/api/agents", json={"name": "Mine"}, headers=h1)
    aid = r.json()["id"]

    # Other user cannot see it
    assert client.get("/api/agents", headers=h2).json() == []
    # Other user gets 404 on direct access
    assert client.get(f"/api/agents/{aid}", headers=h2).status_code == 404
    assert client.put(f"/api/agents/{aid}", json={"name": "X"}, headers=h2).status_code == 404
    assert client.delete(f"/api/agents/{aid}", headers=h2).status_code == 404
    # Owner can still delete
    assert client.delete(f"/api/agents/{aid}", headers=h1).status_code == 200


def test_agent_endpoints_require_auth(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    assert client.get("/api/agents").status_code == 401
    assert client.post("/api/agents", json={"name": "x"}).status_code == 401


def test_agent_run_validation(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth_headers(client)
    r = client.post("/api/agents", json={"name": "Runner"}, headers=h)
    aid = r.json()["id"]
    # Empty task -> 422
    r = client.post(f"/agents/{aid}/run", json={"task": "  "}, headers=h)
    assert r.status_code == 422
    # Nonexistent agent -> 404
    r = client.post("/api/agents/doesnotexist/run", json={"task": "hi"}, headers=h)
    assert r.status_code == 404


def test_agent_run_streams_sse(tmp_path, monkeypatch):
    """Run endpoint streams SSE with mocked run_agent."""
    import backend.api_routes.agents_routes as ar

    async def fake_run(task, model_id, db, **kwargs):
        assert kwargs.get("system_prompt") == "Custom prompt."
        assert kwargs.get("max_iterations") == 4
        from backend.code_agent import AgentStep
        yield AgentStep(kind="thought", content="thinking")
        yield AgentStep(kind="done", content="finished")

    monkeypatch.setattr(ar, "run_agent", fake_run)
    # Avoid needing a real model
    async def fake_default(db):
        return "openai::gpt-4o"
    import backend.llm as llm_mod
    monkeypatch.setattr(llm_mod, "default_model_id", fake_default)

    client = _api_client(tmp_path, monkeypatch)
    h = _auth_headers(client)
    r = client.post("/api/agents", json={
        "name": "Streamer", "system_prompt": "Custom prompt.", "max_steps": 4,
    }, headers=h)
    aid = r.json()["id"]
    r = client.post(f"/agents/{aid}/run", json={"task": "do it"}, headers=h)
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert '"kind": "thought"' in r.text
    assert '"kind": "end"' in r.text
