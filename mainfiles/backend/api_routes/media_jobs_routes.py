"""
api_routes/media_jobs_routes.py — Phase 4: media work as observable jobs.

POST /media-jobs creates a job and returns immediately (202); a
background task runs it and the job row (plus a RunStore mirror) is
the observable state. GET /media-jobs/{id} polls it.

Kinds: transcribe (audio media_id -> text), tts (text -> audio
media), dub (text + voice -> audio media, i.e. VOICING A SCRIPT —
true dubbing lives at POST /voice/dub), image (prompt -> generated
image attachments), audiobook (plan + rendered chapters).

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

JOB_KINDS = {"transcribe", "tts", "dub", "image", "audiobook"}
# NOTE on naming: the legacy ``dub`` kind voices a script (text -> audio).
# True dubbing (source audio -> timed segments -> fitted subtitles) is
# the separate POST /voice/dub route; it is NOT this kind, and docs/UI
# must call this kind "voice a script", never "dubbing".


class MediaJobIn(BaseModel):
    kind: str
    text: str | None = Field(default=None, max_length=8000)
    voice: str | None = None
    media_id: str | None = None
    prompt: str | None = Field(default=None, max_length=2000)
    style: str | None = None
    size: str | None = None
    n: int = Field(default=1, ge=1, le=4)
    # Batch 11 staged pipeline (OpenMontage pattern, non-video):
    # {"stages": [{name, action, checkpoint_required, max_revisions,
    #              budget_cap_usd, produces, input: {...}}]}.
    pipeline: dict | None = None
    budget_cap_usd: float | None = None
    chapters: list[dict] | None = None


def _run_pipeline_stage(stage: dict, inp: dict) -> dict:
    """Execute one pipeline stage through existing engines / pure
    helpers. Unknown actions were rejected at creation (422); an
    engine failure here fails the job with the engine's message."""
    from ..media_pipeline.audio import (
        audiobook_plan, render_ass_word_level, render_srt, render_vtt,
        validate_segments,
    )
    from ..media_pipeline.design import critique_prototype
    from ..media_pipeline.overlay import render_overlay_svg
    from ..media_pipeline.storyboard import still_prompts

    action = stage.get("action")
    sinput = dict(stage.get("input") or {})
    if action == "image":
        from ..image_gen import generate_images
        atts = generate_images(sinput.get("prompt", inp.get("prompt", "")),
                               style=sinput.get("style", inp.get("style")),
                               size=sinput.get("size", inp.get("size")),
                               n=int(sinput.get("n", inp.get("n", 1))))
        return {"images": [a.model_dump(mode="json") for a in atts]}
    if action in ("tts", "voice_script"):
        from ..api_routes.media_routes import save_media_file
        from ..voice import synthesize
        audio, mime = synthesize(sinput.get("text", inp.get("text", "")),
                                 sinput.get("voice", inp.get("voice")))
        att = save_media_file(audio, f"pipeline-{stage.get('name', 'audio')}.wav", mime)
        return {"media_id": att.id, "url": att.url, "mime_type": att.mime_type}
    if action == "transcribe":
        from ..api_routes.media_routes import _media_dir, load_media_attachment
        from ..voice import transcribe
        att = load_media_attachment(sinput.get("media_id", inp.get("media_id", "")))
        if not att:
            raise RuntimeError("Audio media not found")
        path = _media_dir() / f"{att.id}.{Path(att.filename).suffix.lstrip('.') or 'bin'}"
        if not path.exists():
            raise RuntimeError("Audio file not found on disk")
        return {"text": transcribe(path.read_bytes(), att.filename)}
    if action == "diagram_validate":
        from ..diagram_ir import validate_diagram
        doc = sinput.get("diagram") or inp.get("diagram")
        if not isinstance(doc, dict):
            raise RuntimeError("diagram_validate stage needs input.diagram")
        return {"diagnostics": validate_diagram(doc),
                "valid": validate_diagram(doc) == []}
    if action == "design_critique":
        html = sinput.get("html", inp.get("html", ""))
        return {"findings": critique_prototype(html)}
    if action == "subtitle":
        segments = sinput.get("segments") or inp.get("segments")
        errs = validate_segments(segments)
        if errs:
            raise RuntimeError(f"invalid subtitle segments: {errs[0]['message']}")
        return {"srt": render_srt(segments), "vtt": render_vtt(segments),
                "ass": render_ass_word_level(segments)}
    if action == "overlay":
        return {"svg": render_overlay_svg(sinput.get("annotations") or [])}
    if action == "storyboard":
        plan = sinput.get("plan") or inp.get("plan")
        return {"stills": still_prompts(plan)}
    if action == "audiobook_plan":
        return audiobook_plan(sinput.get("text", inp.get("text", "")),
                              seed=int(sinput.get("seed", 0)),
                              chapters=sinput.get("chapters") or inp.get("chapters"))
    raise RuntimeError(f"Unknown pipeline stage action: {action}")


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
    the outcome onto the RunStore (Runs centre visibility).

    Pipeline jobs run stages in order; a checkpoint_required stage
    pauses the job in ``awaiting_approval`` (state lives in
    result_json.pipeline_state) and approve resumes from the next
    stage. Pipeline cost is recorded only from engine reports (none
    of Sangam's engines report one today, so cost is honestly
    ``known: false`` and never trips a budget cap on invented data).
    """
    from ..feature_flags import is_enabled

    async with AsyncSessionLocal() as db:
        job = await db.get(MediaJob, job_id)
        if not job:
            return
        inp0 = json.loads(job.input_json or "{}")
        prev = json.loads(job.result_json or "{}")
        state = prev.get("pipeline_state") or {}
        start_at = int(state.get("next_stage", 0)) if inp0.get("pipeline") else 0
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
            result: dict = dict(prev)
            if inp.get("pipeline"):
                from ..media_pipeline.stages import CostRecord
                stages = inp["pipeline"]["stages"]
                stage_results = dict(result.get("stage_results") or {})
                stage_states = list(state.get("stages") or
                                    [{"name": s.get("name"), "status": "pending"}
                                     for s in stages])
                cost = CostRecord()
                paused = False
                for idx in range(start_at, len(stages)):
                    stage = stages[idx]
                    stage_states[idx]["status"] = "running"
                    stage_results[stage.get("name")] = _run_pipeline_stage(stage, inp)
                    stage_states[idx]["status"] = "done"
                    if stage.get("checkpoint_required"):
                        job.result_json = json.dumps({
                            **result, "stage_results": stage_results,
                            "pipeline_state": {
                                "next_stage": idx + 1, "stages": stage_states,
                                "revisions": state.get("revisions", {}),
                                "cost": cost.as_dict(),
                                "paused_at_stage": stage.get("name")}})
                        job.status = "awaiting_approval"
                        job.updated_at = datetime.now(UTC)
                        await db.commit()
                        return
                result = {**result, "stage_results": stage_results,
                          "pipeline_state": {"next_stage": len(stages),
                                             "stages": stage_states,
                                             "revisions": state.get("revisions", {}),
                                             "cost": cost.as_dict()}}
            elif job.kind == "audiobook":
                if not is_enabled("voice"):
                    raise RuntimeError("Voice is not enabled")
                from ..api_routes.media_routes import save_media_file
                from ..media_pipeline.audio import audiobook_plan
                from ..voice import synthesize_chunked
                plan = audiobook_plan(inp.get("text", ""),
                                      chapters=inp.get("chapters"))
                rendered = []
                for chapter in plan["chapters"]:
                    for span in chapter["spans"]:
                        out = synthesize_chunked(span["text"], inp.get("voice"))
                        att = save_media_file(out["audio"], "audiobook-span.wav",
                                              out["mime"])
                        rendered.append({"chapter": chapter["title"],
                                         "media_id": att.id, "url": att.url})
                result = {"plan": plan, "rendered": rendered}
            elif job.kind == "transcribe":
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
    if payload.kind == "audiobook" and not (payload.text or "").strip() \
            and not payload.chapters:
        raise HTTPException(status_code=422, detail="audiobook needs text or chapters")
    if payload.kind == "image" and not (payload.prompt or "").strip():
        raise HTTPException(status_code=422, detail="image needs prompt")
    if payload.pipeline is not None:
        from ..media_pipeline.stages import validate_pipeline
        errs = validate_pipeline(payload.pipeline)
        if errs:
            raise HTTPException(status_code=422, detail=errs[0]["message"])
    if payload.kind in ("video", "clone", "voice_clone", "faceswap"):
        raise HTTPException(status_code=422, detail=f"Excluded job kind: {payload.kind}")
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


@router.post("/media-jobs/{job_id}/approve")
async def approve_media_job(job_id: str, background_tasks: BackgroundTasks,
                            db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    """Resume a checkpoint-paused pipeline job (OpenMontage pattern).

    Each approve counts as a revision of the paused stage; exceeding
    that stage's max_revisions fails the job instead of resuming.
    """
    job = await db.get(MediaJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Media job not found")
    if job.status != "awaiting_approval":
        raise HTTPException(
            status_code=422, detail=f"Job is {job.status}, not awaiting_approval")
    result = json.loads(job.result_json or "{}")
    state = result.get("pipeline_state") or {}
    paused = state.get("paused_at_stage")
    inp = json.loads(job.input_json or "{}")
    stages = (inp.get("pipeline") or {}).get("stages") or []
    stage = next((s for s in stages if s.get("name") == paused), None)
    revisions = dict(state.get("revisions") or {})
    count = int(revisions.get(paused, 0)) + 1
    if stage is not None and count > int(stage.get("max_revisions", 3)):
        job.status = "failed"
        job.error = (f"Stage {paused!r} exceeded max_revisions "
                     f"({stage.get('max_revisions', 3)})")
        job.updated_at = datetime.now(UTC)
        await db.commit()
        return _job_out(job)
    revisions[paused] = count
    state["revisions"] = revisions
    result["pipeline_state"] = state
    job.result_json = json.dumps(result)
    job.status = "running"
    job.updated_at = datetime.now(UTC)
    await db.commit()
    background_tasks.add_task(_execute_media_job, job.id, user.id)
    return _job_out(job)
