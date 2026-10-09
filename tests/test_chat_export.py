"""Design polish tests: chat markdown export."""
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
    import backend.models  # noqa: F401 — registers tables
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

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
    creds = {"username": "export_test_user", "password": "StrongPass123!"}
    resp = client.post("/api/auth/register", json=creds)
    data = resp.json() if resp.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def _make_chat(client, headers):
    resp = client.post(
        "/api/chats", json={"title": "Export me", "model": "ollama:test-model"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_export_chat_markdown(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    headers = _auth(client)
    chat_id = _make_chat(client, headers)

    # Add messages directly via the API's message path — use the chat detail
    # to confirm creation, then export.
    resp = client.get(f"/api/chats/{chat_id}/export?format=markdown", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"]
    assert "# Export me" in resp.text


def test_export_chat_not_found(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    headers = _auth(client)
    resp = client.get("/api/chats/nope/export?format=markdown", headers=headers)
    assert resp.status_code == 404


def test_export_chat_bad_format(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    headers = _auth(client)
    chat_id = _make_chat(client, headers)
    resp = client.get(f"/api/chats/{chat_id}/export?format=pdf", headers=headers)
    assert resp.status_code == 400


def test_export_chat_requires_auth(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    resp = client.get("/api/chats/abc/export?format=markdown")
    assert resp.status_code in (401, 403)
