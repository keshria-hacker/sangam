"""Foundation F4/F6 tests: media message types, SSE media events, feature flags."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mainfiles"))

import asyncio

from backend.api_routes import media_routes
from backend.api_routes.media_routes import (
    ALLOWED_MEDIA,
    _media_dir,
    media_content_parts,
    resolve_media_json,
)
from backend.config import Settings, settings
from backend.response_events import ResponseEventBuilder, ResponseEventType  # noqa: E402
from backend.schemas import (  # noqa: E402
    ChatStreamRequest,
    MediaAttachment,
    MessageOut,
)


def test_media_event_types_exist():
    assert ResponseEventType.MEDIA_START == "media_start"
    assert ResponseEventType.MEDIA_DELTA == "media_delta"
    assert ResponseEventType.MEDIA_END == "media_end"


def test_media_lifecycle():
    builder = ResponseEventBuilder(provider="p", model="m")
    builder.message_start()
    start = builder.media_start("image", metadata={"filename": "a.png"})
    assert start.type == "media_start"
    assert start.metadata["media_kind"] == "image"
    delta = builder.media_delta("aGVsbG8=")
    assert delta.type == "media_delta"
    end = builder.media_end(url="/api/media/abc123")
    assert end.type == "media_end"
    assert end.metadata["media_url"] == "/api/media/abc123"
    builder.message_end()  # must not raise: media block closed


def test_media_block_must_close_before_message_end():
    builder = ResponseEventBuilder(provider="p", model="m")
    builder.message_start()
    builder.media_start("audio")
    with pytest.raises(RuntimeError):
        builder.message_end()


def test_media_delta_outside_block_raises():
    builder = ResponseEventBuilder(provider="p", model="m")
    builder.message_start()
    with pytest.raises(RuntimeError):
        builder.media_delta("xx")


def test_chat_stream_request_accepts_media_ids():
    req = ChatStreamRequest(
        model="ollama::llama3.2",
        messages=[{"role": "user", "content": "describe this"}],
        media_ids=["abc123def456"],
    )
    assert req.media_ids == ["abc123def456"]


def test_chat_message_parts_validation():
    req = ChatStreamRequest(
        model="ollama::llama3.2",
        messages=[{
            "role": "user",
            "content": "look",
            "parts": [{"type": "image", "url": "http://x/y.png", "mime_type": "image/png"}],
        }],
    )
    part = req.messages[0].parts[0]
    assert part.type == "image"
    assert part.mime_type == "image/png"


def test_message_out_hydrates_media_from_orm():
    class FakeMessage:
        id = "m1"
        role = "user"
        content = "hi"
        model = None
        response_time = None
        feedback = None
        feedback_note = None
        created_at = "2026-10-08T00:00:00"
        media_json = json.dumps([{
            "id": "abc123def456", "kind": "image", "filename": "a.png",
            "mime_type": "image/png", "size_bytes": 10, "url": "/api/media/abc123def456",
        }])

    out = MessageOut.model_validate(FakeMessage())
    assert out.content_type == "multimodal"
    assert len(out.media) == 1
    assert isinstance(out.media[0], MediaAttachment)
    assert out.media[0].kind == "image"


def test_message_out_text_default():
    class FakeMessage:
        id = "m2"
        role = "assistant"
        content = "hello"
        model = "x"
        response_time = 1.0
        feedback = None
        feedback_note = None
        created_at = "2026-10-08T00:00:00"
        media_json = None

    out = MessageOut.model_validate(FakeMessage())
    assert out.content_type == "text"
    assert out.media == []


def test_message_out_survives_bad_media_json():
    class FakeMessage:
        id = "m3"
        role = "user"
        content = "hi"
        model = None
        response_time = None
        feedback = None
        feedback_note = None
        created_at = "2026-10-08T00:00:00"
        media_json = "not-json{{{"

    out = MessageOut.model_validate(FakeMessage())
    assert out.content_type == "text"
    assert out.media == []


def test_feature_flags_shape():
    s = Settings(_env_file=None)
    flags = s.feature_flags()
    assert set(flags) == {"voice", "image_gen", "mcp", "multi_agent", "analytics", "spec_kit", "learning"}
    assert all(isinstance(v, bool) for v in flags.values())
    assert s.API_VERSION == "v1"


def test_mcp_server_configs_parsing():
    s = Settings(_env_file=None)
    assert s.mcp_server_configs() == []
    s2 = Settings(_env_file=None, MCP_SERVERS_JSON='[{"name":"x","command":["y"]}]')
    assert s2.mcp_server_configs() == [{"name": "x", "command": ["y"]}]
    s3 = Settings(_env_file=None, MCP_SERVERS_JSON='not json')
    assert s3.mcp_server_configs() == []


def test_media_routes_helpers():
    assert ALLOWED_MEDIA["png"][0] == "image"
    assert ALLOWED_MEDIA["mp3"][0] == "audio"
    assert _media_dir().name == "media"


def test_resolve_media_json_skips_unknown():
    assert resolve_media_json(None) is None
    assert resolve_media_json(["nope-not-real"]) is None


def test_media_content_parts_builder():
    assert media_content_parts(None, "hi") is None
    media_json = json.dumps([{
        "id": "a1", "kind": "image", "filename": "a.png", "mime_type": "image/png",
        "size_bytes": 1, "url": "/api/media/a1",
    }])
    parts = media_content_parts(media_json, "describe")
    assert parts[0] == {"type": "text", "text": "describe"}
    assert parts[1]["type"] == "image_url"
    # audio-only attachments produce no vision parts
    audio_json = json.dumps([{
        "id": "a2", "kind": "audio", "filename": "a.mp3", "mime_type": "audio/mpeg",
        "size_bytes": 1, "url": "/api/media/a2",
    }])
    assert media_content_parts(audio_json, "transcribe") is None


def test_upload_and_serve_media(tmp_path, monkeypatch):
    """End-to-end: upload a PNG via the route function, then serve it back."""


    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path)

    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    class FakeUpload:
        filename = "test.png"

        async def read(self):
            return png

    class FakeRequest:
        headers = {}

    async def go():
        att = await media_routes.upload_media(FakeRequest(), FakeUpload())
        assert att.kind == "image"
        assert att.size_bytes == len(png)
        assert media_routes.load_media_attachment(att.id) is not None
        resp = await media_routes.get_media(att.id)
        assert resp.status_code == 200
        # unknown id -> 404
        with pytest.raises(HTTPException):
            await media_routes.get_media("000000000000")
        return att

    asyncio.run(go())
    # sidecar + file persisted
    assert list((tmp_path / "media").glob("*.json"))
