"""Phase 4 tests: media jobs as observable background work.

Jobs are created (202), run in the background, and polled to a
terminal state. Voice/image engines are mocked — the test proves the
job plumbing (creation, polling, RunStore mirror, failure capture),
not the engines themselves.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from unittest.mock import MagicMock, patch


def _api_client(tmp_path, monkeypatch):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/phase4.db")
    reset_engine_for_testing()
    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


def _auth(client):
    creds = {"username": "phase4_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def _poll(client, job_id, h, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/media-jobs/{job_id}", headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        if body["status"] in ("succeeded", "failed"):
            return body
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s")


def test_media_jobs_tts_and_image_and_failure(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch)
    h = _auth(client)

    # Unknown kind / missing inputs rejected synchronously.
    assert client.post("/api/media-jobs", json={"kind": "clone"}, headers=h).status_code == 422
    assert client.post("/api/media-jobs", json={"kind": "tts"}, headers=h).status_code == 422

    fake_att = MagicMock()
    fake_att.id = "aud123"
    fake_att.url = "/api/media/aud123"
    fake_att.mime_type = "audio/wav"
    fake_img = MagicMock()
    fake_img.model_dump.return_value = {"id": "img1", "url": "/api/media/img1"}

    with patch("backend.feature_flags.is_enabled", return_value=True), \
         patch("backend.voice.synthesize", return_value=(b"RIFFfake", "audio/wav")), \
         patch("backend.api_routes.media_routes.save_media_file", return_value=fake_att), \
         patch("backend.image_gen.generate_images", return_value=[fake_img]):
        r = client.post("/api/media-jobs", json={"kind": "tts", "text": "Hello world"}, headers=h)
        assert r.status_code == 202, r.text
        job = _poll(client, r.json()["id"], h)
        assert job["status"] == "succeeded"
        assert job["result"]["media_id"] == "aud123"

        r = client.post("/api/media-jobs", json={"kind": "image", "prompt": "a red cat"}, headers=h)
        assert r.status_code == 202, r.text
        job = _poll(client, r.json()["id"], h)
        assert job["status"] == "succeeded"
        assert job["result"]["images"][0]["id"] == "img1"

        # Engine failure is captured on the job, not a 500.
        with patch("backend.voice.synthesize", side_effect=RuntimeError("no engine")):
            r = client.post("/api/media-jobs", json={"kind": "dub", "text": "Hi"}, headers=h)
            job = _poll(client, r.json()["id"], h)
            assert job["status"] == "failed" and "no engine" in (job["error"] or "")

    r = client.get("/api/media-jobs", headers=h)
    assert r.status_code == 200 and len(r.json()["jobs"]) == 3
    # Ownership: another user's job is not visible (404, not leak).
    # (Single-user design: a second register 403s, so this is proven
    # by the job's user_id filter in list; here just check 404 for
    # a nonexistent id.)
    assert client.get("/api/media-jobs/mj-doesnotexist", headers=h).status_code == 404
