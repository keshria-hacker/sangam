"""
backend/image_ops.py — image operations on the engine abstraction
(Batch 7, Fooocus feature set minus FaceSwap).

Capability matrix (mirrors image_gen/engines.py docstring):
  op            openai engine                   fooocus engine
  vary          variations() API call           unsupported -> 422
  upscale       API does not offer it           unsupported
                -> Pillow lanczos local resize, labelled "local resize,
                   not AI upscaling"; if Pillow is absent -> 422
  inpaint       edits() with a mask             unsupported -> 422
  outpaint      edits() with a generated        unsupported -> 422
                border mask (Pillow) or caller mask
  image-prompt  edits() with source image       unsupported -> 422
  describe      NOT here: chat-provider vision path in image_routes.py

Unsupported always means HTTP 422 with a plain message — never a fake
image, never a silent no-op. The ops layer checks for the engine
method (variations/edits/upscale); a fake engine in tests that defines
the method counts as supporting the op.

Deferred (not in this batch, noted not built): prompt weights,
wildcards, LoRA, embeddings, sampler/scheduler/sharpness controls,
FaceSwap (excluded: consent-sensitive).
"""
from __future__ import annotations

import io

from .image_gen.engines import GeneratedImage


class UnsupportedOp(RuntimeError):
    """An op the resolved engine does not support (maps to HTTP 422)."""


def get_engine():
    """Resolve the configured image engine (cached, see image_gen.service)."""
    from .image_gen import service

    return service._get_engine()


def _require_engine():
    engine = get_engine()
    if engine is None:
        raise UnsupportedOp(
            "No image engine available. Set IMAGE_OPENAI_API_KEY or run a "
            "local OpenAI-compatible image server."
        )
    return engine


def _method(engine, *names):
    for name in names:
        fn = getattr(engine, name, None)
        if callable(fn):
            return fn
    return None


def vary(image_bytes: bytes, strength: str = "subtle", engine=None) -> tuple[list[GeneratedImage], str]:
    """Vary an image. OpenAI's variations endpoint takes no strength
    parameter, so strength is recorded as advisory only."""
    engine = engine or _require_engine()
    fn = _method(engine, "vary", "variations")
    if fn is None:
        raise UnsupportedOp(f"Vary is not supported by the {getattr(engine, 'name', 'current')} engine.")
    return fn(image_bytes), f"engine variations (strength '{strength}' is advisory; the variations API takes no strength parameter)"


def upscale(image_bytes: bytes, factor: float = 2.0, engine=None) -> tuple[list[GeneratedImage], str]:
    """Upscale. Engine-native if offered, else Pillow lanczos resize."""
    engine = engine or _require_engine()
    fn = _method(engine, "upscale")
    if fn is not None:
        return fn(image_bytes, factor), "engine upscaling"
    try:
        from PIL import Image  # type: ignore[import-not-found]

        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        w, h = img.size
        resized = img.resize((max(1, round(w * factor)), max(1, round(h * factor))), Image.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format="PNG")
    except ImportError as exc:
        raise UnsupportedOp(
            f"Upscaling is not supported by the {getattr(engine, 'name', 'current')} engine, "
            "and Pillow is not installed for a local resize."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise UnsupportedOp(f"Pillow could not resize this image for a local upscale: {exc}") from exc
    return [GeneratedImage(buf.getvalue(), "image/png")], "local resize, not AI upscaling"


def _border_mask(image_bytes: bytes, factor: float = 1.5) -> tuple[bytes, bytes]:
    """Build an outpaint canvas + mask with Pillow.

    Returns (expanded_image, mask): the original centered on a larger
    transparent canvas, and a mask that is opaque over the original
    (keep) and transparent at the border (edit) — OpenAI mask semantics.
    """
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    img.load()
    w, h = img.size
    nw, nh = max(1, round(w * factor)), max(1, round(h * factor))
    canvas = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
    canvas.paste(img, ((nw - w) // 2, (nh - h) // 2))
    mask = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
    mask.paste((0, 0, 0, 255), ((nw - w) // 2, (nh - h) // 2, (nw - w) // 2 + w, (nh - h) // 2 + h))
    img_buf, mask_buf = io.BytesIO(), io.BytesIO()
    canvas.save(img_buf, format="PNG")
    mask.save(mask_buf, format="PNG")
    return img_buf.getvalue(), mask_buf.getvalue()


def inpaint(image_bytes: bytes, prompt: str, mask_bytes: bytes | None = None, engine=None) -> tuple[list[GeneratedImage], str]:
    """Inpaint the masked area. A mask is required (the caller uploads a
    PNG mask); without one the op cannot know what to change."""
    engine = engine or _require_engine()
    fn = _method(engine, "edits", "edit", "inpaint")
    if fn is None:
        raise UnsupportedOp(f"Inpaint is not supported by the {getattr(engine, 'name', 'current')} engine.")
    if mask_bytes is None:
        raise UnsupportedOp("Inpaint needs a mask image (PNG) marking the area to repaint.")
    return fn(image_bytes, prompt, mask_bytes), "engine edits with mask"


def outpaint(image_bytes: bytes, prompt: str, mask_bytes: bytes | None = None, engine=None) -> tuple[list[GeneratedImage], str]:
    """Outpaint the border. With no caller mask, Pillow builds an expanded
    canvas + border mask; without Pillow, a mask is required."""
    engine = engine or _require_engine()
    fn = _method(engine, "edits", "edit", "outpaint")
    if fn is None:
        raise UnsupportedOp(f"Outpaint is not supported by the {getattr(engine, 'name', 'current')} engine.")
    if mask_bytes is None:
        try:
            image_bytes, mask_bytes = _border_mask(image_bytes)
        except ImportError as exc:
            raise UnsupportedOp("Outpaint needs a mask image (PNG), or Pillow installed to build one.") from exc
    return fn(image_bytes, prompt, mask_bytes), "engine edits with border mask"


def image_prompt(image_bytes: bytes, prompt: str, engine=None) -> tuple[list[GeneratedImage], str]:
    """Image-prompt (img2img): source image + prompt via edits."""
    engine = engine or _require_engine()
    fn = _method(engine, "edits", "edit", "image_prompt")
    if fn is None:
        raise UnsupportedOp(f"Image-prompt is not supported by the {getattr(engine, 'name', 'current')} engine.")
    return fn(image_bytes, prompt, None), "engine edits with source image"
