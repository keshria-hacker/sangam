"""Multi-agent teams tests: definitions, runner fan-out/fan-in, API."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import backend.teams.runner as runner_mod  # noqa: E402
from backend.teams import (  # noqa: E402
    TeamError,
    get_team,
    list_teams,
    register_teams_extension,
    run_team,
)


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "FEATURE_MULTI_AGENT", True)
    yield


# --- definitions ----------------------------------------------------------

def test_list_teams():
    teams = {t["id"]: t for t in list_teams()}
    assert {"research", "code", "writing"} <= set(teams)
    assert len(teams["research"]["specialists"]) == 2
    assert get_team("nope") is None


# --- runner ----------------------------------------------------------------

async def _fake_complete(model_id, messages, db, temperature=0.7, max_tokens=2000):
    system = messages[0]["content"]
    if "coordinator" in system.lower():
        return "SYNTHESIS of specialists"
    role = "specialist"
    if "research" in system.lower():
        role = "researcher-output"
    elif "fact" in system.lower():
        role = "factchecker-output"
    return role


@pytest.mark.asyncio
async def test_run_team_fan_out_fan_in(monkeypatch):
    calls = []

    async def tracking(model_id, messages, db, temperature=0.7, max_tokens=2000):
        calls.append(messages[0]["content"][:40])
        return await _fake_complete(model_id, messages, db, temperature, max_tokens)

    monkeypatch.setattr(runner_mod, "_complete_once", tracking)
    result = await run_team("research", "test task", "model-x", db=None)
    assert result.error is None
    assert result.synthesis == "SYNTHESIS of specialists"
    assert len(result.specialists) == 2
    assert all(r.ok for r in result.specialists)
    # 2 specialists + 1 coordinator = 3 LLM calls
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_run_team_specialist_failure_isolated(monkeypatch):
    async def flaky(model_id, messages, db, temperature=0.7, max_tokens=2000):
        if "fact-checking" in messages[0]["content"].lower():
            raise RuntimeError("boom")
        return await _fake_complete(model_id, messages, db, temperature, max_tokens)

    monkeypatch.setattr(runner_mod, "_complete_once", flaky)
    result = await run_team("research", "test task", "model-x", db=None)
    assert result.error is None  # coordinator still ran
    assert result.synthesis == "SYNTHESIS of specialists"
    failed = [r for r in result.specialists if not r.ok]
    assert len(failed) == 1 and "boom" in failed[0].error


@pytest.mark.asyncio
async def test_run_team_unknown_team():
    with pytest.raises(TeamError, match="Unknown team"):
        await run_team("nope", "task", "model-x", db=None)


@pytest.mark.asyncio
async def test_run_team_flag_off(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "FEATURE_MULTI_AGENT", False)
    with pytest.raises(TeamError, match="not enabled"):
        await run_team("research", "task", "model-x", db=None)


def test_teams_extension_registered():
    from backend.extensions import extensions

    assert register_teams_extension() is True
    manifest = extensions.get("capability:multi_agent")
    assert manifest is not None and manifest.version == "1.0.0"


# --- API ---------------------------------------------------------------------

def _api_client(tmp_path, monkeypatch, teams_on: bool):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "FEATURE_MULTI_AGENT", teams_on)
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    assert "history/sangam.db" not in str(settings.DATABASE_URL)
    reset_engine_for_testing()

    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth(client):
    creds = {"username": "team_test_user", "password": "StrongPass123!"}
    resp = client.post("/api/auth/register", json=creds)
    data = resp.json() if resp.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def test_teams_api_404_when_flag_off(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch, teams_on=False)
    headers = _auth(client)
    assert client.get("/api/teams", headers=headers).status_code == 404
    assert client.post("/api/teams/run", json={"team_id": "research", "task": "x"}, headers=headers).status_code == 404


def test_teams_api_list_and_run(tmp_path, monkeypatch):
    async def fake_run(team_id, task, model_id, db, max_tokens=2000):
        from backend.teams import TeamResult

        return TeamResult(team_id, task, synthesis="done", specialists=[])

    monkeypatch.setattr("backend.api_routes.teams_routes.run_team", fake_run)
    client = _api_client(tmp_path, monkeypatch, teams_on=True)
    headers = _auth(client)

    resp = client.get("/api/teams", headers=headers)
    assert resp.status_code == 200
    assert {t["id"] for t in resp.json()} == {"research", "code", "writing"}

    resp = client.post(
        "/api/teams/run",
        json={"team_id": "code", "task": "write fizzbuzz", "model": "test-model"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["synthesis"] == "done"
