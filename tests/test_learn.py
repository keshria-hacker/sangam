"""Learning mode tests: classroom lesson + tutor feedback, API gating."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import backend.learn.classroom as classroom_mod  # noqa: E402
from backend.learn import (  # noqa: E402
    LearnError,
    register_learn_extension,
    start_lesson,
    tutor_feedback,
)


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "FEATURE_LEARNING", True)
    yield


async def _fake_complete(model_id, messages, db, temperature):
    system = messages[0]["content"]
    if "teacher" in system.lower():
        return "## The big idea\nPhotosynthesis.\n## Check yourself\nQ?\nANSWER: A"
    return "Correct! Follow-up: why?"


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    async def fake_stream(model_id, messages, db, temperature=0.7, max_tokens=None, reasoning_effort=None):
        yield await _fake_complete(model_id, messages, db, temperature)

    import backend.llm as llm_mod

    monkeypatch.setattr(llm_mod, "stream_completion", fake_stream)
    yield


@pytest.mark.asyncio
async def test_start_lesson():
    lesson = await start_lesson("photosynthesis", "model-x", db=None)
    assert lesson.topic == "photosynthesis"
    assert "The big idea" in lesson.content


@pytest.mark.asyncio
async def test_start_lesson_empty_topic():
    with pytest.raises(LearnError, match="Empty topic"):
        await start_lesson("  ", "model-x", db=None)


@pytest.mark.asyncio
async def test_tutor_feedback():
    fb = await tutor_feedback("photosynthesis", "lesson text", "my answer", "model-x", db=None)
    assert "Follow-up" in fb.feedback


@pytest.mark.asyncio
async def test_learn_flag_off(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "FEATURE_LEARNING", False)
    with pytest.raises(LearnError, match="not enabled"):
        await start_lesson("x", "model-x", db=None)


def test_learn_extension_registered():
    from backend.extensions import extensions

    assert register_learn_extension() is True
    assert extensions.get("capability:learning") is not None


# --- API ---------------------------------------------------------------------

def _api_client(tmp_path, monkeypatch, learn_on: bool):
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "FEATURE_LEARNING", learn_on)
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
    creds = {"username": "learn_test_user", "password": "StrongPass123!"}
    resp = client.post("/api/auth/register", json=creds)
    data = resp.json() if resp.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def test_learn_api_404_when_flag_off(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch, learn_on=False)
    headers = _auth(client)
    assert client.post("/api/learn/lesson", json={"topic": "x"}, headers=headers).status_code == 404


def test_learn_api_lesson_and_feedback(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch, learn_on=True)
    headers = _auth(client)

    resp = client.post(
        "/api/learn/lesson", json={"topic": "photosynthesis", "model": "test-model"}, headers=headers
    )
    assert resp.status_code == 200
    lesson = resp.json()["lesson"]
    assert "The big idea" in lesson

    resp = client.post(
        "/api/learn/feedback",
        json={"topic": "photosynthesis", "lesson": lesson, "answer": "plants eat sun", "model": "test-model"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert "Follow-up" in resp.json()["feedback"]
