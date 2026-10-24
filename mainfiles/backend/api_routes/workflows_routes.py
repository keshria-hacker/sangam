"""
api_routes/workflows_routes.py — Phase 3: visual DAG workflows API.

CRUD for workflows, manual runs, webhook runs (token-authenticated),
replay, and run inspection (node results = dead letter on failure).
All routes live on the protected router except the webhook, which is
authenticated by the per-workflow token in the query string.
"""
import json
import secrets
import uuid
from datetime import datetime, UTC

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..automations import parse_schedule
from ..database import get_db
from ..models import Workflow, WorkflowRun
from ..workflows import WorkflowError, run_workflow_row, validate_definition
from .common import public_router, router


def _wf_out(wf: Workflow) -> dict:
    return {
        "id": wf.id, "name": wf.name,
        "definition": json.loads(wf.definition_json or "{}"),
        "version": wf.version,
        "trigger": wf.trigger, "enabled": wf.enabled,
        "webhook_token_set": bool(wf.webhook_token),
        "next_run": wf.next_run.isoformat() if wf.next_run else None,
        "created_at": wf.created_at.isoformat() if wf.created_at else None,
    }


def _run_out(run: WorkflowRun) -> dict:
    return {
        "id": run.id, "workflow_id": run.workflow_id, "status": run.status,
        "input": json.loads(run.input_json or "{}"),
        "output": json.loads(run.output_json or "{}"),
        "node_results": json.loads(run.node_results_json or "{}"),
        "error": run.error, "replay_of": run.replay_of,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


class WorkflowIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    definition: dict
    trigger: str = "manual"
    enabled: bool = True


class RunIn(BaseModel):
    input: dict = {}
    idempotency_key: str | None = Field(default=None, max_length=128)


@router.post("/workflows", status_code=201)
async def create_workflow(payload: WorkflowIn, db: AsyncSession = Depends(get_db),
                          user=Depends(get_current_user)):
    try:
        validate_definition(payload.definition)
    except WorkflowError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.trigger != "manual":
        from ..automations import validate_automation

        err = validate_automation(payload.trigger, "agent")
        if err:
            raise HTTPException(status_code=422, detail=err)
    wf = Workflow(
        id=f"wf-{uuid.uuid4().hex[:12]}",
        user_id=user.id,
        name=payload.name,
        definition_json=json.dumps(payload.definition),
        trigger=payload.trigger,
        webhook_token=secrets.token_urlsafe(24),
        enabled=payload.enabled,
        next_run=parse_schedule(payload.trigger) if payload.trigger != "manual" else None,
    )
    db.add(wf)
    await db.commit()
    await db.refresh(wf)
    out = _wf_out(wf)
    out["webhook_token"] = wf.webhook_token  # returned once, at creation
    out["webhook_url"] = f"/api/workflows/{wf.id}/webhook?token={wf.webhook_token}"
    return out


@router.get("/workflows")
async def list_workflows(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    rows = (await db.execute(
        select(Workflow).where(Workflow.user_id == user.id).order_by(desc(Workflow.created_at))
    )).scalars().all()
    return {"workflows": [_wf_out(w) for w in rows]}


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str, db: AsyncSession = Depends(get_db),
                       user=Depends(get_current_user)):
    wf = await db.get(Workflow, workflow_id)
    if not wf or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _wf_out(wf)


@router.put("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, payload: WorkflowIn, db: AsyncSession = Depends(get_db),
                          user=Depends(get_current_user)):
    """Update a workflow; a changed definition bumps the version, so
    runs stay attributable to the definition that produced them."""
    wf = await db.get(Workflow, workflow_id)
    if not wf or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="Workflow not found")
    try:
        validate_definition(payload.definition)
    except WorkflowError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if json.loads(wf.definition_json or "{}") != payload.definition:
        wf.version = (wf.version or 1) + 1
    wf.name = payload.name
    wf.definition_json = json.dumps(payload.definition)
    wf.trigger = payload.trigger
    wf.enabled = payload.enabled
    wf.next_run = parse_schedule(payload.trigger) if payload.trigger != "manual" else None
    wf.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(wf)
    return _wf_out(wf)


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str, db: AsyncSession = Depends(get_db),
                          user=Depends(get_current_user)):
    wf = await db.get(Workflow, workflow_id)
    if not wf or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await db.delete(wf)
    await db.commit()
    return {"ok": True}


@router.post("/workflows/{workflow_id}/run", status_code=201)
async def run_workflow(workflow_id: str, payload: RunIn, db: AsyncSession = Depends(get_db),
                       user=Depends(get_current_user)):
    wf = await db.get(Workflow, workflow_id)
    if not wf or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="Workflow not found")
    run = await run_workflow_row(wf, db, payload.input, idempotency_key=payload.idempotency_key)
    return _run_out(run)


@router.get("/workflows/{workflow_id}/runs")
async def list_runs(workflow_id: str, db: AsyncSession = Depends(get_db),
                    user=Depends(get_current_user)):
    wf = await db.get(Workflow, workflow_id)
    if not wf or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="Workflow not found")
    rows = (await db.execute(
        select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id)
        .order_by(desc(WorkflowRun.started_at))
    )).scalars().all()
    return {"runs": [_run_out(r) for r in rows]}


@router.post("/workflows/{workflow_id}/runs/{run_id}/replay", status_code=201)
async def replay_run(workflow_id: str, run_id: str, db: AsyncSession = Depends(get_db),
                     user=Depends(get_current_user)):
    wf = await db.get(Workflow, workflow_id)
    if not wf or wf.user_id != user.id:
        raise HTTPException(status_code=404, detail="Workflow not found")
    old = await db.get(WorkflowRun, run_id)
    if not old or old.workflow_id != workflow_id:
        raise HTTPException(status_code=404, detail="Run not found")
    run = await run_workflow_row(
        wf, db, json.loads(old.input_json or "{}"), replay_of=old.id)
    return _run_out(run)


@public_router.post("/workflows/{workflow_id}/webhook", status_code=201)
async def webhook_run(workflow_id: str, token: str, payload: dict,
                      db: AsyncSession = Depends(get_db)):
    """Webhook trigger: the per-workflow token is the authentication.
    A wrong or missing token returns 404 (not 401) so workflow ids
    cannot be probed for existence."""
    wf = await db.get(Workflow, workflow_id)
    if not wf or not wf.webhook_token or not secrets.compare_digest(token, wf.webhook_token):
        raise HTTPException(status_code=404, detail="Workflow not found")
    if not wf.enabled:
        raise HTTPException(status_code=422, detail="Workflow is disabled")
    run = await run_workflow_row(wf, db, payload if isinstance(payload, dict) else {})
    return _run_out(run)
