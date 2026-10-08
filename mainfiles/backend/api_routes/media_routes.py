"""
api_routes/media_routes.py — image/audio media upload + serving.

Foundation for the voice (VoiceStudio) and image-generation (Fooocus)
integrations: messages can carry MediaAttachment parts, streamed via the
MEDIA_START / MEDIA_DELTA / MEDIA_END response events and rendered by the
frontend. Media files live under <UPLOAD_DIR>/media/<id>.<ext> with a
sidecar <id>.json holding the attachment metadata.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from ..config import settings
from ..schemas import MediaAttachment
from .common import _get_magic, router

MEDIA_DIR_NAME = "media"

# extension -> (kind, [allowed mime types])
ALLOWED_MEDIA: dict[str, tuple[str, list[str]]] = {
    "png": ("image", ["image/png"]),
    "jpg": ("image", ["image/jpeg"]),
    "jpeg": ("image", ["image/jpeg"]),
    "webp": ("image", ["image/webp"]),
    "gif": ("image", ["image/gif"]),
    "mp3": ("audio", ["audio/mpeg", "audio/mp3"]),
    "wav": ("audio", ["audio/wav", "audio/x-wav", "audio/wave"]),
    "ogg": ("audio", ["audio/ogg"]),
    "webm": ("audio", ["audio/webm", "video/webm"]),
    "m4a": ("audio", ["audio/mp4", "audio/x-m4a"]),
}


def _media_dir() -> Path:
    path = Path(settings.UPLOAD_DIR) / MEDIA_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sidecar_path(media_id: str) -> Path:
    return _media_dir() / f"{media_id}.json"


def load_media_attachment(media_id: str) -> MediaAttachment | None:
    """Load a stored media attachment's metadata (used by chat pipeline)."""
    sidecar = _sidecar_path(media_id)
    if not sidecar.exists():
        return None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return MediaAttachment(**data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def resolve_media_json(media_ids: list[str] | None) -> str | None:
    """Validate media ids and serialize attachments for Message.media_json.

    Unknown ids are skipped (never fail the chat on a bad media id).
    """
    attachments: list[dict] = []
    for mid in media_ids or []:
        attachment = load_media_attachment(mid)
        if attachment is not None:
            attachments.append(attachment.model_dump(mode="json"))
    return json.dumps(attachments) if attachments else None


def media_content_parts(media_json: str | None, text: str) -> list[dict] | None:
    """Build OpenAI-style content parts (text + image_url) for vision models."""
    if not media_json:
        return None
    try:
        attachments = json.loads(media_json)
    except (ValueError, TypeError):
        return None
    images = [a for a in attachments if isinstance(a, dict) and a.get("kind") == "image"]
    if not images:
        return None
    parts: list[dict] = [{"type": "text", "text": text}]
    for attachment in images:
        # Served from the same backend; vision models fetch via URL.
        parts.append({"type": "image_url", "image_url": {"url": attachment.get("url", "")}})
    return parts


@router.post("/media/upload", response_model=MediaAttachment)
async def upload_media(request: Request, file: UploadFile):
    """Upload an image or audio file; returns a MediaAttachment.

    The attachment id can then be passed as `media_ids` on /chat/stream and
    is persisted on the message's media_json column.
    """
    filename = Path(file.filename or "upload").name
    filename = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)
    extension = (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()

    if extension not in ALLOWED_MEDIA:
        raise HTTPException(status_code=415, detail=f"Unsupported media type: .{extension}")

    kind, allowed_mimes = ALLOWED_MEDIA[extension]

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) / (1024 * 1024) > settings.MAX_UPLOAD_SIZE_MB:
                raise HTTPException(status_code=413, detail="File exceeds size limit")
        except ValueError:
            pass

    contents = await file.read()
    if len(contents) / (1024 * 1024) > settings.MAX_UPLOAD_SIZE_MB:
        raise HTTPException(status_code=413, detail="File exceeds size limit")
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file")

    # Magic-byte validation when libmagic is available.
    magic = _get_magic()
    detected_mime = None
    if magic:
        try:
            detected_mime = (magic.from_buffer(contents) or "").split(";")[0].strip()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Could not determine file type") from exc
        if detected_mime not in allowed_mimes:
            raise HTTPException(status_code=415, detail=f"MIME mismatch: {detected_mime}")

    media_id = uuid.uuid4().hex[:12]
    stored = _media_dir() / f"{media_id}.{extension}"
    stored.write_bytes(contents)

    attachment = MediaAttachment(
        id=media_id,
        kind=kind,  # type: ignore[arg-type]
        filename=filename,
        mime_type=detected_mime or allowed_mimes[0],
        size_bytes=len(contents),
        url=f"{settings.API_PREFIX}/media/{media_id}",
        created_at=datetime.now(UTC),
    )
    _sidecar_path(media_id).write_text(attachment.model_dump_json(), encoding="utf-8")
    return attachment


@router.get("/media/{media_id}")
async def get_media(media_id: str):
    """Serve a stored media file by id."""
    if not re.fullmatch(r"[a-f0-9]{12}", media_id or ""):
        raise HTTPException(status_code=400, detail="Invalid media id")
    attachment = load_media_attachment(media_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Media not found")
    # Recover the stored file (extension recorded implicitly via sidecar glob).
    matches = list(_media_dir().glob(f"{media_id}.*"))
    stored = next((p for p in matches if p.suffix != ".json"), None)
    if stored is None or not stored.exists():
        raise HTTPException(status_code=404, detail="Media file missing")
    return FileResponse(path=stored, media_type=attachment.mime_type, filename=attachment.filename)
