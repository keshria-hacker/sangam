"""api_routes/agent_runtime_routes.py — A4 agent runtime API.

Routes (mounted under /api by main.py via api.py; the webhook is on the
public router, authenticated by per-task token like workflow webhooks):

  POST   /agent-tasks                    create a task (plan validated)
  GET    /agent-tasks                    list (filter: status, trigger)
  GET    /agent-tasks/{task_id}          detail: steps, budget gauge, audit count
  POST   /agent-tasks/{task_id}/run      execute/resume pending steps
  POST   /agent-tasks/{task_id}/pause    pause (pending/running -> paused)
  POST   /agent-tasks/{task_id}/cancel   cancel
  POST   /agent-tasks/{task_id}/record-usage   observed usage + budget enforcement
  GET    /agent-tasks/{task_id}/audit    audit trail, oldest first
  GET    /agent-tasks/{task_id}/notifications (also /agent-notifications)
  POST   /agent-tasks/scheduler/tick     run everything due (tasks + workflows)
  POST   /agent-tasks/security-graph     Recon->Vuln-hunter->Validator->Reporter task
  POST   /agent-tasks/{task_id}/webhook  (public, token) event/webhook trigger run
  POST   /agent-tasks/{task_id}/event    (auth) event trigger run
  GET    /agent-approvals                pending approval queue (runtime tasks)
  POST   /agent-tasks/{task_id}/approvals/{approval_id}/decide
  GET    /agent-notifications            in-app notifications
  POST   /agent-notifications/{notification_id}/read

Security notes: every route is per-user (tasks, approvals, notifications
are filtered by the caller's tasks); approval decisions require the
approval row to belong to the task; the webhook returns 404 on a bad
token so task ids cannot be probed. No route weakens the security
module: the pentest graph still requires an allowlisted target, and
active tool execution stays in the Security workspace.
"""

from __future__ import annotations

import secrets
from datetime import datetime, UTC

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent_runtime.models import (
    AgentAuditEvent, AgentNotification, AgentTask,
)
from ..agent_runtime.planner import PlanError
from ..agent_runtime.scheduler import tick as scheduler_tick
from ..agent_runtime.service import (
    TaskConflict, TaskNotFound, create_security_graph, create_task,
    decide_approval, get_task_or_404, load_steps, record_usage,
    run_task, set_task_state,
)
from ..agent_runtime.store import (
    audit_to_dict, notification_to_dict, task_to_dict,
)
from ..auth import get_current_user
from ..database import get_db
from ..hooks import AgentApproval
from .common import public_router, router


def _task_out(task, steps) -> dict:
    return task_to_dict(task, steps)


async def _load_task(db, task_id: str, user_id: str) -> AgentTask:
    try:
        return await get_task_or_404(db, task_id, user_id)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    agent_id: str | None = None
    approval_policy: str = "default"
    token_budget: int = 0
    cost_budget_usd: float = 0.0
    trigger: str = "manual"
    enabled: bool = True
    next_run: str | None = None
    config: dict = {}
    steps: list[dict] = Field(min_length=1)


class UsageIn(BaseModel):
    tokens: int | None = None
    cost_usd: float | None = None


class DecideIn(BaseModel):
    approved: bool
    reason: str = ""


class SecurityGraphIn(BaseModel):
    target: str = Field(min_length=1, max_length=512)
    scope: str = ""


class EventIn(BaseModel):
    event: str = ""


@router.post("/agent-tasks", status_code=201)
async def create_agent_task(payload: TaskIn, db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    try:
        task = await create_task(db, user.id, payload.model_dump())
    except (PlanError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    steps = await load_steps(db, task.id)
    out = _task_out(task, steps)
    if task.trigger == "webhook":
        # Returned once, at creation — like workflow webhook tokens.
        out["webhook_token"] = task.webhook_token
    return out


@router.get("/agent-tasks")
async def list_agent_tasks(db: AsyncSession = Depends(get_db),
                           user=Depends(get_current_user),
                           status: str | None = None,
                           trigger: str | None = None):
    stmt = select(AgentTask).where(AgentTask.user_id == user.id)
    if status:
        stmt = stmt.where(AgentTask.status == status)
    if trigger:
        stmt = stmt.where(AgentTask.trigger == trigger)
    rows = (await db.execute(stmt.order_by(desc(AgentTask.created_at)))).scalars().all()
    out = []
    for task in rows:
        steps = await load_steps(db, task.id)
        out.append(_task_out(task, steps))
    return {"tasks": out}


@router.post("/agent-tasks/scheduler/tick")
async def run_scheduler_tick(db: AsyncSession = Depends(get_db),
                             user=Depends(get_current_user)):
    """Run everything due for the caller: scheduled agent tasks and
    scheduled workflows (the workflow scheduler's tick, callable)."""
    return await scheduler_tick(db, user.id)


@router.post("/agent-tasks/security-graph", status_code=201)
async def create_security_graph_task(payload: SecurityGraphIn,
                                     db: AsyncSession = Depends(get_db),
                                     user=Depends(get_current_user)):
    try:
        result = await create_security_graph(db, user.id, payload.target, payload.scope)
    except PlanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TaskConflict as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    task = result["task"]
    steps = await load_steps(db, task.id)
    out = _task_out(task, steps)
    out["security_run_id"] = result["security_run_id"]
    return out


@router.get("/agent-tasks/{task_id}")
async def get_agent_task(task_id: str, db: AsyncSession = Depends(get_db),
                         user=Depends(get_current_user)):
    task = await _load_task(db, task_id, user.id)
    steps = await load_steps(db, task.id)
    out = _task_out(task, steps)
    audit_count = (await db.execute(
        select(AgentAuditEvent).where(AgentAuditEvent.task_id == task.id))).scalars().all()
    out["audit_count"] = len(audit_count)
    return out


@router.post("/agent-tasks/{task_id}/run")
async def run_agent_task(task_id: str, payload: dict | None = None,
                         db: AsyncSession = Depends(get_db),
                         user=Depends(get_current_user)):
    task = await _load_task(db, task_id, user.id)
    try:
        result = await run_task(db, task, user.id, (payload or {}).get("input") or {})
    except TaskConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    out = _task_out(result["task"], result["steps"])
    out["summary"] = result["summary"]
    out["needs_approval"] = result["needs_approval"]
    return out


@router.post("/agent-tasks/{task_id}/pause")
async def pause_agent_task(task_id: str, db: AsyncSession = Depends(get_db),
                           user=Depends(get_current_user)):
    task = await _load_task(db, task_id, user.id)
    try:
        task = await set_task_state(db, task, "paused", user.id)
    except TaskConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _task_out(task, await load_steps(db, task.id))


@router.post("/agent-tasks/{task_id}/cancel")
async def cancel_agent_task(task_id: str, db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    task = await _load_task(db, task_id, user.id)
    try:
        task = await set_task_state(db, task, "cancelled", user.id)
    except TaskConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _task_out(task, await load_steps(db, task.id))


@router.post("/agent-tasks/{task_id}/record-usage")
async def record_task_usage(task_id: str, payload: UsageIn,
                            db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    task = await _load_task(db, task_id, user.id)
    try:
        result = await record_usage(db, task, user.id, payload.tokens, payload.cost_usd)
    except TaskConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _task_out(result["task"], await load_steps(db, task.id))


@router.get("/agent-tasks/{task_id}/audit")
async def get_task_audit(task_id: str, db: AsyncSession = Depends(get_db),
                         user=Depends(get_current_user)):
    task = await _load_task(db, task_id, user.id)
    rows = (await db.execute(
        select(AgentAuditEvent).where(AgentAuditEvent.task_id == task.id)
        .order_by(AgentAuditEvent.created_at))).scalars().all()
    return {"task_id": task.id, "audit": [audit_to_dict(r) for r in rows]}


@router.get("/agent-tasks/{task_id}/notifications")
async def get_task_notifications(task_id: str, db: AsyncSession = Depends(get_db),
                                 user=Depends(get_current_user)):
    task = await _load_task(db, task_id, user.id)
    rows = (await db.execute(
        select(AgentNotification).where(AgentNotification.task_id == task.id)
        .order_by(desc(AgentNotification.created_at)))).scalars().all()
    return {"notifications": [notification_to_dict(r) for r in rows]}


@router.post("/agent-tasks/{task_id}/event")
async def fire_task_event(task_id: str, payload: EventIn,
                          db: AsyncSession = Depends(get_db),
                          user=Depends(get_current_user)):
    """Event trigger: runs the task only when its trigger is 'event' and
    the event name matches the task config (empty config matches any)."""
    task = await _load_task(db, task_id, user.id)
    if task.trigger != "event":
        raise HTTPException(status_code=422, detail="task trigger is not 'event'")
    expected = (task.config().get("event") or "")
    if expected and payload.event != expected:
        raise HTTPException(status_code=422,
                            detail=f"event {payload.event!r} does not match {expected!r}")
    try:
        result = await run_task(db, task, user.id, {"event": payload.event})
    except TaskConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    out = _task_out(result["task"], result["steps"])
    out["summary"] = result["summary"]
    return out


@public_router.post("/agent-tasks/{task_id}/webhook")
async def run_task_webhook(task_id: str, request: Request,
                           token: str | None = None,
                           db: AsyncSession = Depends(get_db)):
    """Webhook trigger: per-task token auth (wrong token -> 404, no
    existence leak, same as workflow webhooks). Disabled tasks and
    non-webhook tasks are refused."""
    task = await db.get(AgentTask, task_id)
    authed = bool(task and token and task.webhook_token
                  and secrets.compare_digest(token, task.webhook_token))
    if not authed:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.enabled or task.trigger != "webhook":
        raise HTTPException(status_code=422, detail="Task webhook is not enabled")
    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — empty/non-JSON bodies run with {}
        body = {}
    try:
        result = await run_task(db, task, task.user_id,
                                body if isinstance(body, dict) else {})
    except TaskConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    out = _task_out(result["task"], result["steps"])
    out["summary"] = result["summary"]
    return out


@router.get("/agent-approvals")
async def list_agent_approvals(db: AsyncSession = Depends(get_db),
                               user=Depends(get_current_user),
                               status: str | None = "pending"):
    """Approval queue for this user's runtime tasks. AgentApproval rows
    carry no user id, so scope is via the owning task."""
    task_ids = (await db.execute(
        select(AgentTask.id).where(AgentTask.user_id == user.id))).scalars().all()
    if not task_ids:
        return {"approvals": []}
    stmt = select(AgentApproval).where(AgentApproval.run_id.in_(task_ids))
    if status:
        stmt = stmt.where(AgentApproval.status == status)
    rows = (await db.execute(stmt.order_by(AgentApproval.created_at))).scalars().all()
    return {"approvals": [
        {"id": r.id, "task_id": r.run_id, "tool": r.tool,
         "args": __import__("json").loads(r.args_json or "{}"),
         "status": r.status, "reason": r.reason,
         "created_at": r.created_at.isoformat() if r.created_at else None,
         "decided_at": r.decided_at.isoformat() if r.decided_at else None}
        for r in rows]}


@router.post("/agent-tasks/{task_id}/approvals/{approval_id}/decide")
async def decide_task_approval(task_id: str, approval_id: str, payload: DecideIn,
                               db: AsyncSession = Depends(get_db),
                               user=Depends(get_current_user)):
    task = await _load_task(db, task_id, user.id)
    try:
        return await decide_approval(db, task, approval_id, payload.approved,
                                     payload.reason, user.id)
    except TaskNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TaskConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/agent-notifications")
async def list_notifications(db: AsyncSession = Depends(get_db),
                             user=Depends(get_current_user),
                             unread_only: bool = False):
    stmt = select(AgentNotification).where(AgentNotification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(AgentNotification.read.is_(False))
    rows = (await db.execute(stmt.order_by(desc(AgentNotification.created_at)))).scalars().all()
    return {"notifications": [notification_to_dict(r) for r in rows]}


@router.post("/agent-notifications/{notification_id}/read")
async def read_notification(notification_id: str, db: AsyncSession = Depends(get_db),
                            user=Depends(get_current_user)):
    row = await db.get(AgentNotification, notification_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    row.read = True
    await db.commit()
    return notification_to_dict(row)
