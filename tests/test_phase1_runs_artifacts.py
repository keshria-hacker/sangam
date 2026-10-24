"""Phase 1 tests: Runs centre API, artifact signed download, retention
pruning, artifact pagination, and signed-token unit behaviour."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from backend.contracts import sign_artifact_token, verify_artifact_token  # noqa: E402


def test_signed_token_roundtrip_tamper_and_expiry():
    token = sign_artifact_token("art-abc123", "user-1", "test-secret", 900)
    payload = verify_artifact_token(token, "test-secret")
    assert payload and payload["artifact_id"] == "art-abc123"
    assert payload["owner_id"] == "user-1"
    # Tampered body, wrong secret, expired token all fail.
    assert verify_artifact_token(token[:-2] + "00", "test-secret") is None
    assert verify_artifact_token(token, "other-secret") is None
    expired = sign_artifact_token("art-abc123", "user-1", "test-secret", -10)
    assert verify_artifact_token(expired, "test-secret") is None


def _api_client(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/phase1.db")
    reset_engine_for_testing()

    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth_headers(client):
    creds = {"username": "phase1_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def test_runs_live_mirrors_recorded_run(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth_headers(client)
    r = client.post("/api/runs", json={"kind": "agent", "title": "live run",
                                       "tokens": 7}, headers=h)
    assert r.status_code == 201, r.text
    r = client.get("/api/runs/live", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pagination"]["total"] == 1
    assert body["runs"][0]["title"] == "live run"
    assert body["runs"][0]["state"] == "succeeded"


def test_runs_live_does_not_swallow_as_run_id(tmp_path, monkeypatch):
    # Regression guard: /runs/live must not be handled by /runs/{run_id}.
    client = _api_client(tmp_path, monkeypatch)
    h = _auth_headers(client)
    r = client.get("/api/runs/live", headers=h)
    assert r.status_code == 200
    assert "runs" in r.json()


def test_artifact_signed_download_end_to_end(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth_headers(client)
    r = client.post("/api/artifacts", json={"title": "My Doc", "type": "doc",
                                            "content": "# Hello"}, headers=h)
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    r = client.post(f"/api/artifacts/{aid}/signed-url", headers=h)
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert url.startswith("/api/artifacts/download?token=")
    # No auth headers on the download itself: the token is the auth.
    r = client.get(url)
    assert r.status_code == 200, r.text
    assert r.text == "# Hello"
    assert "attachment" in r.headers.get("content-disposition", "")
    assert r.headers["content-disposition"].endswith('.md"')
    # Tampered token is rejected, and does not leak existence (403).
    r = client.get("/api/artifacts/download?token=tampered.token")
    assert r.status_code == 403
    # Signed URL for a missing artifact is 404, not a token.
    r = client.post("/api/artifacts/art-missing/signed-url", headers=h)
    assert r.status_code == 404


def test_artifact_pagination_and_prune(tmp_path, monkeypatch):
    import asyncio
    from datetime import UTC, datetime, timedelta

    client = _api_client(tmp_path, monkeypatch)
    h = _auth_headers(client)
    for title in ("new one", "old one"):
        r = client.post("/api/artifacts", json={"title": title, "type": "doc",
                                                "content": "x"}, headers=h)
        assert r.status_code == 201
    # Backdate one artifact directly in the DB.
    async def _backdate():
        from backend.database import AsyncSessionLocal
        from backend.models import Artifact
        from sqlalchemy import select

        async with AsyncSessionLocal() as db:
            art = (await db.execute(
                select(Artifact).where(Artifact.title == "old one"))).scalars().first()
            art.updated_at = datetime.now(UTC) - timedelta(days=100)
            await db.commit()

    asyncio.run(_backdate())
    r = client.get("/api/artifacts?limit=10", headers=h)
    assert r.json()["pagination"]["total"] == 2
    r = client.post("/api/artifacts/retention/prune", json={"days": 90}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 1
    remaining = client.get("/api/artifacts", headers=h).json()["artifacts"]
    assert [a["title"] for a in remaining] == ["new one"]
    # Prune with an invalid window is rejected, not silently ignored.
    r = client.post("/api/artifacts/retention/prune", json={"days": 0}, headers=h)
    assert r.status_code == 422
