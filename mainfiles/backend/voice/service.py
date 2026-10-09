"""
voice/service.py — high-level voice operations over the engine registry.

Thin, never-raise-at-import layer: engine resolution is cached per process,
failures surface as VoiceError with a human-readable message the API turns
into a 502/503.
"""
from __future__ import annotations

import logging
import re

from ..config import settings
from .engines import (
    EngineStatus,
    VoiceInfo,
    describe_engines,
    resolve_stt_engine,
    resolve_tts_engine,
)

logger = logging.getLogger(__name__)


class VoiceError(RuntimeError):
    """A voice operation failed in a way the user can act on."""


_tts_engine = None
_stt_engine = None
_tts_resolved = False
_stt_resolved = False


def reset_voice_for_testing() -> None:
    global _tts_engine, _stt_engine, _tts_resolved, _stt_resolved
    _tts_engine = _stt_engine = None
    _tts_resolved = _stt_resolved = False


def _tts() -> object | None:
    global _tts_engine, _tts_resolved
    if not _tts_resolved:
        _tts_engine = resolve_tts_engine(settings.VOICE_TTS_ENGINE)
        _tts_resolved = True
        logger.info("voice TTS engine: %s", getattr(_tts_engine, "name", None))
    return _tts_engine


def _stt() -> object | None:
    global _stt_engine, _stt_resolved
    if not _stt_resolved:
        _stt_engine = resolve_stt_engine(settings.VOICE_STT_ENGINE)
        _stt_resolved = True
        logger.info("voice STT engine: %s", getattr(_stt_engine, "name", None))
    return _stt_engine


def _clean_for_tts(text: str) -> str:
    """Strip markdown/code that sounds bad spoken aloud."""
    text = re.sub(r"```.*?```", " [code omitted] ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"[*_~]{1,3}", "", text)
    return re.sub(r"\s+", " ", text).strip()


def synthesize(text: str, voice_id: str | None = None) -> tuple[bytes, str]:
    """Text -> (wav_bytes, mime). Raises VoiceError on any failure."""
    cleaned = _clean_for_tts(text)
    if not cleaned:
        raise VoiceError("Nothing to speak: empty text.")
    if len(cleaned) > settings.VOICE_MAX_TTS_CHARS:
        raise VoiceError(
            f"Text too long for TTS ({len(cleaned)} > {settings.VOICE_MAX_TTS_CHARS} chars)."
        )
    engine = _tts()
    if engine is None:
        raise VoiceError(
            "No TTS engine available. Install `kokoro` or set VOICE_OPENAI_BASE_URL."
        )
    try:
        return engine.synthesize(cleaned, voice_id)  # type: ignore[union-attr]
    except VoiceError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("TTS synthesis failed: %s", exc)
        raise VoiceError(f"Speech synthesis failed: {exc}") from exc


def transcribe(audio: bytes, filename: str = "audio.webm") -> str:
    """Audio bytes -> transcript text. Raises VoiceError on any failure."""
    if not audio:
        raise VoiceError("Empty audio.")
    engine = _stt()
    if engine is None:
        raise VoiceError(
            "No STT engine available. Install `faster-whisper` or set VOICE_OPENAI_BASE_URL."
        )
    try:
        text = engine.transcribe(audio, filename)  # type: ignore[union-attr]
    except VoiceError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("STT transcription failed: %s", exc)
        raise VoiceError(f"Transcription failed: {exc}") from exc
    if not text.strip():
        raise VoiceError("No speech detected in the audio.")
    return text.strip()


def list_voices() -> list[VoiceInfo]:
    engine = _tts()
    if engine is None:
        return []
    try:
        return engine.list_voices()  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        logger.debug("list_voices failed: %s", exc)
        return []


def voice_status() -> dict:
    """Status payload for GET /api/voice/status."""
    engines: list[EngineStatus] = describe_engines()
    tts = _tts()
    stt = _stt()
    return {
        "enabled": settings.FEATURE_VOICE,
        "tts_engine": getattr(tts, "name", None),
        "stt_engine": getattr(stt, "name", None),
        "engines": [
            {"name": e.name, "kind": e.kind, "available": e.available, "detail": e.detail}
            for e in engines
        ],
    }
