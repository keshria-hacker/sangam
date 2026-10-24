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
from .engines import (
    FooocusControls,
    UnsupportedImageControl,
    describe_fooocus_controls,
    describe_image_engines,
    resolve_image_engine,
)
from .styles import enhance_prompt, list_styles, prepare_prompt
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
    controls: FooocusControls | dict | None = None,
    wildcards_dir=None,
    wildcard_seed: int | None = None,
    wildcard_in_order: bool = False,
    wildcard_words: dict[str, list[str]] | None = None,
) -> list[MediaAttachment]:
    """Generate n images; returns saved media attachments. Raises ImageGenError.

    Fooocus controls (Wave-2): ``controls`` may be a FooocusControls or a
    plain dict with its fields. Preprocessing order is Fooocus order:
    wildcards expand first, then style enhancement, then prompt-weight
    parsing. Wildcard expansion is pure text substitution and works on
    any engine; prompt weights are honoured only by engines whose
    supported_controls include the Fooocus set — on any other engine a
    prompt carrying a non-1.0 weight raises UnsupportedImageControl
    (422 at the route) instead of silently dropping the emphasis.
    Unknown engines (no supported_controls attribute, e.g. test doubles)
    are treated as supporting controls only when they accept a
    ``controls`` keyword; otherwise the control request is a 422.
    """
    from ..api_routes.media_routes import save_media_file

    prompt = (prompt or "").strip()
    if not prompt:
        raise ImageGenError("Empty prompt.")
    n = max(1, min(int(n or 1), settings.IMAGE_MAX_IMAGES))
    size = size or settings.IMAGE_DEFAULT_SIZE

    if isinstance(controls, dict):
        from .engines import LoRARef

        controls = FooocusControls(
            sampler=controls.get("sampler"), scheduler=controls.get("scheduler"),
            steps=controls.get("steps"), cfg=controls.get("cfg"),
            seed=controls.get("seed"), sharpness=controls.get("sharpness"),
            clip_skip=controls.get("clip_skip"),
            loras=[LoRARef(**l) if isinstance(l, dict) else l
                   for l in (controls.get("loras") or [])],
            embeddings=list(controls.get("embeddings") or []),
        )
    if controls is not None:
        controls.validate()

    engine = _get_engine()
    if engine is None:
        raise ImageGenError(
            "No image engine available. Set IMAGE_OPENAI_API_KEY, run a local "
            "OpenAI-compatible image server, or start Fooocus locally."
        )
    expanded, plain, segments = prepare_prompt(
        prompt, wildcards_dir=wildcards_dir, seed=wildcard_seed,
        in_order=wildcard_in_order, wordlists=wildcard_words)
    weighted = [(t, w) for t, w in segments if w != 1.0]
    positive, negative = enhance_prompt(expanded, style)
    # enhance_prompt appends style/quality suffixes after the user text;
    # weights were parsed from the expanded user prompt, so re-derive the
    # plain positive text by stripping weight syntax from the styled text.
    from .styles import parse_prompt_weights as _parse_weights

    plain_positive, _ = _parse_weights(positive)
    if controls is not None:
        controls.prompt_weights = segments
    if weighted:
        supported = getattr(engine, "supported_controls", None)
        if supported is not None and not supported:
            raise UnsupportedImageControl(
                "Prompt weights (word:1.3) are not supported by the "
                f"{getattr(engine, 'name', 'selected')} engine; use the fooocus "
                "engine or remove the weights.")
    try:
        import inspect as _inspect

        kwargs: dict = {}
        if controls is not None:
            params = _inspect.signature(engine.generate).parameters  # type: ignore[union-attr]
            if "controls" in params or any(
                    p.kind == _inspect.Parameter.VAR_KEYWORD for p in params.values()):
                kwargs["controls"] = controls
            else:
                raise UnsupportedImageControl(
                    f"The {getattr(engine, 'name', 'selected')} engine does not "
                    "accept Fooocus controls.")
        results = engine.generate(plain_positive, negative, size, n, **kwargs)  # type: ignore[union-attr]
    except UnsupportedImageControl:
        raise
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
        "fooocus_controls": describe_fooocus_controls(),
    }
