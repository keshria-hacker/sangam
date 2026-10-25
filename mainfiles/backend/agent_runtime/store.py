"""Serialisers + durable helpers: audit log, notification bus, Runs mirror.

Helpers only ADD rows; callers own the commit so a run's step updates,
audits, notifications, and Runs mirror commit together.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from .budgets import BudgetMeter
from .models import AgentAuditEvent, AgentNotification


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def budget_gauge(task) -> dict:
    # The "unknown usage" flag is sticky task state (a fresh meter would
    # forget it): the service persists it in task config after every
    # run / usage recording. Absent (never run), usage is vacuously known.
    known = task.config().get("usage_known", True)
    return BudgetMeter(
        token_budget=int(task.token_budget or 0),
        cost_budget_usd=float(task.cost_budget_usd or 0.0),
        tokens_used=int(task.tokens_used or 0),
        cost_used=float(task.cost_used or 0.0),
        unknown_usage=not bool(known),
    ).gauge()


def step_to_dict(step) -> dict:
    return {
        "id": step.id, "name": step.name, "kind": step.kind,
        "tool": step.tool, "args": step.args(),
        "depends_on": step.depends_on(), "order": step.order,
        "status": step.status, "result": step.result(),
        "error": step.error, "attempts": step.attempts,
        "approval_id": step.approval_id,
    }


def task_to_dict(task, steps) -> dict:
    config = task.config()
    return {
        "id": task.id, "title": task.title, "agent_id": task.agent_id,
        "status": task.status, "approval_policy": task.approval_policy,
        "trigger": task.trigger, "enabled": task.enabled,
        "next_run": _iso(task.next_run), "last_run": _iso(task.last_run),
        "budget": budget_gauge(task),
        "budget_exceeded": bool(task.budget_exceeded),
        "circuit_tripped": bool(task.circuit_tripped),
        "circuit_reason": task.circuit_reason,
        "summary": task.summary(), "config": config,
        "error": task.error,
        "created_at": _iso(task.created_at),
        "updated_at": _iso(task.updated_at),
        "steps": [step_to_dict(s) for s in steps],
        "webhook_url": (f"/api/agent-tasks/{task.id}/webhook"
                        if task.trigger == "webhook" else None),
    }


def audit_to_dict(row) -> dict:
    return {"id": row.id, "task_id": row.task_id, "action": row.action,
            "detail": row.detail, "created_at": _iso(row.created_at)}


def notification_to_dict(row) -> dict:
    return {"id": row.id, "task_id": row.task_id, "kind": row.kind,
            "message": row.message, "read": bool(row.read),
            "created_at": _iso(row.created_at)}


def add_audit(db, task_id: str | None, user_id: str, action: str, detail: str = "") -> None:
    db.add(AgentAuditEvent(
        id=f"aa-{uuid.uuid4().hex[:12]}", task_id=task_id, user_id=user_id,
        action=action, detail=(detail or "")[:2000],
        created_at=datetime.now(UTC)))


def add_notification(db, task_id: str | None, user_id: str, kind: str, message: str) -> None:
    db.add(AgentNotification(
        id=f"an-{uuid.uuid4().hex[:12]}", task_id=task_id, user_id=user_id,
        kind=kind, message=(message or "")[:2000], read=False,
        created_at=datetime.now(UTC)))


def mirror_agent_run(db, task, steps, status: str) -> None:
    """Mirror a terminal task outcome onto the Runs store (agent_runs)
    so run history, audit, and notifications agree. Best-effort in the
    sense that a mirror failure must not rewrite the task outcome — the
    caller still commits the task; this row is additive history."""
    from ..models import AgentRun

    step_rows = [{"name": s.name, "kind": s.kind, "status": s.status,
                  "error": s.error} for s in steps]
    db.add(AgentRun(
        id=f"run-{uuid.uuid4().hex[:12]}", user_id=task.user_id,
        kind="agent-task", title=f"{task.title} [{task.id}]",
        model=task.agent_id, status="done" if status == "completed" else status,
        tokens=int(task.tokens_used or 0),
        cost_usd=float(task.cost_used or 0.0),
        steps_json=json.dumps(step_rows)[:50000], error=task.error,
        created_at=datetime.now(UTC)))
