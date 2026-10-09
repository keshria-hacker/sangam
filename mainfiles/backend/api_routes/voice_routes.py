"""
api_routes/voice_routes.py — text-to-speech and speech-to-text API.

Gated end-to-end by FEATURE_VOICE (the frontend hides voice UI when off).
Engines are optional: with no TTS/STT engine installed the endpoints answer
503 with an actionable message instead of failing.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..voice import VoiceError, list_voices, synthesize, transcribe, voice_status
from .common import router


def _require_voice() -> None:
    if not settings.FEATURE_VOICE:
        raise HTTPException(status_code=404, detail="Voice is not enabled")


class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    voice: str | None = None


@router.get("/voice/status")
async def get_voice_status():
    """Engine availability: which TTS/STT engines are usable right now."""
    _require_voice()
    return voice_status()


@router.get("/voice/voices")
async def get_voices():
    """Voices offered by the active TTS engine (empty when none)."""
    _require_voice()
    return [
        {"id": v.id, "name": v.name, "engine": v.engine, "language": v.language}
        for v in list_voices()
    ]


@router.post("/voice/tts")
async def text_to_speech(
    payload: TTSIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Synthesize speech; returns audio/wav bytes for immediate playback."""
    _require_voice()
    try:
        audio, mime = synthesize(payload.text, payload.voice)
    except VoiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    from ..analytics import events as _ae, optional_user_id, record_event as _record

    await _record(db, await optional_user_id(request, db), _ae.VOICE_TTS, {})
    return Response(content=audio, media_type=mime)


@router.post("/voice/stt")
async def speech_to_text(
    request: Request,
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
):
    """Transcribe an uploaded audio clip (webm/wav/mp3/ogg/m4a)."""
    _require_voice()
    filename = (file.filename or "audio.webm").rsplit("/", 1)[-1]
    data = await file.read()
    if len(data) / (1024 * 1024) > settings.MAX_UPLOAD_SIZE_MB:
        raise HTTPException(status_code=413, detail="Audio file exceeds size limit")
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio file")
    try:
        text = transcribe(data, filename)
    except VoiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    from ..analytics import events as _ae, optional_user_id, record_event as _record

    await _record(db, await optional_user_id(request, db), _ae.VOICE_STT, {})
    return {"text": text}
