"""
api_routes/diagrams_routes.py — editorial diagrams API (Batch 7).

GET  /diagrams/catalogue        template entries (id, name, use, template)
POST /diagrams/lint             statically checkable style-guide issues
GET  /diagrams/brands           saved brand profiles
POST /diagrams/brands           create a brand profile
POST /diagrams/brands/apply     substitute a brand into a template
POST /diagrams/import           mermaid|drawio|excalidraw -> mermaid + warnings
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..diagrams import (
    CATALOGUE,
    DiagramBrand,
    apply_brand,
    import_diagram,
    lint_mermaid,
)
from .common import router


@router.get("/diagrams/catalogue")
async def diagrams_catalogue(user=Depends(get_current_user)):
    return {"diagrams": CATALOGUE}


class LintIn(BaseModel):
    mermaid: str


@router.post("/diagrams/lint")
async def diagrams_lint(payload: LintIn, user=Depends(get_current_user)):
    issues = lint_mermaid(payload.mermaid)
    return {
        "issues": issues,
        "note": (
            "Lint covers only what is statically checkable (accent count, "
            "node count, label length, title). Overlap/clipping checks are "
            "visual — check the rendered diagram, the 4px grid and hairline "
            "guidance are guides, not automated checks."
        ),
    }


class BrandIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    accent: str = Field(default="#3A7BD5", pattern=r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")
    font: str | None = None
    logo_text: str | None = None


@router.get("/diagrams/brands")
async def list_brands(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    res = await db.execute(select(DiagramBrand).order_by(DiagramBrand.created_at.desc()))
    rows = res.scalars().all()
    return {"brands": [
        {"id": r.id, "name": r.name, "accent": r.accent, "font": r.font, "logo_text": r.logo_text}
        for r in rows
    ]}


@router.post("/diagrams/brands")
async def create_brand(payload: BrandIn, db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    row = DiagramBrand(
        id=uuid.uuid4().hex[:12], name=payload.name, accent=payload.accent,
        font=payload.font or "Inter, system-ui, sans-serif",
        logo_text=payload.logo_text or "",
    )
    db.add(row)
    await db.commit()
    return {"id": row.id, "name": row.name, "accent": row.accent, "font": row.font, "logo_text": row.logo_text}


class BrandApplyIn(BaseModel):
    template: str
    brand_id: str | None = None
    accent: str | None = None
    font: str | None = None


@router.post("/diagrams/brands/apply")
async def apply_brand_endpoint(
    payload: BrandApplyIn, db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    accent, font = payload.accent, payload.font
    if payload.brand_id:
        row = await db.get(DiagramBrand, payload.brand_id)
        if not row:
            raise HTTPException(status_code=404, detail="Brand not found")
        accent, font = row.accent, row.font
    if not accent:
        raise HTTPException(status_code=422, detail="Provide brand_id or accent")
    return {"mermaid": apply_brand(payload.template, accent, font)}


class ImportIn(BaseModel):
    format: str
    content: str


@router.post("/diagrams/import")
async def import_diagram_endpoint(payload: ImportIn, user=Depends(get_current_user)):
    try:
        return import_diagram(payload.format, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
