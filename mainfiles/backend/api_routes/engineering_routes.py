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
from .. import pipeline_agents
from ..spec_chain import (
    ChainReview,
    PipelineTaskRun,
    ReviewPackage,
    SpecChainArtifact,
    advance_chain,
    chain_out,
    list_chain,
    list_reviews,
    list_task_runs,
    new_chain_id,
    parse_tasks,
    sha,
    task_briefs,
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
        # Real per-task runs when this pipeline has a spec-chain tasks
        # artifact; otherwise the v1 call below (team/handoff). The
        # 3-arg call is preserved when no chain tasks exist so existing
        # callers/mocks of produce_subagent_output keep working.
        chain_tasks: list[dict] | None = None
        chain = await list_chain(db, pid)
        chain_by_stage = {c.stage: c for c in chain}
        if "tasks" in chain_by_stage:
            try:
                parsed = parse_tasks(chain_by_stage["tasks"].artifact)
                if parsed:
                    if "spec" in chain_by_stage:
                        briefs = task_briefs(
                            chain_by_stage["spec"].artifact,
                            chain_by_stage["tasks"].artifact)
                    else:
                        briefs = [{"task_id": t["id"], "files": t["files"],
                                   "brief": f"Implement task {t['id']}: "
                                            f"{t['title']}"} for t in parsed]
                    chain_tasks = briefs
            except ValueError:
                chain_tasks = None
        if chain_tasks:
            artifact, source = await produce_subagent_output(
                pipe.goal, prior_text, db, tasks=chain_tasks)
        else:
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


# ------------------------------------------------------------------ spec chain
# Served on the already-mounted engineering router (no api.py change).
# Order is enforced in spec_chain.advance_chain; every 422 below is a
# structural gate, not an LLM judgement.


class ChainAdvanceIn(BaseModel):
    stage: str
    artifact: str = ""
    clarifications: list[dict] | None = None


class TaskRunIn(BaseModel):
    test_command: str = ""
    model: str | None = None
    fresh_context: bool = False


class ReviewIn(BaseModel):
    verdict: str
    artifact: str = ""
    review_package_id: str


class FixIn(BaseModel):
    task_id: str | None = None
    test_command: str = ""
    model: str | None = None


class ChainFinishIn(BaseModel):
    artifact: str = ""


async def _chain_view(db: AsyncSession, pid: str) -> dict:
    chain = await list_chain(db, pid)
    runs = await list_task_runs(db, pid)
    rows = await db.execute(
        select(ReviewPackage).where(ReviewPackage.pipeline_id == pid)
        .order_by(ReviewPackage.created_at))
    packages = list(rows.scalars().all())
    reviews = await list_reviews(db, pid)
    return chain_out(chain, runs, packages, reviews)


def _latest_runs(runs: list[PipelineTaskRun]) -> dict[str, PipelineTaskRun]:
    latest: dict[str, PipelineTaskRun] = {}
    for r in runs:
        latest[r.task_id] = r
    return latest


def _sequential_halt(tasks: list[dict], latest: dict[str, PipelineTaskRun],
                     task_id: str) -> str | None:
    """Return a halt reason, or None if the task may run.

    A non-[P] task needs every earlier task passed. A [P] task may run
    any time, unless an earlier non-[P] task failed (the sequential
    chain it depends on is broken). A failing implement stage halts
    the pipeline instead of proceeding.
    """
    idx = next((i for i, t in enumerate(tasks) if t["id"] == task_id), None)
    if idx is None:
        return f"unknown task {task_id}"
    task = tasks[idx]
    for earlier in tasks[:idx]:
        row = latest.get(earlier["id"])
        if row is not None and not row.test_passed and not earlier["parallel"]:
            return (f"halted: earlier sequential task {earlier['id']} "
                    "failed its tests")
        if not task["parallel"] and (row is None or not row.test_passed):
            return (f"halted: earlier task {earlier['id']} has not passed "
                    "its tests yet")
    return None


@router.post("/engineering/{pid}/chain/advance")
async def chain_advance(pid: str, payload: ChainAdvanceIn,
                        db: AsyncSession = Depends(get_db)):
    await _get_pipe(db, pid)
    try:
        row = await advance_chain(
            db, pid, payload.stage, artifact=payload.artifact,
            clarifications=payload.clarifications)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"id": row.id, "stage": row.stage, "artifact": row.artifact}


@router.get("/engineering/{pid}/chain")
async def get_chain(pid: str, db: AsyncSession = Depends(get_db)):
    await _get_pipe(db, pid)
    return await _chain_view(db, pid)


@router.post("/engineering/{pid}/chain/tasks/{task_id}/run")
async def chain_run_task(pid: str, task_id: str, payload: TaskRunIn,
                         db: AsyncSession = Depends(get_db)):
    pipe = await _get_pipe(db, pid)
    chain = await list_chain(db, pid)
    by_stage = {c.stage: c for c in chain}
    if "tasks" not in by_stage:
        raise HTTPException(422, "no stored tasks stage: advance the chain first")
    try:
        tasks = parse_tasks(by_stage["tasks"].artifact)
        briefs = (task_briefs(by_stage["spec"].artifact, by_stage["tasks"].artifact)
                  if "spec" in by_stage else [])
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task is None:
        raise HTTPException(404, f"Unknown task {task_id}")
    runs = await list_task_runs(db, pid)
    halt = _sequential_halt(tasks, _latest_runs(runs), task_id)
    if halt:
        raise HTTPException(422, halt)
    brief = next((b["brief"] for b in briefs if b["task_id"] == task_id),
                 f"Implement task {task_id}: {task['title']}")
    model_id = payload.model
    if not model_id:
        from .. import llm
        try:
            model_id = await llm.default_model_id(db)
        except Exception:  # noqa: BLE001
            model_id = None
    if not model_id:
        raise HTTPException(422, "no model configured: cannot run a real agent")
    result = await pipeline_agents.run_task_agent(
        task_id, brief, model_id, db, files=task["files"],
        fresh_context=payload.fresh_context)
    if result.error:
        passed, test_out = False, f"agent error: {result.error}"
    else:
        passed, test_out = pipeline_agents.run_tests(payload.test_command)
    row = PipelineTaskRun(
        id=new_chain_id("taskrun"), pipeline_id=pipe.id, task_id=task_id,
        brief=brief, agent_source="agent", diff=result.diff,
        test_command=payload.test_command, test_passed=1 if passed else 0,
        test_output=test_out, fix_round=0,
        fresh_context=1 if payload.fresh_context else 0,
        error=result.error)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "task_id": task_id, "test_passed": passed,
            "diff": result.diff, "test_output": test_out,
            "error": result.error}


@router.post("/engineering/{pid}/chain/review-package")
async def chain_review_package(pid: str, db: AsyncSession = Depends(get_db)):
    pipe = await _get_pipe(db, pid)
    chain = await list_chain(db, pid)
    by_stage = {c.stage: c for c in chain}
    if "tasks" not in by_stage:
        raise HTTPException(422, "no stored tasks stage")
    runs = _latest_runs(await list_task_runs(db, pid))
    diffs = []
    for task_id in sorted(runs):
        if runs[task_id].diff:
            diffs.append(f"## Task {task_id}\n{runs[task_id].diff}")
    if not diffs:
        raise HTTPException(
            422, "review package requires a non-empty diff: no task run "
                 "has produced file changes yet")
    diff = "\n\n".join(diffs)
    pkg = ReviewPackage(
        id=new_chain_id("revpkg"), pipeline_id=pipe.id,
        base_ref=sha(by_stage["tasks"].artifact), head_ref=sha(diff),
        diff=diff, fix_rounds=0)
    db.add(pkg)
    await db.commit()
    await db.refresh(pkg)
    return {"id": pkg.id, "base_ref": pkg.base_ref,
            "head_ref": pkg.head_ref, "diff": pkg.diff}


@router.post("/engineering/{pid}/chain/review/{axis}")
async def chain_review(pid: str, axis: str, payload: ReviewIn,
                       db: AsyncSession = Depends(get_db)):
    await _get_pipe(db, pid)
    if axis not in ("spec", "quality"):
        raise HTTPException(422, "review axis must be 'spec' or 'quality'")
    if payload.verdict not in ("pass", "fail"):
        raise HTTPException(422, "review verdict must be 'pass' or 'fail'")
    rows = await db.execute(
        select(ReviewPackage).where(ReviewPackage.id == payload.review_package_id))
    pkg = rows.scalars().first()
    if pkg is None or pkg.pipeline_id != pid:
        raise HTTPException(422, "review_package_id must be a package of this pipeline")
    # The teeth: the verdict must reference the review package. Pasted
    # text alone (no package id) cannot satisfy a review, or finish.
    if payload.review_package_id not in (payload.artifact or ""):
        raise HTTPException(
            422, "review artifact must reference its review_package_id")
    row = ChainReview(
        id=new_chain_id("review"), pipeline_id=pid, axis=axis,
        verdict=payload.verdict, review_package_id=payload.review_package_id,
        artifact=payload.artifact)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "axis": axis, "verdict": payload.verdict,
            "review_package_id": payload.review_package_id}


@router.post("/engineering/{pid}/chain/review/{axis}/fix")
async def chain_fix(pid: str, axis: str, payload: FixIn,
                    db: AsyncSession = Depends(get_db)):
    pipe = await _get_pipe(db, pid)
    if axis not in ("spec", "quality"):
        raise HTTPException(422, "review axis must be 'spec' or 'quality'")
    reviews = await list_reviews(db, pid)
    axis_reviews = [r for r in reviews if r.axis == axis]
    if not axis_reviews or axis_reviews[-1].verdict != "fail":
        raise HTTPException(
            422, f"fix requires a latest '{axis}' verdict of 'fail'")
    rows = await db.execute(
        select(ReviewPackage).where(ReviewPackage.pipeline_id == pid)
        .order_by(ReviewPackage.created_at.desc()))
    pkg = rows.scalars().first()
    if pkg is None:
        raise HTTPException(422, "fix requires a review package")
    new_round = pkg.fix_rounds + 1
    if new_round > 5:
        raise HTTPException(422, "fix loop cap reached: 5 rounds maximum")
    chain = await list_chain(db, pid)
    by_stage = {c.stage: c for c in chain}
    if "tasks" not in by_stage:
        raise HTTPException(422, "no stored tasks stage")
    tasks = parse_tasks(by_stage["tasks"].artifact)
    runs = _latest_runs(await list_task_runs(db, pid))
    task_id = payload.task_id
    if task_id is None:
        failed = [t["id"] for t in tasks
                  if t["id"] in runs and not runs[t["id"]].test_passed]
        if not failed:
            raise HTTPException(422, "no failed task to fix; pass task_id")
        task_id = failed[0]
    task = next((t for t in tasks if t["id"] == task_id), None)
    if task is None:
        raise HTTPException(404, f"Unknown task {task_id}")
    briefs = (task_briefs(by_stage["spec"].artifact, by_stage["tasks"].artifact)
              if "spec" in by_stage else [])
    brief = next((b["brief"] for b in briefs if b["task_id"] == task_id),
                 f"Implement task {task_id}: {task['title']}")
    brief += (f"\n\nReview findings ({axis}, package {pkg.id}):\n"
              f"{axis_reviews[-1].artifact}")
    model_id = payload.model
    if not model_id:
        from .. import llm
        try:
            model_id = await llm.default_model_id(db)
        except Exception:  # noqa: BLE001
            model_id = None
    if not model_id:
        raise HTTPException(422, "no model configured: cannot run a real agent")
    fresh = new_round >= 4  # rounds 4-5 run with fresh context
    result = await pipeline_agents.run_task_agent(
        task_id, brief, model_id, db, files=task["files"], fresh_context=fresh)
    if result.error:
        passed, test_out = False, f"agent error: {result.error}"
    else:
        passed, test_out = pipeline_agents.run_tests(payload.test_command)
    row = PipelineTaskRun(
        id=new_chain_id("taskrun"), pipeline_id=pipe.id, task_id=task_id,
        brief=brief, agent_source="agent", diff=result.diff,
        test_command=payload.test_command, test_passed=1 if passed else 0,
        test_output=test_out, fix_round=new_round,
        fresh_context=1 if fresh else 0, error=result.error)
    db.add(row)
    pkg.fix_rounds = new_round
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "task_id": task_id, "fix_round": new_round,
            "fresh_context": fresh, "test_passed": passed,
            "diff": result.diff, "error": result.error}


@router.post("/engineering/{pid}/chain/finish")
async def chain_finish(pid: str, payload: ChainFinishIn,
                       db: AsyncSession = Depends(get_db)):
    pipe = await _get_pipe(db, pid)
    chain = await list_chain(db, pid)
    stages = [c.stage for c in chain]
    if "converge" not in stages:
        raise HTTPException(422, "chain finish requires the converge stage")
    if "finish" in stages:
        raise HTTPException(422, "Spec chain is already finished")
    rows = await db.execute(
        select(ReviewPackage).where(ReviewPackage.pipeline_id == pid)
        .order_by(ReviewPackage.created_at.desc()))
    pkg = rows.scalars().first()
    if pkg is None:
        raise HTTPException(422, "chain finish requires a review package")
    reviews = await list_reviews(db, pid)
    latest: dict[str, ChainReview] = {}
    for r in reviews:
        latest[r.axis] = r
    for axis in ("spec", "quality"):
        rev = latest.get(axis)
        if rev is None or rev.verdict != "pass":
            raise HTTPException(
                422, f"chain finish requires a 'pass' verdict from the "
                     f"'{axis}' reviewer")
        if rev.review_package_id != pkg.id:
            raise HTTPException(
                422, f"chain finish requires the '{axis}' pass to reference "
                     "the latest review package")
    by_stage = {c.stage: c for c in chain}
    tasks = parse_tasks(by_stage["tasks"].artifact) if "tasks" in by_stage else []
    latest_runs = _latest_runs(await list_task_runs(db, pid))
    failed = [t["id"] for t in tasks
              if t["id"] not in latest_runs or not latest_runs[t["id"]].test_passed]
    if failed:
        raise HTTPException(
            422, f"chain finish blocked: tasks without passing tests: "
                 f"{', '.join(failed)}")
    summary = (payload.artifact or
               f"Chain finished: converge done, spec+quality passes on "
               f"package {pkg.id}, all tasks green.")
    row = SpecChainArtifact(
        id=new_chain_id("chain"), pipeline_id=pipe.id, stage="finish",
        artifact=summary, position=len(chain))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"finished": True, "review_package_id": pkg.id,
            "summary": summary}
