"""Phase 0 contract tests: error envelope, pagination, correlation,
run/job state machine, capability manifests, provider telemetry,
artifact storage, and workspace ownership.

These test the new contracts module plus the three live wirings:
runs pagination + RunStore mirror, the 500 error envelope shape, and
cross-user access denial on agents/runs (ownership audit).
"""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from backend.contracts import (  # noqa: E402
    CapabilityKind,
    CapabilityManifest,
    LocalArtifactStore,
    PaginationParams,
    RunState,
    RunStore,
    TelemetryLedger,
    capability_manifest_from_extension,
    correlation_id_for,
    error_envelope,
    paginate,
    redact_error_message,
    run_event,
)


# ------------------------------------------------------------ errors

def test_error_envelope_shape_and_redaction():
    env = error_envelope("not_found", "Bearer abc123 and sk-abcdefghijklmnop",
                         correlation_id="corr-1")
    assert env["error"]["code"] == "not_found"
    assert env["correlation_id"] == "corr-1"
    assert "abc123" not in env["error"]["message"]
    assert "sk-abcdefghijklmnop" not in env["error"]["message"]
    assert "[REDACTED]" in env["error"]["message"]


def test_redact_leaves_plain_messages_alone():
    assert redact_error_message("Provider unavailable") == "Provider unavailable"


# --------------------------------------------------------- pagination

def test_pagination_clamps_and_has_more():
    params = PaginationParams(limit=999, offset=0)
    assert params.limit == 200
    page = paginate([1, 2], total=5, params=params)
    assert page["pagination"] == {"total": 5, "limit": 200, "offset": 0, "has_more": True}
    page2 = paginate([1, 2, 3, 4, 5], total=5, params=PaginationParams(limit=50))
    assert page2["pagination"]["has_more"] is False


def test_pagination_rejects_negative_offset():
    with pytest.raises(Exception):
        PaginationParams(limit=10, offset=-1)


# -------------------------------------------------------- correlation

def test_correlation_id_prefers_middleware_request_id():
    class _State:
        request_id = "req-abc"

    class _Req:
        state = _State()

    assert correlation_id_for(_Req()) == "req-abc"


def test_correlation_id_generated_when_absent():
    class _Req:
        state = object()

    assert correlation_id_for(_Req())


# ------------------------------------------------------------ runs

def test_run_state_machine_guards_terminal_states():
    store = RunStore()
    record = store.create(kind="agent", owner_id="u1", title="t")
    assert record.state == RunState.PENDING
    store.transition(record.run_id, RunState.RUNNING, progress=0.5)
    assert record.progress == 0.5
    store.transition(record.run_id, RunState.SUCCEEDED, progress=1.0)
    with pytest.raises(ValueError):
        store.transition(record.run_id, RunState.RUNNING)
    with pytest.raises(ValueError):
        store.transition(record.run_id, RunState.CANCELLED)


def test_run_cancel_and_event_envelope():
    store = RunStore()
    record = store.create(kind="workflow", owner_id="u1")
    store.transition(record.run_id, RunState.CANCELLED)
    event = run_event(record, "progress", {"note": "stopped"})
    assert event["run_id"] == record.run_id
    assert event["state"] == "cancelled"
    assert event["sequence"] == 1
    assert event["data"]["note"] == "stopped"


def test_run_store_unknown_run():
    with pytest.raises(KeyError):
        RunStore().transition("run-missing", RunState.RUNNING)


def test_run_store_lists_only_owner_runs():
    store = RunStore()
    store.create(kind="agent", owner_id="u1")
    store.create(kind="agent", owner_id="u2")
    assert len(store.list_for_owner("u1")) == 1


# ------------------------------------------------------- capabilities

def test_capability_manifest_validates():
    manifest = CapabilityManifest(
        name="web_search", version="1.0.0", kind=CapabilityKind.TOOL,
        input_schema={"type": "object", "properties": {"q": {"type": "string"}}},
        permissions=["network:read"], side_effects=[],
        resource_limits={"max_seconds": 30}, approval_required=False,
    )
    assert manifest.name == "web_search"
    with pytest.raises(Exception):
        CapabilityManifest(name="bad", version="1.0", kind=CapabilityKind.TOOL)
    with pytest.raises(Exception):
        CapabilityManifest(name="bad", version="1.0.0", kind="not-a-kind")


def test_capability_manifest_from_extension():
    from backend.extensions.manifest import ExtensionKind, ExtensionManifest

    manifest = capability_manifest_from_extension(ExtensionManifest(
        name="web_search", version="2.1.0", kind=ExtensionKind.TOOL,
        description="Search the web", entrypoint="backend.tools:web_search",
    ))
    assert manifest.kind == CapabilityKind.TOOL
    assert manifest.version == "2.1.0"
    with pytest.raises(ValueError):
        capability_manifest_from_extension(ExtensionManifest(
            name="p", version="1.0.0", kind=ExtensionKind.PROVIDER,
        ))


# --------------------------------------------------------- telemetry

def test_telemetry_ledger_totals_and_cost():
    ledger = TelemetryLedger()
    ledger.record("openai", "gpt-4o", latency_ms=100.0, input_tokens=1000,
                  output_tokens=500, input_price_per_1k=0.01,
                  output_price_per_1k=0.02)
    ledger.record("openai", "gpt-4o", latency_ms=200.0, success=False,
                  error="Bearer secret-token-here")
    totals = ledger.totals("openai")
    assert totals["calls"] == 2
    assert totals["failures"] == 1
    assert totals["input_tokens"] == 1000
    assert totals["output_tokens"] == 500
    assert totals["cost_usd"] == pytest.approx(0.02)
    assert totals["avg_latency_ms"] == 150.0


# ---------------------------------------------------------- artifacts

def test_artifact_store_roundtrip_and_traversal_guard(tmp_path):
    store = LocalArtifactStore(tmp_path / "artifacts")
    meta = store.save("art-1.bin", b"hello", "application/octet-stream", "u1")
    assert meta["size_bytes"] == 5
    assert store.get("art-1.bin") == b"hello"
    assert store.metadata("art-1.bin")["size_bytes"] == 5
    assert store.delete("art-1.bin") is True
    assert store.get("art-1.bin") is None
    with pytest.raises(ValueError):
        store.save("../escape.bin", b"x", "text/plain", "u1")
    assert store.get("../escape.bin") is None


# ------------------------------------------------- live wirings (API)

def _api_client(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/phase0.db")
    reset_engine_for_testing()

    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth_headers(client, username):
    creds = {"username": username, "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def test_correlation_header_propagated(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    r = client.get("/api/health", headers={"X-Request-ID": "phase0-corr"})
    assert r.headers.get("X-Request-ID") == "phase0-corr"


def test_runs_pagination_and_runstore_mirror(tmp_path, monkeypatch):
    from backend.contracts import run_store

    client = _api_client(tmp_path, monkeypatch)
    h = _auth_headers(client, "phase0_user")
    r = client.post("/api/runs", json={"kind": "agent", "title": "run one",
                                       "tokens": 42, "cost_usd": 0.01}, headers=h)
    assert r.status_code == 201, r.text
    run_id = r.json()["id"]
    # Live RunStore mirror from record_run.
    mirrored = run_store.get(run_id)
    assert mirrored is not None
    assert mirrored.state == RunState.SUCCEEDED
    assert mirrored.tokens == 42
    # Pagination block alongside the unchanged "runs" list.
    r = client.get("/api/runs?limit=10&offset=0", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["runs"]) == 1
    assert body["pagination"]["total"] == 1
    assert body["pagination"]["has_more"] is False


def test_workspace_ownership_denies_other_user(tmp_path, monkeypatch):
    # Sangam auth is single-user by design: registration is refused
    # once an account exists (auth.py register, user_count check).
    # So the ownership audit seeds another user's rows directly in
    # the DB (the test_agents ownership pattern) and proves the
    # owner never sees them and cannot fetch them by id.
    import asyncio
    import json as _json

    client = _api_client(tmp_path, monkeypatch)
    h1 = _auth_headers(client, "phase0_owner")
    r = client.post("/api/agents", json={"name": "Mine"}, headers=h1)
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    r = client.post("/api/runs", json={"kind": "agent", "title": "my run"}, headers=h1)
    run_id = r.json()["id"]

    async def _seed():
        from backend.database import AsyncSessionLocal
        from backend.models import AgentRun, CustomAgent
        from sqlalchemy import text

        async with AsyncSessionLocal() as db:
            await db.execute(text("PRAGMA foreign_keys=OFF"))
            db.add(CustomAgent(id="otheragent02", user_id="ghost-user-99",
                               name="Theirs", tool_names=_json.dumps([]), max_steps=8))
            db.add(AgentRun(id="run-ghost99", user_id="ghost-user-99",
                            kind="agent", title="their run", status="done"))
            await db.commit()
            await db.execute(text("PRAGMA foreign_keys=ON"))

    asyncio.run(_seed())

    # Owner lists only their own rows.
    assert [a["id"] for a in client.get("/api/agents", headers=h1).json()] == [aid]
    assert [x["id"] for x in client.get("/api/runs", headers=h1).json()["runs"]] == [run_id]
    # Ghost rows are not fetchable as the owner (404, not a leak).
    assert client.get("/api/agents/otheragent02", headers=h1).status_code == 404
    assert client.get("/api/runs/run-ghost99", headers=h1).status_code == 404
    assert client.get(f"/api/runs/{run_id}", headers=h1).status_code == 200
