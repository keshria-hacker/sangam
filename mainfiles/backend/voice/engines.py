"""
voice/engines.py — pluggable TTS/STT engines.

Everything here is optional and lazy: missing pip packages or unreachable
servers make an engine report unavailable instead of raising at import.
Sangam never requires voice dependencies to run.

Engines:
- kokoro          local neural TTS (pip `kokoro`, ~30MB, 2x realtime on CPU)
- faster-whisper  local STT (pip `faster-whisper`, offline)
- openai          any OpenAI-compatible audio server:
                  OpenAI, a local VoiceStudio backend (/v1/audio/*),
                  speaches, etc.
"""
from __future__ import annotations

import io
import logging
import wave
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass
class VoiceInfo:
    id: str
    name: str
    engine: str
    language: str = "en"


@dataclass
class EngineStatus:
    name: str
    kind: str  # "tts" | "stt"
    available: bool
    detail: str = ""


class TTSEngine(Protocol):
    name: str

    def is_available(self) -> bool: ...
    def synthesize(self, text: str, voice_id: str | None = None) -> tuple[bytes, str]:
        """Return (wav_bytes, mime_type). May raise on failure."""
        ...
    def list_voices(self) -> list[VoiceInfo]: ...


class STTEngine(Protocol):
    name: str

    def is_available(self) -> bool: ...
    def transcribe(self, audio: bytes, filename: str = "audio.webm") -> str:
        """Return transcript text. May raise on failure."""
        ...


# --- kokoro (local TTS) --------------------------------------------------------

class KokoroTTSEngine:
    """Local neural TTS. First use downloads the model (~300MB) via HF."""

    name = "kokoro"
    _pipeline: object = None
    _load_error: str = ""

    # A few well-known kokoro voice ids (af_* American, bf_* British, etc.)
    KNOWN_VOICES = [
        "af_heart", "af_bella", "af_nicole", "af_sarah",
        "am_adam", "am_michael", "bf_emma", "bf_isabella", "bm_george",
    ]

    def is_available(self) -> bool:
        if self._pipeline is not None:
            return True
        if self._load_error:
            return False
        try:
            from kokoro import KPipeline  # type: ignore[import-not-found]
        except ImportError as exc:
            self._load_error = f"kokoro not installed: {exc}"
            return False
        try:
            # lang_code 'a' = American English; pipeline downloads weights lazily.
            self._pipeline = KPipeline(lang_code="a")
            return True
        except Exception as exc:  # noqa: BLE001
            self._load_error = str(exc)
            logger.warning("kokoro init failed: %s", exc)
            return False

    def synthesize(self, text: str, voice_id: str | None = None) -> tuple[bytes, str]:
        from ..config import settings

        if not self.is_available():
            raise RuntimeError(f"kokoro unavailable: {self._load_error}")
        voice = voice_id or settings.VOICE_KOKORO_VOICE
        pipeline = self._pipeline
        assert pipeline is not None
        chunks: list[bytes] = []
        sample_rate = 24000
        # kokoro streams per-sentence; concatenate into one wav.
        for _gs, _ps, audio in pipeline(text, voice=voice):  # type: ignore[operator]
            import numpy as np  # type: ignore[import-not-found]

            pcm = (audio.numpy() * 32767).astype("<i2").tobytes()
            chunks.append(pcm)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(b"".join(chunks))
        return buf.getvalue(), "audio/wav"

    def list_voices(self) -> list[VoiceInfo]:
        return [
            VoiceInfo(id=v, name=v.replace("_", " ").title(), engine="kokoro")
            for v in self.KNOWN_VOICES
        ]


# --- faster-whisper (local STT) -------------------------------------------------

class FasterWhisperSTTEngine:
    """Local speech-to-text. First use downloads the model (tiny ~75MB)."""

    name = "faster-whisper"
    _model: object = None
    _load_error: str = ""

    def is_available(self) -> bool:
        if self._model is not None:
            return True
        if self._load_error:
            return False
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-not-found]
        except ImportError as exc:
            self._load_error = f"faster-whisper not installed: {exc}"
            return False
        try:
            from ..config import settings

            self._model = WhisperModel(settings.VOICE_WHISPER_MODEL, device="cpu", compute_type="int8")
            return True
        except Exception as exc:  # noqa: BLE001
            self._load_error = str(exc)
            logger.warning("faster-whisper init failed: %s", exc)
            return False

    def transcribe(self, audio: bytes, filename: str = "audio.webm") -> str:
        if not self.is_available():
            raise RuntimeError(f"faster-whisper unavailable: {self._load_error}")
        import tempfile, os

        model = self._model
        assert model is not None
        suffix = "." + (filename.rsplit(".", 1)[-1] if "." in filename else "webm")
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio)
            tmp_path = tmp.name
        try:
            segments, _info = model.transcribe(tmp_path, beam_size=5)  # type: ignore[operator]
            return " ".join(s.text.strip() for s in segments).strip()
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# --- OpenAI-compatible audio server --------------------------------------------

class OpenAIAudioEngine:
    """TTS + STT via any OpenAI-compatible /v1/audio/* server.

    Covers OpenAI itself, a locally-running VoiceStudio backend
    (POST /v1/audio/speech, POST /v1/audio/transcriptions,
    GET /v1/audio/voices), speaches, and similar servers.
    """

    name = "openai"

    def __init__(self) -> None:
        self._voices_cache: list[VoiceInfo] = []

    def _config(self) -> tuple[str, str | None]:
        from ..config import settings

        base = (settings.VOICE_OPENAI_BASE_URL or "").rstrip("/")
        return base, settings.VOICE_OPENAI_API_KEY

    # -- TTS side --
    def is_available_tts(self) -> bool:
        base, _ = self._config()
        return bool(base)

    def synthesize(self, text: str, voice_id: str | None = None) -> tuple[bytes, str]:
        import httpx

        from ..config import settings

        base, api_key = self._config()
        if not base:
            raise RuntimeError("VOICE_OPENAI_BASE_URL not configured")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        resp = httpx.post(
            f"{base}/v1/audio/speech",
            json={
                "model": settings.VOICE_OPENAI_TTS_MODEL,
                "input": text,
                "voice": voice_id or "alloy",
                "response_format": "wav",
            },
            headers=headers,
            timeout=120,
        )
        resp.raise_for_status()
        return resp.content, "audio/wav"

    def list_voices(self) -> list[VoiceInfo]:
        import httpx

        if self._voices_cache:
            return self._voices_cache
        base, api_key = self._config()
        if not base:
            return []
        try:
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            resp = httpx.get(f"{base}/v1/audio/voices", headers=headers, timeout=15)
            if resp.status_code == 404:
                # Plain OpenAI has no voices endpoint; use stock voices.
                return [VoiceInfo(id=v, name=v.title(), engine="openai") for v in ("alloy", "echo", "fable", "onyx", "nova", "shimmer")]
            resp.raise_for_status()
            data = resp.json()
            items = data.get("voices") or data.get("data") or []
            voices = [
                VoiceInfo(
                    id=str(v.get("id") or v.get("voice_id") or v.get("name", "")),
                    name=str(v.get("name") or v.get("id", "")),
                    engine="openai",
                    language=str(v.get("language", "en")),
                )
                for v in items
                if isinstance(v, dict)
            ]
            self._voices_cache = voices or self._voices_cache
            return self._voices_cache
        except Exception as exc:  # noqa: BLE001
            logger.debug("openai voices list failed: %s", exc)
            return []

    # -- STT side --
    def is_available_stt(self) -> bool:
        base, _ = self._config()
        return bool(base)

    def transcribe(self, audio: bytes, filename: str = "audio.webm") -> str:
        import httpx

        from ..config import settings

        base, api_key = self._config()
        if not base:
            raise RuntimeError("VOICE_OPENAI_BASE_URL not configured")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        resp = httpx.post(
            f"{base}/v1/audio/transcriptions",
            data={"model": settings.VOICE_OPENAI_STT_MODEL},
            files={"file": (filename, audio)},
            headers=headers,
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()
        return str(data.get("text", "")).strip()

    # Protocol compat: is_available dispatches on kind via attribute set by service.
    def is_available(self) -> bool:  # type: ignore[override]
        return self.is_available_tts()


# --- registry -------------------------------------------------------------------

_TTS_PREFERENCE = ("kokoro", "openai")
_STT_PREFERENCE = ("faster-whisper", "openai")


def _build_tts(name: str) -> TTSEngine | None:
    if name == "kokoro":
        return KokoroTTSEngine()
    if name == "openai":
        return OpenAIAudioEngine()  # type: ignore[return-value]
    return None


def _build_stt(name: str) -> STTEngine | None:
    if name == "faster-whisper":
        return FasterWhisperSTTEngine()
    if name == "openai":
        return OpenAIAudioEngine()  # type: ignore[return-value]
    return None


def resolve_tts_engine(configured: str) -> TTSEngine | None:
    """Pick a TTS engine. 'auto' tries each in preference order."""
    names = _TTS_PREFERENCE if configured == "auto" else (configured,)
    for name in names:
        engine = _build_tts(name)
        if engine is not None and engine.is_available():
            return engine
    return None


def resolve_stt_engine(configured: str) -> STTEngine | None:
    names = _STT_PREFERENCE if configured == "auto" else (configured,)
    for name in names:
        engine = _build_stt(name)
        if engine is not None and engine.is_available():
            return engine
    return None


def describe_engines() -> list[EngineStatus]:
    """Availability report for /api/voice/status (probes are cached)."""
    out: list[EngineStatus] = []
    kokoro = KokoroTTSEngine()
    out.append(EngineStatus("kokoro", "tts", kokoro.is_available(), kokoro._load_error))
    whisper = FasterWhisperSTTEngine()
    out.append(EngineStatus("faster-whisper", "stt", whisper.is_available(), whisper._load_error))
    oa = OpenAIAudioEngine()
    from ..config import settings

    base = settings.VOICE_OPENAI_BASE_URL
    out.append(EngineStatus(
        "openai", "tts+stt", oa.is_available(),
        "" if base else "VOICE_OPENAI_BASE_URL not set",
    ))
    return out
