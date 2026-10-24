"""
api_routes/media_jobs_routes.py — Phase 4: media work as observable jobs.

POST /media-jobs creates a job and returns immediately (202); a
background task runs it and the job row (plus a RunStore mirror) is
the observable state. GET /media-jobs/{id} polls it.

Kinds: transcribe (audio media_id -> text), tts (text -> audio
media), dub (text + voice -> audio media, i.e. voicing a script),
image (prompt -> generated image attachments).

Voice cloning is deliberately NOT a kind here: the plan proposed it
as gated on consent + audit, and the user has not confirmed it.
"""
import json
import uuid
from datetime import datetime, UTC
from pathlib import Path

from fastapi import BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..contracts import RunState, run_store
from ..database import AsyncSessionLocal, get_db
from ..models import MediaJob
from .common import router

JOB_KINDS = {"transcribe", "tts", "dub", "image"}


class MediaJobIn(BaseModel):
    kind: str
    text: str | None = Field(default=None, max_length=8000)
    voice: str | None = None
    media_id: str | None = None
    prompt: str | None = Field(default=None, max_length=2000)
    style: str | None = None
    size: str | None = None
    n: int = Field(default=1, ge=1, le=4)


def _job_out(job: MediaJob) -> dict:
    return {
        "id": job.id, "kind": job.kind, "status": job.status,
        "input": json.loads(job.input_json or "{}"),
        "result": json.loads(job.result_json or "{}"),
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


async def _execute_media_job(job_id: str, user_id: str) -> None:
    """Background worker: run one media job to completion, then mirror
    the outcome onto the RunStore (Runs centre visibility)."""
    from ..feature_flags import is_enabled

    async with AsyncSessionLocal() as db:
        job = await db.get(MediaJob, job_id)
        if not job:
            return
        job.status = "running"
        job.updated_at = datetime.now(UTC)
        await db.commit()
        record = None
        try:
            record = run_store.create(kind=f"media-{job.kind}", owner_id=user_id,
                                      title=f"Media job: {job.kind}", run_id=job.id)
            record.transition(RunState.RUNNING)
        except Exception:
            record = None
        inp = json.loads(job.input_json or "{}")
        try:
            result: dict = {}
            if job.kind == "transcribe":
                if not is_enabled("voice"):
                    raise RuntimeError("Voice is not enabled")
                from ..api_routes.media_routes import _media_dir, load_media_attachment
                from ..voice import transcribe

                att = load_media_attachment(inp.get("media_id", ""))
                if not att:
                    raise RuntimeError("Audio media not found")
                path = _media_dir() / f"{att.id}.{Path(att.filename).suffix.lstrip('.') or 'bin'}"
                if not path.exists():
                    raise RuntimeError("Audio file not found on disk")
                result = {"text": transcribe(path.read_bytes(), att.filename)}
            elif job.kind in ("tts", "dub"):
                if not is_enabled("voice"):
                    raise RuntimeError("Voice is not enabled")
                from ..api_routes.media_routes import save_media_file
                from ..voice import synthesize

                audio, mime = synthesize(inp.get("text", ""), inp.get("voice"))
                att = save_media_file(audio, f"media-job-{job.id}.wav", mime)
                result = {"media_id": att.id, "url": att.url, "mime_type": att.mime_type}
            elif job.kind == "image":
                if not is_enabled("image_gen"):
                    raise RuntimeError("Image generation is not enabled")
                from ..image_gen import generate_images

                attachments = generate_images(
                    inp.get("prompt", ""), style=inp.get("style"),
                    size=inp.get("size"), n=int(inp.get("n", 1)),
                )
                result = {"images": [a.model_dump(mode="json") for a in attachments]}
            else:
                raise RuntimeError(f"Unknown media job kind: {job.kind}")
            job.result_json = json.dumps(result)
            job.status = "succeeded"
            job.error = None
            if record:
                try:
                    record.transition(RunState.SUCCEEDED)
                except Exception:
                    pass
        except Exception as exc:  # noqa: BLE001 — job failure is data, not a crash
            job.status = "failed"
            job.error = str(exc)[:500]
            if record:
                try:
                    record.transition(RunState.FAILED, error=job.error)
                except Exception:
                    pass
        job.updated_at = datetime.now(UTC)
        await db.commit()


@router.post("/media-jobs", status_code=202)
async def create_media_job(payload: MediaJobIn, background_tasks: BackgroundTasks,
                           db: AsyncSession = Depends(get_db),
                           user=Depends(get_current_user)):
    if payload.kind not in JOB_KINDS:
        raise HTTPException(status_code=422, detail=f"Unknown media job kind: {payload.kind}")
    if payload.kind == "transcribe" and not payload.media_id:
        raise HTTPException(status_code=422, detail="transcribe needs media_id")
    if payload.kind in ("tts", "dub") and not (payload.text or "").strip():
        raise HTTPException(status_code=422, detail=f"{payload.kind} needs text")
    if payload.kind == "image" and not (payload.prompt or "").strip():
        raise HTTPException(status_code=422, detail="image needs prompt")
    job = MediaJob(
        id=f"mj-{uuid.uuid4().hex[:12]}",
        user_id=user.id,
        kind=payload.kind,
        input_json=json.dumps(payload.model_dump()),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    # Framework background tasks (not a bare create_task): Starlette
    # runs these after the response, and they reliably execute under
    # TestClient as well as uvicorn.
    background_tasks.add_task(_execute_media_job, job.id, user.id)
    return _job_out(job)


@router.get("/media-jobs")
async def list_media_jobs(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    rows = (await db.execute(
        select(MediaJob).where(MediaJob.user_id == user.id).order_by(desc(MediaJob.created_at))
    )).scalars().all()
    return {"jobs": [_job_out(r) for r in rows]}


@router.get("/media-jobs/{job_id}")
async def get_media_job(job_id: str, db: AsyncSession = Depends(get_db),
                        user=Depends(get_current_user)):
    job = await db.get(MediaJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Media job not found")
    return _job_out(job)
