"""
backend.voice — local-first text-to-speech and speech-to-text.

Engines are pluggable and optional (kokoro, faster-whisper, any
OpenAI-compatible audio server such as a local VoiceStudio backend).
Nothing here is imported at app startup cost: engines load lazily on
first use, and every failure degrades to "engine unavailable".
"""
from __future__ import annotations

from .engines import EngineStatus, VoiceInfo
from .service import (
    VoiceError,
    list_voices,
    reset_voice_for_testing,
    synthesize,
    transcribe,
    voice_status,
)


def register_voice_extension() -> bool:
    """Project voice into the unified extension registry (best-effort)."""
    try:
        from ..extensions import ExtensionKind, ExtensionManifest, extensions
    except ImportError:
        return False
    extensions.register(
        ExtensionManifest(
            name="capability:voice",
            version="1.0.0",
            kind=ExtensionKind.CAPABILITY,
            description=(
                "Local-first voice I/O: text-to-speech (kokoro / OpenAI-compat) "
                "and speech-to-text (faster-whisper / OpenAI-compat)."
            ),
            enabled_by_default=True,
        )
    )
    return True


__all__ = [
    "EngineStatus",
    "VoiceError",
    "VoiceInfo",
    "list_voices",
    "register_voice_extension",
    "reset_voice_for_testing",
    "synthesize",
    "transcribe",
    "voice_status",
]
