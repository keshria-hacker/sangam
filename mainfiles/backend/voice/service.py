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
from ..feature_flags import is_enabled
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
        "enabled": is_enabled("voice"),
        "tts_engine": getattr(tts, "name", None),
        "stt_engine": getattr(stt, "name", None),
        "engines": [
            {"name": e.name, "kind": e.kind, "available": e.available, "detail": e.detail}
            for e in engines
        ],
    }


def synthesize_chunked(text: str, voice_id: str | None = None,
                       max_chars: int = 800, gap_ms: int = 250) -> dict:
    """Long-form TTS: chunk at sentence/clause boundaries, synthesise
    each chunk, join same-format WAV chunks with silence gaps.

    Returns {chunks, audio, mime} on success. Non-WAV engine output
    raises VoiceError rather than producing a corrupt join.
    """
    from ..media_pipeline.audio import chunk_text, join_wav_bytes
    cleaned = _clean_for_tts(text)
    if not cleaned:
        raise VoiceError("Nothing to speak: empty text.")
    chunks = chunk_text(cleaned, max_chars=max_chars)
    engine = _tts()
    if engine is None:
        raise VoiceError("No TTS engine available.")
    parts, mime = [], None
    for chunk in chunks:
        audio, chunk_mime = engine.synthesize(chunk["text"], voice_id)  # type: ignore[union-attr]
        parts.append(audio)
        mime = chunk_mime
    if mime and "wav" not in mime:
        raise VoiceError(
            f"Chunked TTS needs WAV output to join chunks safely; engine "
            f"returned {mime}. Synthesise chunks individually instead.")
    try:
        joined = join_wav_bytes(parts, gap_ms=gap_ms) if len(parts) > 1 else parts[0]
    except ValueError as exc:
        raise VoiceError(str(exc)) from exc
    return {"chunks": chunks, "audio": joined, "mime": mime or "audio/wav",
            "gaps_ms": [gap_ms] * (len(parts) - 1)}


def transcribe_segments(audio: bytes, filename: str = "audio.webm") -> list[dict]:
    """Timed ASR segments, when the STT engine exposes them.

    Sangam's current engines return plain text only, so this raises a
    VoiceError saying timed segments are unavailable — callers (true
    dubbing) must supply timed segments instead of receiving invented
    timings. An engine that implements ``transcribe_segments`` is used
    when present.
    """
    engine = _stt()
    if engine is None:
        raise VoiceError("No STT engine available.")
    fn = getattr(engine, "transcribe_segments", None)
    if fn is None:
        raise VoiceError(
            "The active STT engine returns plain text only, without timings. "
            "True dubbing needs timed segments: supply segments explicitly "
            "to /voice/dub, or use an STT engine that exposes segments.")
    return fn(audio, filename)
