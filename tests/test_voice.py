"""Voice theme tests: engine registry, service, API gating."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import backend.voice.service as svc  # noqa: E402
from backend.voice import (  # noqa: E402
    VoiceError,
    register_voice_extension,
    reset_voice_for_testing,
    voice_status,
)
from backend.voice.engines import (  # noqa: E402
    FasterWhisperSTTEngine,
    KokoroTTSEngine,
    OpenAIAudioEngine,
    resolve_stt_engine,
    resolve_tts_engine,
)
from backend.voice.service import _clean_for_tts  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_voice():
    reset_voice_for_testing()
    yield
    reset_voice_for_testing()


# --- engines ---------------------------------------------------------------

def test_engines_degrade_gracefully_when_missing():
    # kokoro / faster-whisper are not installed in the test env.
    assert KokoroTTSEngine().is_available() is False
    assert FasterWhisperSTTEngine().is_available() is False
    # OpenAI engine without a base URL is unavailable.
    assert OpenAIAudioEngine().is_available() is False


def test_resolve_returns_none_without_engines():
    assert resolve_tts_engine("auto") is None
    assert resolve_stt_engine("auto") is None
    assert resolve_tts_engine("none") is None


def test_voice_error_when_no_engine():
    with pytest.raises(VoiceError, match="No TTS engine"):
        svc.synthesize("hello")
    with pytest.raises(VoiceError, match="No STT engine"):
        svc.transcribe(b"fake-audio")


def test_clean_for_tts_strips_markdown():
    cleaned = _clean_for_tts("# Title\n\nSome `code` and [link](http://x).\n```py\nprint(1)\n```")
    assert "#" not in cleaned and "`" not in cleaned
    assert "code omitted" in cleaned
    assert "Title" in cleaned


class _FakeTTS:
    name = "fake-tts"

    def is_available(self):
        return True

    def synthesize(self, text, voice_id=None):
        return b"RIFFfake-wav", "audio/wav"

    def list_voices(self):
        from backend.voice import VoiceInfo

        return [VoiceInfo(id="v1", name="Test Voice", engine="fake-tts")]


class _FakeSTT:
    name = "fake-stt"

    def is_available(self):
        return True

    def transcribe(self, audio, filename="audio.webm"):
        return "hello world"


def test_service_uses_resolved_engines(monkeypatch):
    monkeypatch.setattr(svc, "resolve_tts_engine", lambda _cfg: _FakeTTS())
    monkeypatch.setattr(svc, "resolve_stt_engine", lambda _cfg: _FakeSTT())
    audio, mime = svc.synthesize("Hello **there**!")
    assert mime == "audio/wav" and audio.startswith(b"RIFF")
    assert svc.transcribe(b"bytes", "a.webm") == "hello world"
    assert svc.list_voices()[0].id == "v1"
    status = voice_status()
    assert status["tts_engine"] == "fake-tts"
    assert status["stt_engine"] == "fake-stt"


def test_voice_extension_registered():
    from backend.extensions import extensions

    assert register_voice_extension() is True
    manifest = extensions.get("capability:voice")
    assert manifest is not None and manifest.version == "1.0.0"


# --- API --------------------------------------------------------------------

def _api_client(tmp_path, monkeypatch, voice_on: bool):
    import backend.voice.service as svc_mod
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "FEATURE_VOICE", voice_on)
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    assert "history/sangam.db" not in str(settings.DATABASE_URL)
    reset_engine_for_testing()

    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    svc_mod.reset_voice_for_testing()
    return TestClient(create_app())


def _auth(client):
    creds = {"username": "voice_test_user", "password": "StrongPass123!"}
    resp = client.post("/api/auth/register", json=creds)
    data = resp.json() if resp.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def test_voice_api_404_when_flag_off(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch, voice_on=False)
    headers = _auth(client)
    assert client.get("/api/voice/status", headers=headers).status_code == 404
    assert client.post("/api/voice/tts", json={"text": "hi"}, headers=headers).status_code == 404


def test_voice_api_503_without_engine(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch, voice_on=True)
    headers = _auth(client)
    resp = client.get("/api/voice/status", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["tts_engine"] is None
    resp = client.post("/api/voice/tts", json={"text": "hi"}, headers=headers)
    assert resp.status_code == 503
    resp = client.post(
        "/api/voice/stt",
        files={"file": ("a.webm", b"fake", "audio/webm")},
        headers=headers,
    )
    assert resp.status_code == 503


def test_voice_api_roundtrip_with_fake_engines(tmp_path, monkeypatch):
    import backend.voice.service as svc_mod

    monkeypatch.setattr(svc_mod, "resolve_tts_engine", lambda _cfg: _FakeTTS())
    monkeypatch.setattr(svc_mod, "resolve_stt_engine", lambda _cfg: _FakeSTT())
    client = _api_client(tmp_path, monkeypatch, voice_on=True)
    headers = _auth(client)

    resp = client.get("/api/voice/voices", headers=headers)
    assert resp.status_code == 200 and resp.json()[0]["id"] == "v1"

    resp = client.post("/api/voice/tts", json={"text": "hello"}, headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.content.startswith(b"RIFF")

    resp = client.post(
        "/api/voice/stt",
        files={"file": ("a.webm", b"fake", "audio/webm")},
        headers=headers,
    )
    assert resp.status_code == 200 and resp.json() == {"text": "hello world"}
