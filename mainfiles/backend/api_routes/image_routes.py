"""
api_routes/image_routes.py — image generation API.

Gated end-to-end by FEATURE_IMAGE_GEN (the frontend hides image UI when off).
Generated images persist through the media pipeline and return as
MediaAttachments, so they render in chat like any image.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..image_gen import ImageGenError, generate_images, image_status
from .common import router


def _require_image_gen() -> None:
    if not settings.FEATURE_IMAGE_GEN:
        raise HTTPException(status_code=404, detail="Image generation is not enabled")


class ImageGenIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    style: str | None = None
    size: str | None = Field(default=None, pattern=r"^\d+x\d+$")
    n: int = Field(default=1, ge=1, le=4)


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
    try:
        attachments = generate_images(
            payload.prompt, style=payload.style, size=payload.size, n=payload.n
        )
    except ImageGenError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    from ..analytics import events as _ae, optional_user_id, record_event as _record

    await _record(db, await optional_user_id(request, db), _ae.IMAGE_GENERATED,
                  {"n": payload.n})
    return {"images": [a.model_dump(mode="json") for a in attachments]}
