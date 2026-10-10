"""Image generation theme tests: styles, engines, service, API, tool."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import backend.image_gen.service as svc  # noqa: E402
from backend.image_gen import (  # noqa: E402
    ImageGenError,
    enhance_prompt,
    generate_images,
    image_status,
    list_styles,
    register_image_gen_extension,
    reset_image_gen_for_testing,
)
from backend.image_gen.engines import (  # noqa: E402
    FooocusEngine,
    GeneratedImage,
    OpenAIImagesEngine,
    resolve_image_engine,
)


@pytest.fixture(autouse=True)
def _reset_img(tmp_path, monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    reset_image_gen_for_testing()
    yield
    reset_image_gen_for_testing()


# --- styles ---------------------------------------------------------------

def test_enhance_prompt_applies_style():
    pos, neg = enhance_prompt("a red barn", "photographic")
    assert pos.startswith("a red barn")
    assert "photograph" in pos and "best quality" in pos
    assert "blurry" in neg


def test_enhance_prompt_unknown_style_falls_back():
    pos, _ = enhance_prompt("a red barn", "nope-not-a-style")
    assert "a red barn" in pos and "best quality" in pos


def test_list_styles():
    styles = list_styles()
    ids = {s["id"] for s in styles}
    assert {"photographic", "cinematic", "anime", "none"} <= ids


# --- engines ---------------------------------------------------------------

def test_openai_engine_needs_key_for_openai_cloud(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "IMAGE_OPENAI_BASE_URL", "https://api.openai.com")
    monkeypatch.setattr(settings, "IMAGE_OPENAI_API_KEY", None)
    assert OpenAIImagesEngine().is_available() is False
    monkeypatch.setattr(settings, "IMAGE_OPENAI_API_KEY", "sk-test")
    assert OpenAIImagesEngine().is_available() is True


def test_openai_engine_local_server_needs_no_key(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "IMAGE_OPENAI_BASE_URL", "http://localhost:9000")
    monkeypatch.setattr(settings, "IMAGE_OPENAI_API_KEY", None)
    assert OpenAIImagesEngine().is_available() is True


def test_fooocus_engine_unavailable_without_server():
    # Nothing listening on FOOOCUS_URL in tests.
    assert FooocusEngine().is_available() is False


def test_resolve_none_when_nothing_available(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "IMAGE_OPENAI_BASE_URL", "https://api.openai.com")
    monkeypatch.setattr(settings, "IMAGE_OPENAI_API_KEY", None)
    assert resolve_image_engine("auto") is None


def test_generate_images_errors_gracefully():
    with pytest.raises(ImageGenError, match="No image engine"):
        generate_images("a cat")


class _FakeEngine:
    name = "fake-img"

    def is_available(self):
        return True

    def generate(self, prompt, negative_prompt="", size="1024x1024", n=1):
        assert "best quality" in prompt  # style enhancement applied
        return [GeneratedImage(b"\x89PNGfake", "image/png") for _ in range(n)]


def test_generate_images_saves_via_media_pipeline(monkeypatch):
    monkeypatch.setattr(svc, "resolve_image_engine", lambda _cfg: _FakeEngine())
    attachments = generate_images("a cat", style="anime", n=1)
    assert len(attachments) == 1
    a = attachments[0]
    assert a.kind == "image" and a.mime_type == "image/png"
    assert a.url.startswith("/api/media/")
    # The file is actually on disk and servable.
    from backend.api_routes.media_routes import load_media_attachment

    assert load_media_attachment(a.id) is not None


def test_image_status_shape(monkeypatch):
    monkeypatch.setattr(svc, "resolve_image_engine", lambda _cfg: _FakeEngine())
    status = image_status()
    assert status["engine"] == "fake-img"
    assert any(e["name"] == "openai" for e in status["engines"])
    assert len(status["styles"]) >= 5


def test_image_gen_extension_registered():
    from backend.extensions import extensions

    assert register_image_gen_extension() is True
    manifest = extensions.get("capability:image_gen")
    assert manifest is not None and manifest.version == "1.0.0"


# --- tool --------------------------------------------------------------------

def test_generate_image_tool_registered():
    import backend.tools.builtin  # noqa: F401 — auto-registers
    from backend.tools.registry import registry

    tool = registry.get("generate_image")
    assert tool is not None
    assert "prompt" in tool.parameters["properties"]


@pytest.mark.asyncio
async def test_generate_image_tool_flag_off(monkeypatch):
    import backend.tools.builtin as builtin_mod
    from backend.config import settings

    monkeypatch.setattr(settings, "FEATURE_IMAGE_GEN", False)
    result = await builtin_mod.generate_image_handler("a cat")
    assert "error" in result and "not enabled" in result["error"]


# --- API ---------------------------------------------------------------------

def _api_client(tmp_path, monkeypatch, image_on: bool):
    import backend.image_gen.service as svc_mod
    from backend.config import settings
    from backend.database import Base, get_engine, reset_engine_for_testing
    from backend.main import create_app
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "FEATURE_IMAGE_GEN", image_on)
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    settings.DATABASE_URL = f"sqlite+aiosqlite:///{tmp_path}/test.db"
    assert "history/sangam.db" not in str(settings.DATABASE_URL)
    reset_engine_for_testing()

    import asyncio

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    svc_mod.reset_image_gen_for_testing()
    return TestClient(create_app())


def _auth(client):
    creds = {"username": "img_test_user", "password": "StrongPass123!"}
    resp = client.post("/api/auth/register", json=creds)
    data = resp.json() if resp.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}", "X-CSRF-Token": data["csrf_token"]}


def test_image_api_404_when_flag_off(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch, image_on=False)
    headers = _auth(client)
    assert client.get("/api/image/status", headers=headers).status_code == 404
    assert client.post("/api/image/generate", json={"prompt": "x"}, headers=headers).status_code == 404


def test_image_api_503_without_engine(tmp_path, monkeypatch):
    client = _api_client(tmp_path, monkeypatch, image_on=True)
    headers = _auth(client)
    resp = client.get("/api/image/status", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["engine"] is None
    resp = client.post("/api/image/generate", json={"prompt": "a cat"}, headers=headers)
    assert resp.status_code == 503


def test_image_api_generate_roundtrip(tmp_path, monkeypatch):
    import backend.image_gen.service as svc_mod

    monkeypatch.setattr(svc_mod, "resolve_image_engine", lambda _cfg: _FakeEngine())
    client = _api_client(tmp_path, monkeypatch, image_on=True)
    headers = _auth(client)
    resp = client.post(
        "/api/image/generate",
        json={"prompt": "a cat", "style": "photographic"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    images = resp.json()["images"]
    assert len(images) == 1 and images[0]["kind"] == "image"
    # The returned attachment is servable.
    media_id = images[0]["id"]
    got = client.get(f"/api/media/{media_id}", headers=headers)
    assert got.status_code == 200
