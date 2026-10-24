"""
api_routes/engineering_routes.py — Batch 5: engineering pipeline API.

Routes (mounted under /api via the shared router; importing this module
from api.py registers them AND registers the pipeline tables):

  POST /engineering                    create {title, goal}
  GET  /engineering                    list pipelines
  GET  /engineering/{id}               one pipeline + stages
  POST /engineering/{id}/advance       {stage, artifact, verdict?,
                                         prerequisite_artifact_id?}
                                         (422 on out-of-order / missing
                                         prerequisite / unfinished reviews)
  GET  /engineering/{id}/stages        stage list with artifacts
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..engineering_pipeline import (
    EngineeringPipeline,
    advance_pipeline,
    list_stages,
    new_pipeline_id,
    pipeline_out,
    produce_subagent_output,
)
from .common import router


class PipelineIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    goal: str = ""


class AdvanceIn(BaseModel):
    stage: str
    artifact: str = ""
    verdict: str | None = None
    prerequisite_artifact_id: str | None = None


async def _get_pipe(db: AsyncSession, pid: str) -> EngineeringPipeline:
    row = await db.execute(
        select(EngineeringPipeline).where(EngineeringPipeline.id == pid))
    pipe = row.scalars().first()
    if pipe is None:
        raise HTTPException(404, "Engineering pipeline not found")
    return pipe


@router.post("/engineering", status_code=201)
async def create_pipeline(payload: PipelineIn, db: AsyncSession = Depends(get_db)):
    pipe = EngineeringPipeline(id=new_pipeline_id(), title=payload.title,
                               goal=payload.goal or "")
    db.add(pipe)
    await db.commit()
    return {"id": pipe.id, "title": pipe.title, "goal": pipe.goal,
            "current_stage": None, "next_stage": "grill", "stages": []}


@router.get("/engineering")
async def list_pipelines(db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(EngineeringPipeline).order_by(desc(EngineeringPipeline.created_at)))
    pipes = rows.scalars().all()
    out = []
    for pipe in pipes:
        stages = await list_stages(db, pipe.id)
        out.append(pipeline_out(pipe, stages))
    return out


@router.get("/engineering/{pid}")
async def get_pipeline(pid: str, db: AsyncSession = Depends(get_db)):
    pipe = await _get_pipe(db, pid)
    return pipeline_out(pipe, await list_stages(db, pid))


@router.get("/engineering/{pid}/stages")
async def get_pipeline_stages(pid: str, db: AsyncSession = Depends(get_db)):
    pipe = await _get_pipe(db, pid)
    stages = await list_stages(db, pid)
    return [{"id": s.id, "stage": s.stage, "artifact": s.artifact,
             "verdict": s.verdict, "source": s.source} for s in stages]


@router.post("/engineering/{pid}/advance")
async def advance_stage(pid: str, payload: AdvanceIn,
                        db: AsyncSession = Depends(get_db)):
    pipe = await _get_pipe(db, pid)
    artifact, source = payload.artifact, "user"
    if payload.stage == "subagent":
        prior = await list_stages(db, pid)
        prior_text = "\n\n".join(f"## {s.stage}\n{s.artifact}" for s in prior)
        artifact, source = await produce_subagent_output(
            pipe.goal, prior_text, db)
        # A caller-supplied note is kept as a prefix, never as fake output.
        if payload.artifact.strip():
            artifact = f"Request note: {payload.artifact.strip()}\n\n{artifact}"
    try:
        row = await advance_pipeline(
            db, pipe, payload.stage, artifact,
            verdict=payload.verdict,
            prerequisite_artifact_id=payload.prerequisite_artifact_id,
            source=source)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"id": row.id, "stage": row.stage, "artifact": row.artifact,
            "verdict": row.verdict, "source": row.source,
            "current_stage": pipe.current_stage}
