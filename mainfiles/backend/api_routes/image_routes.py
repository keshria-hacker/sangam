"""
api_routes/image_routes.py — image generation API.

Gated end-to-end by FEATURE_IMAGE_GEN (the frontend hides image UI when off).
Generated images persist through the media pipeline and return as
MediaAttachments, so they render in chat like any image.
"""
from __future__ import annotations

import base64

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from .. import llm
from ..config import settings
from ..feature_flags import is_enabled
from ..database import get_db
from ..image_gen import ImageGenError, generate_images, image_status
from ..image_gen.engines import FooocusControls, LoRARef, UnsupportedImageControl
from ..image_ops import UnsupportedOp, image_prompt, inpaint, outpaint, upscale, vary
from .common import router
from .media_routes import save_media_file


def _require_image_gen() -> None:
    if not is_enabled("image_gen"):
        raise HTTPException(status_code=404, detail="Image generation is not enabled")


class LoRAIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    weight: float = Field(default=1.0, ge=-2.0, le=2.0)  # Fooocus LoRA clamp


class ImageGenIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    style: str | None = None
    size: str | None = Field(default=None, pattern=r"^\d+x\d+$")
    n: int = Field(default=1, ge=1, le=4)
    # Fooocus diffusion controls — honoured only by the fooocus engine;
    # any requested control on another engine returns 422, never a fake.
    sampler: str | None = None
    scheduler: str | None = None
    steps: int | None = Field(default=None, ge=1, le=150)
    cfg: float | None = Field(default=None, ge=0.0, le=30.0)
    seed: int | None = None
    sharpness: float | None = Field(default=None, ge=0.0, le=30.0)
    clip_skip: int | None = Field(default=None, ge=1, le=12)
    loras: list[LoRAIn] = Field(default_factory=list)
    embeddings: list[str] = Field(default_factory=list)
    # Inline wildcard wordlists for __name__ expansion (file-based
    # expansion lives in the service layer via wildcards_dir).
    wildcard_words: dict[str, list[str]] | None = None
    wildcard_seed: int | None = None
    wildcard_in_order: bool = False
    # Batch 11: Performance preset (quality/speed/extreme/lightning/hyper)
    # as an engine-parameter bundle, and explicit prompt expansion.
    performance: str | None = None
    expand_prompt: bool = False
    metadata: bool = False


@router.get("/image/status")
async def get_image_status():
    """Engine availability + style presets."""
    _require_image_gen()
    return image_status()


@router.post("/image/generate")
async def generate_image_endpoint(
    payload: ImageGenIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Generate images; returns saved media attachments."""
    _require_image_gen()
    controls = None
    if (payload.sampler or payload.scheduler or payload.steps is not None
            or payload.cfg is not None or payload.seed is not None
            or payload.sharpness is not None or payload.clip_skip is not None
            or payload.loras or payload.embeddings):
        controls = FooocusControls(
            sampler=payload.sampler, scheduler=payload.scheduler,
            steps=payload.steps, cfg=payload.cfg, seed=payload.seed,
            sharpness=payload.sharpness, clip_skip=payload.clip_skip,
            loras=[LoRARef(name=l.name, weight=l.weight) for l in payload.loras],
            embeddings=list(payload.embeddings),
        )
    try:
        from ..image_gen.service import generate_images_with_sidecar
        if payload.metadata or payload.expand_prompt or payload.performance:
            attachments, sidecar = generate_images_with_sidecar(
                payload.prompt, style=payload.style, size=payload.size, n=payload.n,
                controls=controls, performance=payload.performance,
                expand_prompt=payload.expand_prompt,
                wildcard_seed=payload.wildcard_seed,
                wildcard_in_order=payload.wildcard_in_order,
                wildcard_words=payload.wildcard_words,
            )
        else:
            attachments = generate_images(
                payload.prompt, style=payload.style, size=payload.size, n=payload.n,
                controls=controls, wildcard_seed=payload.wildcard_seed,
                wildcard_in_order=payload.wildcard_in_order,
                wildcard_words=payload.wildcard_words,
            )
            sidecar = None
    except UnsupportedImageControl as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        # FooocusControls.validate() failures (bad sampler/scheduler/range)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ImageGenError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    from ..analytics import events as _ae, optional_user_id, record_event as _record

    await _record(db, await optional_user_id(request, db), _ae.IMAGE_GENERATED,
                  {"n": payload.n})
    out: dict = {"images": [a.model_dump(mode="json") for a in attachments]}
    if sidecar is not None:
        out["sidecar"] = sidecar
    return out


class MaskIn(BaseModel):
    mask_b64: str = Field(min_length=1)
    feather_radius: float = Field(default=2.0, ge=0.0, le=20.0)


@router.post("/image/mask")
async def build_mask_endpoint(payload: MaskIn):
    """Mask handling is PNG in / PNG out only. The server never invents
    a mask: the caller supplies brush strokes as a PNG (the Create
    panel's canvas brush produces it client-side); this endpoint only
    validates the PNG and optionally feathers its edges."""
    _require_image_gen()
    try:
        raw = base64.b64decode(payload.mask_b64, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="mask_b64 is not valid base64") from exc
    try:
        from ..image_ops import UnsupportedOp, feather_mask
        feathered = feather_mask(raw, radius=payload.feather_radius)
    except UnsupportedOp as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"mask_b64": base64.b64encode(feathered).decode(),
            "note": "Caller-supplied PNG mask, feathered at the edges only."}


# ------------------------------------------------------------ Batch 7 ops

def _decode_b64(value: str | None, field: str) -> bytes:
    if not value:
        raise HTTPException(status_code=422, detail=f"{field} (base64 image) is required")
    try:
        return base64.b64decode(value, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"{field} is not valid base64") from exc


def _save_op_images(results, method: str):
    attachments = []
    for i, img in enumerate(results):
        ext = "png" if "png" in img.mime_type else "jpg"
        attachments.append(save_media_file(img.data, f"op_{i + 1}.{ext}", img.mime_type))
    return {"images": [a.model_dump(mode="json") for a in attachments], "method": method}


def _run_op(fn, *args):
    _require_image_gen()
    try:
        results, method = fn(*args)
    except UnsupportedOp as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Image operation failed: {exc}") from exc
    return _save_op_images(results, method)


class ImageOpIn(BaseModel):
    image_b64: str | None = None
    mask_b64: str | None = None
    prompt: str | None = None
    strength: str = "subtle"
    factor: float = Field(default=2.0, ge=1.1, le=4.0)


@router.post("/image/vary")
async def vary_image_endpoint(payload: ImageOpIn):
    img = _decode_b64(payload.image_b64, "image_b64")
    return _run_op(vary, img, payload.strength)


@router.post("/image/upscale")
async def upscale_image_endpoint(payload: ImageOpIn):
    img = _decode_b64(payload.image_b64, "image_b64")
    return _run_op(upscale, img, payload.factor)


@router.post("/image/inpaint")
async def inpaint_image_endpoint(payload: ImageOpIn):
    img = _decode_b64(payload.image_b64, "image_b64")
    mask = base64.b64decode(payload.mask_b64) if payload.mask_b64 else None
    if not payload.prompt:
        raise HTTPException(status_code=422, detail="prompt is required for inpaint")
    return _run_op(inpaint, img, payload.prompt, mask)


@router.post("/image/outpaint")
async def outpaint_image_endpoint(payload: ImageOpIn):
    img = _decode_b64(payload.image_b64, "image_b64")
    mask = base64.b64decode(payload.mask_b64) if payload.mask_b64 else None
    if not payload.prompt:
        raise HTTPException(status_code=422, detail="prompt is required for outpaint")
    return _run_op(outpaint, img, payload.prompt, mask)


@router.post("/image/image-prompt")
async def image_prompt_endpoint(payload: ImageOpIn):
    img = _decode_b64(payload.image_b64, "image_b64")
    if not payload.prompt:
        raise HTTPException(status_code=422, detail="prompt is required for image-prompt")
    return _run_op(image_prompt, img, payload.prompt)


@router.post("/image/describe")
async def describe_image_endpoint(
    payload: ImageOpIn,
    db: AsyncSession = Depends(get_db),
):
    """Describe an image via the default chat model with an image_url
    message. v1 has no vision-capability registry: if no chat model is
    configured, or the provider rejects the image, this returns 503 with
    a plain message — never a fabricated description."""
    _require_image_gen()
    img = _decode_b64(payload.image_b64, "image_b64")
    try:
        model_id = await llm.default_model_id(db)
    except Exception:
        model_id = None
    if not model_id:
        raise HTTPException(
            status_code=503,
            detail="No chat model is configured for image description. Add a provider key first.",
        )
    b64 = base64.b64encode(img).decode()
    messages = [{"role": "user", "content": [
        {"type": "text", "text": payload.prompt or "Describe this image in detail."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
    ]}]
    try:
        parts: list[str] = []
        async for chunk in llm.stream_completion(model_id, messages, db):
            text = chunk if isinstance(chunk, str) else (getattr(chunk, "text", "") or "")
            if text:
                parts.append(text)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"Image description failed (the configured model may not support vision): {exc}",
        ) from exc
    description = "".join(parts).strip()
    if not description:
        raise HTTPException(
            status_code=503,
            detail="The configured model returned no description for this image.",
        )
    return {"description": description, "model_id": model_id}
