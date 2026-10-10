"""
backend.image_gen — image generation with pluggable engines.

Fooocus-inspired: style presets + prompt enhancement ("focus on prompting"),
an OpenAI-compatible engine for reliable generation, and an experimental
driver for a locally-running Fooocus Gradio UI. Results persist through the
media pipeline so generated images render in chat like any attachment.
"""
from __future__ import annotations

from .engines import GeneratedImage
from .service import ImageGenError, generate_images, image_status, reset_image_gen_for_testing
from .styles import enhance_prompt, get_style, list_styles


def register_image_gen_extension() -> bool:
    """Project image generation into the unified extension registry."""
    try:
        from ..extensions import ExtensionKind, ExtensionManifest, extensions
    except ImportError:
        return False
    extensions.register(
        ExtensionManifest(
            name="capability:image_gen",
            version="1.0.0",
            kind=ExtensionKind.CAPABILITY,
            description=(
                "Image generation: Fooocus-inspired styles + prompt enhancement, "
                "OpenAI-compatible engine, experimental local Fooocus driver."
            ),
            enabled_by_default=True,
        )
    )
    return True


__all__ = [
    "GeneratedImage",
    "ImageGenError",
    "enhance_prompt",
    "generate_images",
    "get_style",
    "image_status",
    "list_styles",
    "register_image_gen_extension",
    "reset_image_gen_for_testing",
]
