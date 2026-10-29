"""F6: GET /api/files lists uploaded documents (references only).

Covers: auth-gated, empty-list shape, upload-then-list round trip, and
that the response never leaks server-local stored_path or full extracted
text. Follows the established TestClient + create_app pattern (the
conftest async auth fixture does not create tables, so no existing test
uses it).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ["TEST_MODE"] = "1"

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


def _api_client(tmp_path, monkeypatch):
    import backend.api_routes.files_routes  # noqa: F401 — registers handlers
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    reset_engine_for_testing()

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth_headers(client):
    creds = {"username": "kn_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


def test_files_list_requires_auth(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    with client:
        r = client.get("/api/files")
        assert r.status_code == 401, r.text


def test_files_list_empty_shape(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    with client:
        h = _auth_headers(client)
        r = client.get("/api/files", headers=h)
        assert r.status_code == 200, r.text
        assert r.json() == {"files": []}


def test_files_upload_then_list(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    with client:
        h = _auth_headers(client)
        up = client.post(
            "/api/files",
            headers=h,
            files={"file": ("notes.txt", b"hello sangam", "text/plain")},
        )
        assert up.status_code in (200, 201), up.text
        body = up.json()
        assert body["filename"] == "notes.txt"

        r = client.get("/api/files", headers=h)
        assert r.status_code == 200, r.text
        files = r.json()["files"]
        assert len(files) == 1
        entry = files[0]
        assert entry["id"] == body["file_id"]
        assert entry["filename"] == "notes.txt"
        assert entry["extension"] == "txt"
        assert entry["size_bytes"] == len(b"hello sangam")
        assert entry["created_at"]
        assert "stored_path" not in entry
        assert "extracted_text" not in entry
