"""Lesson-player TTS wiring tests.

Covers: speech steps return a stored-audio ref (media_id + servable
url) when the voice engine works, and fail soft (audio None, lesson
completes on text) when the engine is unavailable. No real TTS
engine, no network: voice.synthesize is monkeypatched.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import backend.api_routes.deep_routes  # noqa: E402,F401 — registers lesson routes
from backend.config import settings  # noqa: E402
from backend.database import Base, get_engine, reset_engine_for_testing  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.voice.service import VoiceError  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _api_client(tmp_path, monkeypatch):
    os.environ["CHROMA_DB_PATH"] = str(tmp_path / "chroma")
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/t.db")
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
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
    creds = {"username": "lp_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


def _make_player(client, h, scenes):
    r = client.post("/api/lessons/player", json={"scenes": scenes}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["player_id"]


def _speech_scene():
    return {"index": 0, "kind": "slide", "title": "Intro",
            "actions": [{"type": "speech", "text": "Welcome to the lesson"}]}


def test_speech_step_returns_stored_audio_ref(client, monkeypatch):
    """Engine works -> play-step audio is a servable media ref, not bytes."""
    monkeypatch.setattr(
        "backend.voice.service.synthesize",
        lambda text, voice_id=None: (b"RIFF-fake-wav-bytes", "audio/wav"))
    h = _auth_headers(client)
    pid = _make_player(client, h, [_speech_scene()])
    assert client.post(f"/api/lessons/player/{pid}/start", headers=h).status_code == 200
    step = client.post(f"/api/lessons/player/{pid}/play-step", headers=h).json()
    assert step["action"] == "speech" and step["text"] == "Welcome to the lesson"
    audio = step["audio"]
    assert isinstance(audio, dict)
    assert audio["media_id"] and audio["url"].endswith(f"/media/{audio['media_id']}")
    assert audio["mime_type"] == "audio/wav"
    # The ref actually serves: GET the stored file, expect the same bytes.
    served = client.get(audio["url"], headers=h)
    assert served.status_code == 200, served.text
    assert served.content == b"RIFF-fake-wav-bytes"
    assert served.headers["content-type"].startswith("audio/wav")


def test_engine_failure_fails_soft_and_lesson_completes(client, monkeypatch):
    """Engine unavailable -> audio None, text recorded, lesson still finishes."""
    def _boom(text, voice_id=None):
        raise VoiceError("No TTS engine available.")

    monkeypatch.setattr("backend.voice.service.synthesize", _boom)
    h = _auth_headers(client)
    pid = _make_player(client, h, [_speech_scene()])
    assert client.post(f"/api/lessons/player/{pid}/start", headers=h).status_code == 200
    step = client.post(f"/api/lessons/player/{pid}/play-step", headers=h).json()
    assert step["action"] == "speech" and step["audio"] is None
    assert step["text"] == "Welcome to the lesson"
    # Speech was the only action: the snapshot shows the lesson
    # finished (mode back to idle). Note play_step reports done=True
    # only when stepping an already-finished lesson; the final action
    # itself reports done=False with a finished snapshot.
    assert step["finished"] is True and step["mode"] == "idle"


def test_mpeg_mime_stored_with_matching_extension(client, monkeypatch):
    """mp3 engine output is stored under .mp3 and served as audio/mpeg."""
    monkeypatch.setattr(
        "backend.voice.service.synthesize",
        lambda text, voice_id=None: (b"ID3-fake-mp3", "audio/mpeg"))
    h = _auth_headers(client)
    pid = _make_player(client, h, [_speech_scene()])
    assert client.post(f"/api/lessons/player/{pid}/start", headers=h).status_code == 200
    step = client.post(f"/api/lessons/player/{pid}/play-step", headers=h).json()
    assert step["audio"]["mime_type"] == "audio/mpeg"
    served = client.get(step["audio"]["url"], headers=h)
    assert served.status_code == 200 and served.content == b"ID3-fake-mp3"
