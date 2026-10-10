"""
image_gen/service.py — high-level image generation over the engine registry.

Generates images, applies Fooocus-inspired style enhancement, and persists
results through the media pipeline so they render in chat like any image
attachment. Engine resolution is cached per process; failures surface as
ImageGenError with actionable messages.
"""
from __future__ import annotations

import logging

from ..config import settings
from ..schemas import MediaAttachment
from .engines import describe_image_engines, resolve_image_engine
from .styles import enhance_prompt, list_styles
from ..feature_flags import is_enabled

logger = logging.getLogger(__name__)


class ImageGenError(RuntimeError):
    """An image generation failure the user can act on."""


_engine = None
_engine_resolved = False


def reset_image_gen_for_testing() -> None:
    global _engine, _engine_resolved
    _engine = None
    _engine_resolved = False


def _get_engine() -> object | None:
    global _engine, _engine_resolved
    if not _engine_resolved:
        _engine = resolve_image_engine(settings.IMAGE_GEN_ENGINE)
        _engine_resolved = True
        logger.info("image-gen engine: %s", getattr(_engine, "name", None))
    return _engine


def generate_images(
    prompt: str,
    style: str | None = None,
    size: str | None = None,
    n: int = 1,
) -> list[MediaAttachment]:
    """Generate n images; returns saved media attachments. Raises ImageGenError."""
    from ..api_routes.media_routes import save_media_file

    prompt = (prompt or "").strip()
    if not prompt:
        raise ImageGenError("Empty prompt.")
    n = max(1, min(int(n or 1), settings.IMAGE_MAX_IMAGES))
    size = size or settings.IMAGE_DEFAULT_SIZE

    engine = _get_engine()
    if engine is None:
        raise ImageGenError(
            "No image engine available. Set IMAGE_OPENAI_API_KEY, run a local "
            "OpenAI-compatible image server, or start Fooocus locally."
        )
    positive, negative = enhance_prompt(prompt, style)
    try:
        results = engine.generate(positive, negative, size, n)  # type: ignore[union-attr]
    except ImageGenError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("image generation failed: %s", exc)
        raise ImageGenError(f"Image generation failed: {exc}") from exc

    attachments: list[MediaAttachment] = []
    for i, img in enumerate(results[:n]):
        ext = "png" if "png" in img.mime_type else "jpg"
        attachments.append(
            save_media_file(img.data, f"generated_{i + 1}.{ext}", img.mime_type)
        )
    if not attachments:
        raise ImageGenError("The engine returned no images.")
    return attachments


def image_status() -> dict:
    """Status payload for GET /api/image/status."""
    engine = _get_engine()
    return {
        "enabled": is_enabled("image_gen"),
        "engine": getattr(engine, "name", None),
        "engines": describe_image_engines(),
        "styles": list_styles(),
        "max_images": settings.IMAGE_MAX_IMAGES,
    }
