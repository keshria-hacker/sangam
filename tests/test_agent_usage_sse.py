"""T9: agent runs stream a final 'usage' event with tokens/cost.

The CostMeter snapshot existed (T8) but no route forwarded it, so the
UI could never show a run's tokens or cost. All three streaming agent
routes now emit a 'usage' event (carrying the latest cumulative
snapshot) before the 'end' event, and the shared RunLog renders it.
The fake engine here stands in for run_agent/run_code_agent; the
wiring under test is the route's capture-and-emit of on_usage_detail.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ["TEST_MODE"] = "1"

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


def _api_client(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "DATABASE_URL",
                        f"sqlite+aiosqlite:///{tmp_path}/usage.db")
    reset_engine_for_testing()

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth_headers(client):
    creds = {"username": "usage_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post(
        "/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


def _events(client, path, payload):
    with client:
        headers = _auth_headers(client)
        r = client.post(path, json=payload, headers=headers)
        assert r.status_code == 200, r.text
        body = r.text
    events = []
    for part in body.split("\n\n"):
        line = part.strip()
        if line.startswith("data:"):
            events.append(json.loads(line[5:].strip()))
    return events


_SNAPSHOT = {
    "prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500,
    "responses": 1, "unknown_responses": 0, "usage_known": True,
    "cost_usd": 0.00045, "cost_known": True,
    "input_cost_per_token": 1.5e-07, "output_cost_per_token": 6e-07,
}


def test_chat_agent_run_emits_usage_before_end(tmp_path, monkeypatch):
    import backend.api_routes.code_agent_routes as routes

    async def fake_run_agent(*args, on_usage_detail=None, **kwargs):
        if on_usage_detail:
            on_usage_detail(dict(_SNAPSHOT))
        yield SimpleNamespace(kind="answer", content="done",
                              tool_name="", approval_id="")

    monkeypatch.setattr(routes, "run_agent", fake_run_agent)
    client = _api_client(tmp_path, monkeypatch)
    events = _events(client, "/api/agent/run",
                     {"message": "hi", "model": "openai::gpt-4o-mini"})
    kinds = [e["kind"] for e in events]
    assert "answer" in kinds
    assert kinds[-1] == "end"
    usage = [e for e in events if e["kind"] == "usage"]
    assert len(usage) == 1
    assert usage[0]["usage"]["total_tokens"] == 1500
    assert usage[0]["usage"]["cost_usd"] == 0.00045
    assert usage[0]["usage"]["cost_known"] is True
    assert kinds.index("usage") < kinds.index("end")


def test_chat_agent_run_without_usage_emits_no_usage_event(tmp_path, monkeypatch):
    import backend.api_routes.code_agent_routes as routes

    async def fake_run_agent(*args, on_usage_detail=None, **kwargs):
        # A run that fails before any model response never reports usage.
        yield SimpleNamespace(kind="error", content="LLM call failed",
                              tool_name="", approval_id="")

    monkeypatch.setattr(routes, "run_agent", fake_run_agent)
    client = _api_client(tmp_path, monkeypatch)
    events = _events(client, "/api/agent/run",
                     {"message": "hi", "model": "openai::gpt-4o-mini"})
    assert not [e for e in events if e["kind"] == "usage"]
    assert events[-1]["kind"] == "end"


def test_code_agent_run_emits_usage(tmp_path, monkeypatch):
    import backend.api_routes.code_agent_routes as routes

    async def fake_run_code_agent(*args, on_usage_detail=None, **kwargs):
        if on_usage_detail:
            on_usage_detail(dict(_SNAPSHOT))
        yield SimpleNamespace(kind="done", content="done", tool_name="")

    monkeypatch.setattr(routes, "run_code_agent", fake_run_code_agent)
    client = _api_client(tmp_path, monkeypatch)
    events = _events(client, "/api/code-agent/run",
                     {"task": "hi", "model": "openai::gpt-4o-mini"})
    usage = [e for e in events if e["kind"] == "usage"]
    assert len(usage) == 1
    assert usage[0]["usage"]["prompt_tokens"] == 1000
    assert usage[0]["usage"]["completion_tokens"] == 500
