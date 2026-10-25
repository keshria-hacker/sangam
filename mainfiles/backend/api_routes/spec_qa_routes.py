"""api_routes/spec_qa_routes.py — A5 routes (spec v2, QA, code-graph
extensions, deploy interface).

Registered on the shared router by ONE import block in api.py (the
coordinator merges that block; this module itself makes no api.py
edit). All routes are authenticated like the other /api routes.

Spec v2 (``/api/spec-v2/*``): the full state machine from
``backend/spec/state_machine.py`` — constitution -> spec -> clarify
-> plan -> checklist -> tasks -> analyze -> implement -> verify
-> converge — with TDD evidence per task, GreenContract verification
records, review packages + PR-style review artifact, and a computed
convergence report. The old ``/engineering/*/chain/*`` routes are
untouched.

QA (``/api/qa/*``): GreenContract levels, report builder, and body
normalization. Recording/replay themselves are library functions in
``backend/qa/`` (they need a TestClient, so they live in tests, not
in a self-referential HTTP endpoint).

Code graph (``/api/code-graph/*``): cycles, architecture overview,
change impact, and search v2 — the existing code-graph routes file
is untouched; these are additive endpoints only.

Deploy (``/api/deploy/*``): interface status only. Every connector
reports ``deferred``; there is no deploy endpoint, by design.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..code_graph import cached_graph, ensure_fresh_graph
from ..code_graph_queries import (
    architecture_overview,
    change_impact,
    circular_imports,
    search_code_v2,
)
from ..database import get_db
from ..deploy_interface import (
    check_deploy_permission,
    list_deploy_connectors,
)
from ..qa.greencontract import (
    LEVELS,
    LEVEL_DESCRIPTIONS,
    graduated_satisfied,
    level_index,
    validate_verification_record,
)
from ..qa.noise import normalize_json
from ..qa.report import build_report, render_report_markdown
from ..spec import validate_stage
from ..spec.checklist import validate_checklist  # noqa: F401 — re-exported for tests
from ..spec.converge import build_convergence_report, compute_gaps
from ..spec.models import (
    SpecV2Pipeline,
    SpecV2Review,
    SpecV2ReviewPackage,
    SpecV2Stage,
    SpecV2TaskEvidence,
    SpecV2Verification,
    new_spec2_id,
)
from ..spec.review import diff_files, render_pr_review
from ..spec.state_machine import STAGES
from ..spec.tdd import validate_tdd_evidence
from ..spec_chain import apply_clarifications, parse_tasks, sha
from .common import router


# ---------------------------------------------------------------- spec v2
class SpecV2In(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    goal: str = ""


class AdvanceV2In(BaseModel):
    stage: str
    artifact: str = ""
    clarifications: list[dict] | None = None


class EvidenceIn(BaseModel):
    diff: str = ""
    test_command: str = ""
    red_output: str = ""
    green_output: str = ""


class VerifyRecordIn(BaseModel):
    level: str
    test_command: str = ""
    output: str = ""
    passed: bool = False


class ReviewV2In(BaseModel):
    verdict: str
    artifact: str = ""
    review_package_id: str


async def _get_pipe(db: AsyncSession, pid: str) -> SpecV2Pipeline:
    row = await db.execute(
        select(SpecV2Pipeline).where(SpecV2Pipeline.id == pid))
    pipe = row.scalars().first()
    if pipe is None:
        raise HTTPException(404, "Spec pipeline not found")
    return pipe


async def _stages(db: AsyncSession, pid: str) -> list[SpecV2Stage]:
    rows = await db.execute(
        select(SpecV2Stage).where(SpecV2Stage.pipeline_id == pid)
        .order_by(SpecV2Stage.position))
    return list(rows.scalars().all())


async def _evidence_map(db: AsyncSession, pid: str) -> dict[str, dict]:
    rows = await db.execute(
        select(SpecV2TaskEvidence).where(
            SpecV2TaskEvidence.pipeline_id == pid)
        .order_by(SpecV2TaskEvidence.created_at))
    out: dict[str, dict] = {}
    for r in rows.scalars().all():
        out[r.task_id] = {"tdd_ok": bool(r.tdd_ok), "diff": r.diff,
                          "test_command": r.test_command}
    return out


async def _verifications(db: AsyncSession, pid: str) -> list[dict]:
    rows = await db.execute(
        select(SpecV2Verification).where(
            SpecV2Verification.pipeline_id == pid)
        .order_by(SpecV2Verification.created_at))
    return [{"level": r.level, "passed": bool(r.passed),
             "test_command": r.test_command} for r in rows.scalars().all()]


async def _reviews(db: AsyncSession, pid: str) -> list[SpecV2Review]:
    rows = await db.execute(
        select(SpecV2Review).where(SpecV2Review.pipeline_id == pid)
        .order_by(SpecV2Review.created_at))
    return list(rows.scalars().all())


def _pipe_out(pipe: SpecV2Pipeline, stages: list[SpecV2Stage]) -> dict:
    return {"id": pipe.id, "title": pipe.title, "goal": pipe.goal,
            "current_stage": pipe.current_stage or None,
            "stages": STAGES,
            "stage_artifacts": [{"id": s.id, "stage": s.stage,
                                 "artifact": s.artifact} for s in stages]}


@router.post("/spec-v2", status_code=201)
async def create_spec_v2(payload: SpecV2In, db: AsyncSession = Depends(get_db),
                         user=Depends(get_current_user)):
    pipe = SpecV2Pipeline(id=new_spec2_id("spec2"), title=payload.title,
                          goal=payload.goal or "")
    db.add(pipe)
    await db.commit()
    return {"id": pipe.id, "title": pipe.title, "goal": pipe.goal,
            "current_stage": None, "stages": STAGES}


@router.get("/spec-v2")
async def list_spec_v2(db: AsyncSession = Depends(get_db),
                       user=Depends(get_current_user)):
    rows = await db.execute(
        select(SpecV2Pipeline).order_by(desc(SpecV2Pipeline.created_at)))
    out = []
    for pipe in rows.scalars().all():
        out.append(_pipe_out(pipe, await _stages(db, pipe.id)))
    return out


@router.get("/spec-v2/{pid}")
async def get_spec_v2(pid: str, db: AsyncSession = Depends(get_db),
                      user=Depends(get_current_user)):
    pipe = await _get_pipe(db, pid)
    return _pipe_out(pipe, await _stages(db, pid))


@router.get("/spec-v2/{pid}/artifacts")
async def spec_v2_artifacts(pid: str, db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    await _get_pipe(db, pid)
    stages = await _stages(db, pid)
    return {"pipeline_id": pid,
            "artifacts": [{"stage": s.stage, "artifact": s.artifact}
                          for s in stages]}


@router.post("/spec-v2/{pid}/advance")
async def advance_spec_v2(pid: str, payload: AdvanceV2In,
                          db: AsyncSession = Depends(get_db),
                          user=Depends(get_current_user)):
    pipe = await _get_pipe(db, pid)
    if payload.stage not in STAGES:
        raise HTTPException(422, f"unknown spec stage: {payload.stage!r}")
    stages = await _stages(db, pid)
    by_stage = {s.stage: s for s in stages}
    context: dict = {
        "current_stage": pipe.current_stage or "",
        "spec": by_stage["spec"].artifact if "spec" in by_stage else None,
        "tasks": by_stage["tasks"].artifact if "tasks" in by_stage else "",
        "clarifications": payload.clarifications,
        "evidence": await _evidence_map(db, pid),
        "verifications": await _verifications(db, pid),
    }
    if payload.stage == "converge":
        analysis = by_stage["analysis"].artifact if "analysis" in by_stage else ""
        tasks_text = by_stage["tasks"].artifact if "tasks" in by_stage else ""
        reviews = await _reviews(db, pid)
        context["gaps"] = compute_gaps(
            context["spec"] or "", analysis, tasks_text,
            context["evidence"], context["verifications"])
    try:
        validate_stage(payload.stage, payload.artifact, context)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    artifact = payload.artifact
    if payload.stage == "clarify":
        # Write clarifications back into the stored spec, like the old
        # chain: markers resolved in the spec itself, not a side channel.
        spec_row = by_stage["spec"]
        spec_row.artifact = apply_clarifications(
            spec_row.artifact, payload.clarifications or [])
        artifact = artifact or (
            "Clarifications written back into the spec:\n" +
            "\n".join(f"- {c.get('question')}: {c.get('answer')}"
                      for c in (payload.clarifications or [])))
    row = SpecV2Stage(id=new_spec2_id("spec2s"), pipeline_id=pipe.id,
                      stage=payload.stage, artifact=artifact,
                      position=len(stages))
    db.add(row)
    pipe.current_stage = payload.stage
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "stage": row.stage, "artifact": row.artifact,
            "current_stage": pipe.current_stage}


@router.post("/spec-v2/{pid}/tasks/{task_id}/evidence")
async def spec_v2_evidence(pid: str, task_id: str, payload: EvidenceIn,
                           db: AsyncSession = Depends(get_db),
                           user=Depends(get_current_user)):
    await _get_pipe(db, pid)
    stages = await _stages(db, pid)
    by_stage = {s.stage: s for s in stages}
    if "tasks" not in by_stage:
        raise HTTPException(422, "no stored tasks stage: advance the chain first")
    try:
        tasks = parse_tasks(by_stage["tasks"].artifact)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if task_id not in {t["id"] for t in tasks}:
        raise HTTPException(404, f"Unknown task {task_id}")
    try:
        validate_tdd_evidence(payload.test_command, payload.red_output,
                              payload.green_output)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    row = SpecV2TaskEvidence(
        id=new_spec2_id("spec2e"), pipeline_id=pid, task_id=task_id,
        diff=payload.diff, test_command=payload.test_command,
        red_output=payload.red_output[-4000:],
        green_output=payload.green_output[-4000:], tdd_ok=1)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "task_id": task_id, "tdd_ok": True,
            "test_command": payload.test_command}


@router.post("/spec-v2/{pid}/verify-record")
async def spec_v2_verify_record(pid: str, payload: VerifyRecordIn,
                                db: AsyncSession = Depends(get_db),
                                user=Depends(get_current_user)):
    await _get_pipe(db, pid)
    try:
        level_index(payload.level)
        validate_verification_record(payload.level, payload.test_command,
                                     payload.output, payload.passed)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    existing = await _verifications(db, pid)
    idx = LEVELS.index(payload.level)
    if idx > 0 and not graduated_satisfied(LEVELS[idx - 1], existing):
        raise HTTPException(
            422, f"GreenContract: level '{payload.level}' requires "
                 f"'{LEVELS[idx - 1]}' passed first")
    row = SpecV2Verification(
        id=new_spec2_id("spec2v"), pipeline_id=pid, level=payload.level,
        test_command=payload.test_command, output=payload.output[-4000:],
        passed=1 if payload.passed else 0)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "level": payload.level, "passed": payload.passed,
            "next_level": (LEVELS[idx + 1] if payload.passed and idx + 1 < len(LEVELS)
                           else None)}


@router.post("/spec-v2/{pid}/review-package")
async def spec_v2_review_package(pid: str, db: AsyncSession = Depends(get_db),
                                 user=Depends(get_current_user)):
    await _get_pipe(db, pid)
    stages = await _stages(db, pid)
    by_stage = {s.stage: s for s in stages}
    if "tasks" not in by_stage:
        raise HTTPException(422, "no stored tasks stage")
    evidence = await _evidence_map(db, pid)
    diffs = [f"## Task {tid}\n{ev['diff']}" for tid, ev in sorted(evidence.items())
             if ev["diff"]]
    if not diffs:
        raise HTTPException(
            422, "review package requires a non-empty diff: no task "
                 "evidence has produced file changes yet")
    diff = "\n\n".join(diffs)
    pkg = SpecV2ReviewPackage(
        id=new_spec2_id("spec2p"), pipeline_id=pid,
        base_ref=sha(by_stage["tasks"].artifact), head_ref=sha(diff), diff=diff)
    db.add(pkg)
    await db.commit()
    await db.refresh(pkg)
    return {"id": pkg.id, "base_ref": pkg.base_ref,
            "head_ref": pkg.head_ref, "diff": pkg.diff}


@router.post("/spec-v2/{pid}/review/{axis}")
async def spec_v2_review(pid: str, axis: str, payload: ReviewV2In,
                         db: AsyncSession = Depends(get_db),
                         user=Depends(get_current_user)):
    await _get_pipe(db, pid)
    if axis not in ("spec", "quality"):
        raise HTTPException(422, "review axis must be 'spec' or 'quality'")
    if payload.verdict not in ("pass", "fail"):
        raise HTTPException(422, "review verdict must be 'pass' or 'fail'")
    rows = await db.execute(
        select(SpecV2ReviewPackage).where(
            SpecV2ReviewPackage.id == payload.review_package_id))
    pkg = rows.scalars().first()
    if pkg is None or pkg.pipeline_id != pid:
        raise HTTPException(422, "review_package_id must be a package of this pipeline")
    if payload.review_package_id not in (payload.artifact or ""):
        raise HTTPException(
            422, "review artifact must reference its review_package_id")
    row = SpecV2Review(
        id=new_spec2_id("spec2r"), pipeline_id=pid, axis=axis,
        verdict=payload.verdict, review_package_id=payload.review_package_id,
        artifact=payload.artifact)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {"id": row.id, "axis": axis, "verdict": payload.verdict,
            "review_package_id": payload.review_package_id}


@router.get("/spec-v2/{pid}/review-pr")
async def spec_v2_review_pr(pid: str, db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    pipe = await _get_pipe(db, pid)
    rows = await db.execute(
        select(SpecV2ReviewPackage).where(
            SpecV2ReviewPackage.pipeline_id == pid)
        .order_by(SpecV2ReviewPackage.created_at.desc()))
    pkg = rows.scalars().first()
    if pkg is None:
        raise HTTPException(422, "no review package yet")
    reviews = await _reviews(db, pid)
    review_dicts = [{"axis": r.axis, "verdict": r.verdict,
                     "review_package_id": r.review_package_id,
                     "artifact": r.artifact} for r in reviews]
    md = render_pr_review(pipe.title, pkg.diff, review_dicts)
    return {"review_pr": md, "files": diff_files(pkg.diff),
            "review_package_id": pkg.id, "reviews": review_dicts}


@router.post("/spec-v2/{pid}/converge-report")
async def spec_v2_converge_report(pid: str, db: AsyncSession = Depends(get_db),
                                  user=Depends(get_current_user)):
    await _get_pipe(db, pid)
    stages = await _stages(db, pid)
    by_stage = {s.stage: s for s in stages}
    spec = by_stage["spec"].artifact if "spec" in by_stage else ""
    tasks_text = by_stage["tasks"].artifact if "tasks" in by_stage else ""
    analysis = by_stage["analysis"].artifact if "analysis" in by_stage else ""
    evidence = await _evidence_map(db, pid)
    verifications = await _verifications(db, pid)
    reviews = await _reviews(db, pid)
    review_dicts = [{"axis": r.axis, "verdict": r.verdict} for r in reviews]
    report, gaps = build_convergence_report(
        spec, tasks_text, analysis, evidence, verifications, review_dicts)
    return {"report": report, "gaps": gaps}


# --------------------------------------------------------------------- QA
class NormalizeIn(BaseModel):
    body: dict = {}
    noise_fields: list[str] = []


class ReportIn(BaseModel):
    results: list[dict] = []
    untested: list[str] = []


@router.get("/qa/levels")
async def qa_levels(user=Depends(get_current_user)):
    return {"levels": LEVELS,
            "descriptions": LEVEL_DESCRIPTIONS}


@router.post("/qa/normalize")
async def qa_normalize(payload: NormalizeIn, user=Depends(get_current_user)):
    return {"normalized": normalize_json(payload.body, payload.noise_fields)}


@router.post("/qa/report")
async def qa_report(payload: ReportIn, user=Depends(get_current_user)):
    report = build_report(payload.results, payload.untested)
    return {**report, "markdown": render_report_markdown(report)}


# ------------------------------------------------------- code-graph extensions
def _resolve_root(root: str | None) -> Path:
    from ..tools.builtin import _get_workspace_root
    base = _get_workspace_root()
    if not root:
        return base
    cand = (base / root).resolve()
    try:
        cand.relative_to(base)
    except ValueError:
        raise ValueError(f"root escapes workspace: {root!r}")
    return cand


def _graph_or_error(root: str | None):
    try:
        base = _resolve_root(root)
    except ValueError as exc:
        return None, None, {"error": str(exc)}
    graph, warning = ensure_fresh_graph(base)
    if graph is None:
        return None, warning, {"error": warning or "code graph unavailable"}
    return graph, warning, None


@router.get("/code-graph/cycles")
async def graph_cycles(root: str | None = Query(default=None),
                       user=Depends(get_current_user)):
    graph, _warning, err = _graph_or_error(root)
    if err:
        return err
    return circular_imports(graph)


@router.get("/code-graph/architecture")
async def graph_architecture(root: str | None = Query(default=None),
                             user=Depends(get_current_user)):
    graph, _warning, err = _graph_or_error(root)
    if err:
        return err
    return architecture_overview(graph)


@router.get("/code-graph/impact")
async def graph_impact(target: str = Query(min_length=1),
                       root: str | None = Query(default=None),
                       user=Depends(get_current_user)):
    graph, _warning, err = _graph_or_error(root)
    if err:
        return err
    return change_impact(graph, target)


@router.get("/code-graph/search-v2")
async def graph_search_v2(q: str = Query(min_length=1),
                          regex: bool = Query(default=False),
                          top_k: int = Query(default=10, ge=1, le=50),
                          root: str | None = Query(default=None),
                          user=Depends(get_current_user)):
    graph, _warning, err = _graph_or_error(root)
    if err:
        return err
    base = _resolve_root(root)
    return search_code_v2(graph, q, root=base, regex=regex, top_k=top_k)


# ------------------------------------------------------------------- deploy
@router.get("/deploy/connectors")
async def deploy_connectors(user=Depends(get_current_user)):
    return {"connectors": list_deploy_connectors(),
            "note": "Deferred (user decision 2026-10-25): interface only, "
                    "no live Coolify/Quickemu dependency."}


@router.get("/deploy/permissions")
async def deploy_permissions(role: str = Query(default="owner"),
                             user=Depends(get_current_user)):
    from ..deploy_interface import DeployPermission
    return {"role": role,
            "permissions": {p.value: check_deploy_permission(role, p)
                            for p in DeployPermission}}
