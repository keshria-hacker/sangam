"""
api_routes/artifacts_routes.py — typed artifacts with version history (Phase 4).
"""
import json
import uuid
from datetime import datetime, UTC

from fastapi import Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..config import settings
from ..contracts import (
    PaginationParams,
    paginate,
    sign_artifact_token,
    signing_secret,
    verify_artifact_token,
)
from ..database import get_db
from ..models import Artifact, ArtifactVersion
from .common import public_router, router

# Phase 1: artifact type -> download file extension / media type.
_ARTIFACT_DOWNLOAD = {
    "doc": ("md", "text/markdown"),
    "code": ("txt", "text/plain"),
    "diagram": ("svg", "image/svg+xml"),
    "html": ("html", "text/html"),
    "design": ("html", "text/html"),
}


class ArtifactIn(BaseModel):
    title: str
    type: str = "doc"  # doc | diagram | code | html
    content: str = ""
    language: str | None = None


class ArtifactUpdate(BaseModel):
    title: str | None = None
    content: str | None = None


@router.post("/artifacts", status_code=201)
async def create_artifact(payload: ArtifactIn, db: AsyncSession = Depends(get_db),
                          user=Depends(get_current_user)):
    art = Artifact(
        id=f"art-{uuid.uuid4().hex[:12]}",
        user_id=user.id,
        title=payload.title[:200],
        type=payload.type,
        language=payload.language,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(art)
    await db.flush()
    ver = ArtifactVersion(
        id=f"ver-{uuid.uuid4().hex[:12]}",
        artifact_id=art.id,
        version=1,
        content=payload.content,
        created_at=datetime.now(UTC),
    )
    db.add(ver)
    await db.commit()
    return {"id": art.id, "version": 1}


@router.get("/artifacts")
async def list_artifacts(db: AsyncSession = Depends(get_db),
                         user=Depends(get_current_user),
                         type: str | None = None,
                         limit: int = 50, offset: int = 0):
    """Phase 1: pagination block alongside the unchanged artifacts list."""
    from sqlalchemy import func

    params = PaginationParams(limit=limit, offset=offset)
    base = select(Artifact).where(Artifact.user_id == user.id)
    if type:
        base = base.where(Artifact.type == type)
    total = (await db.execute(
        select(func.count()).select_from(base.subquery()))).scalar() or 0
    stmt = base.order_by(desc(Artifact.updated_at)).limit(params.limit).offset(params.offset)
    arts = (await db.execute(stmt)).scalars().all()
    items = [
        {"id": a.id, "title": a.title, "type": a.type, "language": a.language,
         "updated_at": a.updated_at.isoformat() if a.updated_at else None}
        for a in arts
    ]
    return {"artifacts": items, "pagination": paginate(items, total, params)["pagination"]}


@router.get("/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str, db: AsyncSession = Depends(get_db),
                       user=Depends(get_current_user),
                       version: int | None = None):
    art = await db.get(Artifact, artifact_id)
    if not art or art.user_id != user.id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if version:
        ver = (await db.execute(
            select(ArtifactVersion).where(
                ArtifactVersion.artifact_id == artifact_id,
                ArtifactVersion.version == version)
        )).scalar_one_or_none()
        if not ver:
            raise HTTPException(status_code=404, detail="Version not found")
        content = ver.content
    else:
        ver = (await db.execute(
            select(ArtifactVersion).where(
                ArtifactVersion.artifact_id == artifact_id)
            .order_by(desc(ArtifactVersion.version)).limit(1)
        )).scalar_one_or_none()
        content = ver.content if ver else ""
        version = ver.version if ver else 1
    return {"id": art.id, "title": art.title, "type": art.type,
            "language": art.language, "content": content, "version": version}


@router.put("/artifacts/{artifact_id}")
async def update_artifact(artifact_id: str, payload: ArtifactUpdate,
                          db: AsyncSession = Depends(get_db),
                          user=Depends(get_current_user)):
    art = await db.get(Artifact, artifact_id)
    if not art or art.user_id != user.id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    # Get current max version
    max_ver = (await db.execute(
        select(ArtifactVersion.version).where(
            ArtifactVersion.artifact_id == artifact_id)
        .order_by(desc(ArtifactVersion.version)).limit(1)
    )).scalar_one_or_none() or 0
    new_version = max_ver + 1
    if payload.title:
        art.title = payload.title[:200]
    if payload.content is not None:
        ver = ArtifactVersion(
            id=f"ver-{uuid.uuid4().hex[:12]}",
            artifact_id=art.id,
            version=new_version,
            content=payload.content,
            created_at=datetime.now(UTC),
        )
        db.add(ver)
    art.updated_at = datetime.now(UTC)
    await db.commit()
    return {"id": art.id, "version": new_version}


@router.get("/artifacts/{artifact_id}/versions")
async def list_versions(artifact_id: str, db: AsyncSession = Depends(get_db),
                        user=Depends(get_current_user)):
    art = await db.get(Artifact, artifact_id)
    if not art or art.user_id != user.id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    vers = (await db.execute(
        select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact_id)
        .order_by(desc(ArtifactVersion.version))
    )).scalars().all()
    return {"versions": [
        {"version": v.version,
         "created_at": v.created_at.isoformat() if v.created_at else None,
         "size": len(v.content or "")}
        for v in vers
    ]}


@router.delete("/artifacts/{artifact_id}")
async def delete_artifact(artifact_id: str, db: AsyncSession = Depends(get_db),
                          user=Depends(get_current_user)):
    art = await db.get(Artifact, artifact_id)
    if not art or art.user_id != user.id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    await db.delete(art)
    await db.commit()
    return {"ok": True}


# ------------------------------------------------- Phase 1 lifecycle

async def _latest_content(db: AsyncSession, artifact_id: str) -> tuple[Artifact, str, int]:
    """Return (artifact, latest content, latest version), owner-checked
    by the caller for signed downloads (owner comes from the token)."""
    art = await db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")
    ver = (await db.execute(
        select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact_id)
        .order_by(desc(ArtifactVersion.version)).limit(1)
    )).scalar_one_or_none()
    return art, (ver.content if ver else ""), (ver.version if ver else 1)


@router.post("/artifacts/{artifact_id}/signed-url")
async def create_signed_url(artifact_id: str, db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    """Phase 1: signed, short-lived download URL for an artifact.

    The token binds artifact + owner + expiry and is HMAC-signed;
    the download endpoint itself needs no session, so the URL can be
    opened directly (e.g. from the Runs centre's Download button).
    """
    art = await db.get(Artifact, artifact_id)
    if not art or art.user_id != user.id:
        raise HTTPException(status_code=404, detail="Artifact not found")
    token = sign_artifact_token(artifact_id, user.id,
                                signing_secret(settings.MASTER_KEY),
                                expires_in_seconds=900)
    return {"url": f"{settings.API_PREFIX}/artifacts/download?token={token}",
            "expires_in": 900}


@public_router.get("/artifacts/download")
async def download_artifact(token: str, db: AsyncSession = Depends(get_db)):
    """Download an artifact's latest version via a signed token.

    No session auth: the token IS the auth. Expired, tampered, or
    owner-mismatched tokens are rejected with 403, never 404 detail
    that would leak which artifacts exist.
    """
    payload = verify_artifact_token(token, signing_secret(settings.MASTER_KEY))
    if payload is None:
        raise HTTPException(status_code=403, detail="Invalid or expired download link")
    art, content, _version = await _latest_content(db, payload["artifact_id"])
    if art.user_id != payload["owner_id"]:
        raise HTTPException(status_code=403, detail="Invalid or expired download link")
    ext, media_type = _ARTIFACT_DOWNLOAD.get(art.type, ("txt", "text/plain"))
    safe_title = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in art.title[:80]) or "artifact"
    return PlainTextResponse(
        content, media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_title}.{ext}"'},
    )


class RetentionPruneIn(BaseModel):
    days: int = 90  # delete artifacts not updated in this many days


@router.post("/artifacts/retention/prune")
async def prune_artifacts(payload: RetentionPruneIn,
                          db: AsyncSession = Depends(get_db),
                          user=Depends(get_current_user)):
    """Phase 1 retention: explicitly delete the caller's artifacts not
    updated in ``days`` days. Explicit only — nothing auto-deletes.
    Returns how many were removed."""
    from datetime import timedelta

    if payload.days < 1:
        raise HTTPException(status_code=422, detail="days must be >= 1")
    cutoff = datetime.now(UTC) - timedelta(days=payload.days)
    stmt = select(Artifact).where(
        Artifact.user_id == user.id, Artifact.updated_at < cutoff)
    arts = (await db.execute(stmt)).scalars().all()
    for art in arts:
        await db.delete(art)
    await db.commit()
    return {"deleted": len(arts), "days": payload.days}
