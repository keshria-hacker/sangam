"""
api_routes/artifacts_routes.py — typed artifacts with version history (Phase 4).
"""
import json
import uuid
from datetime import datetime, UTC

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import Artifact, ArtifactVersion
from .common import router


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
                         limit: int = 50):
    stmt = select(Artifact).where(Artifact.user_id == user.id)
    if type:
        stmt = stmt.where(Artifact.type == type)
    stmt = stmt.order_by(desc(Artifact.updated_at)).limit(min(limit, 200))
    arts = (await db.execute(stmt)).scalars().all()
    return {"artifacts": [
        {"id": a.id, "title": a.title, "type": a.type, "language": a.language,
         "updated_at": a.updated_at.isoformat() if a.updated_at else None}
        for a in arts
    ]}


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
