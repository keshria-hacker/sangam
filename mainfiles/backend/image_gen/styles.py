"""
image_gen/styles.py — Fooocus-inspired style presets and prompt enhancement.

Fooocus's signature idea is "focus on prompting": styles expand a short
user prompt with quality/framing suffixes so the diffusion model gets a
well-formed prompt. These presets are Sangam's own take on that idea —
pure string manipulation, no model download, fully testable.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageStyle:
    id: str
    name: str
    prompt_suffix: str
    negative_suffix: str = ""


STYLES: tuple[ImageStyle, ...] = (
    ImageStyle(
        id="none",
        name="No style",
        prompt_suffix="",
    ),
    ImageStyle(
        id="photographic",
        name="Photographic",
        prompt_suffix=(
            "photograph, ultra detailed, sharp focus, natural lighting, "
            "high resolution, professional photography"
        ),
        negative_suffix="cartoon, illustration, painting, blurry, low quality",
    ),
    ImageStyle(
        id="cinematic",
        name="Cinematic",
        prompt_suffix=(
            "cinematic shot, dramatic lighting, film still, shallow depth of "
            "field, 35mm, moody atmosphere"
        ),
        negative_suffix="blurry, low quality, amateur",
    ),
    ImageStyle(
        id="digital-art",
        name="Digital Art",
        prompt_suffix=(
            "digital artwork, highly detailed, vibrant colors, concept art, "
            "trending on artstation"
        ),
        negative_suffix="blurry, low quality, watermark",
    ),
    ImageStyle(
        id="anime",
        name="Anime",
        prompt_suffix="anime style, cel shaded, vibrant, detailed anime illustration",
        negative_suffix="photorealistic, blurry, low quality",
    ),
    ImageStyle(
        id="portrait",
        name="Portrait",
        prompt_suffix=(
            "portrait, 85mm lens, soft studio lighting, detailed skin texture, "
            "bokeh background"
        ),
        negative_suffix="deformed, blurry, low quality",
    ),
    ImageStyle(
        id="landscape",
        name="Landscape",
        prompt_suffix=(
            "breathtaking landscape, golden hour, epic scale, highly detailed, "
            "national geographic"
        ),
        negative_suffix="blurry, low quality",
    ),
    ImageStyle(
        id="fantasy",
        name="Fantasy",
        prompt_suffix=(
            "epic fantasy art, magical atmosphere, intricate details, "
            "ethereal lighting"
        ),
        negative_suffix="blurry, low quality, modern, photograph",
    ),
)

_STYLE_MAP = {s.id: s for s in STYLES}

# Shared quality floor appended to every styled prompt (Fooocus does the
# same via its default positive/negative prompt templates).
QUALITY_SUFFIX = "masterpiece, best quality, high detail"
QUALITY_NEGATIVE = "low quality, worst quality, blurry, watermark, text"


def get_style(style_id: str | None) -> ImageStyle:
    return _STYLE_MAP.get(style_id or "none", _STYLE_MAP["none"])


def list_styles() -> list[dict[str, str]]:
    return [{"id": s.id, "name": s.name} for s in STYLES]


def enhance_prompt(prompt: str, style_id: str | None = None) -> tuple[str, str]:
    """Return (positive_prompt, negative_prompt) with style applied."""
    prompt = (prompt or "").strip()
    style = get_style(style_id)
    positive = prompt
    if style.prompt_suffix:
        positive = f"{positive}, {style.prompt_suffix}" if positive else style.prompt_suffix
    if QUALITY_SUFFIX and positive:
        positive = f"{positive}, {QUALITY_SUFFIX}"
    negative_parts = [p for p in (style.negative_suffix, QUALITY_NEGATIVE) if p]
    negative = ", ".join(negative_parts)
    return positive, negative
