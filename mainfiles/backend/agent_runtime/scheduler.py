"""Scheduler — scheduled + recurring runs through the runtime.

Wraps :func:`backend.automations.parse_schedule` (hourly/daily/weekly/
cron — cron keeps the existing simplified next-hour semantics, stated
here so nobody mistakes it for full cron evaluation) instead of
re-implementing schedule math.

Two entry points:

* :func:`tick` — synchronous callable (also exposed as
  POST /agent-tasks/scheduler/tick): runs every due, enabled agent task
  and every due, enabled workflow whose trigger is not manual, then
  advances its ``next_run``. This is what makes the workflow scheduler
  — previously only an opt-in background loop — callable and testable.
* :func:`start_agent_scheduler` — the opt-in 30s background loop
  (``SANGAM_AGENT_SCHEDULER=1``), mirroring
  :func:`backend.workflows.start_workflow_scheduler`. It is NOT started
  by this module; the coordinator wires it into the app lifespan if
  wanted, or operators call the tick endpoint.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

from sqlalchemy import select

from ..automations import parse_schedule


def next_run_after(trigger: str, from_dt: datetime | None = None) -> datetime | None:
    """Next run for a trigger (delegates to automations.parse_schedule)."""
    return parse_schedule(trigger)


def _as_aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes; stored values are UTC by
    # construction (every writer here uses datetime.now(UTC)).
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def due_agent_tasks(rows, now: datetime) -> list:
    return [r for r in rows
            if r.enabled and r.trigger not in ("manual", "event", "webhook")
            and r.next_run is not None and _as_aware(r.next_run) <= now
            and r.status not in ("running", "waiting_approval",
                                 "completed", "cancelled")]


def due_workflows(rows, now: datetime) -> list:
    return [r for r in rows
            if r.enabled and r.trigger != "manual"
            and r.next_run is not None and _as_aware(r.next_run) <= now]


async def tick(db, user_id: str) -> dict:
    """Run everything due for one user; advance every schedule (a failed
    run still advances: recurring means 'try again next interval', and
    the failure is in the task's audit + notification)."""
    from ..models import Workflow
    from .models import AgentTask
    from .service import run_task

    now = datetime.now(UTC)
    out: dict = {"agent_tasks": [], "workflows": [], "at": now.isoformat()}
    tasks = (await db.execute(
        select(AgentTask).where(AgentTask.user_id == user_id))).scalars().all()
    for task in due_agent_tasks(tasks, now):
        try:
            result = await run_task(db, task, user_id, {})
            out["agent_tasks"].append(
                {"id": task.id, "status": result["task"].status})
        except Exception as exc:  # noqa: BLE001 — one due task never blocks the tick
            out["agent_tasks"].append({"id": task.id, "error": str(exc)[:300]})
        task.next_run = parse_schedule(task.trigger)
        task.last_run = now
        await db.commit()
    workflows = (await db.execute(
        select(Workflow).where(Workflow.user_id == user_id))).scalars().all()
    from ..workflows import run_workflow_row

    for wf in due_workflows(workflows, now):
        try:
            run = await run_workflow_row(wf, db, {})
            out["workflows"].append({"id": wf.id, "status": run.status})
        except Exception as exc:  # noqa: BLE001 — same rule as tasks
            out["workflows"].append({"id": wf.id, "error": str(exc)[:300]})
        wf.next_run = parse_schedule(wf.trigger)
        await db.commit()
    return out


async def start_agent_scheduler(app=None) -> None:
    """Opt-in loop (SANGAM_AGENT_SCHEDULER=1). Ticks every 30s for all
    users with due tasks/workflows. Kept out of the default path so
    tests never get surprise executions."""
    if os.environ.get("SANGAM_AGENT_SCHEDULER") != "1":
        return
    while True:
        await asyncio.sleep(30)
        try:
            from ..database import AsyncSessionLocal
            from .models import AgentTask

            async with AsyncSessionLocal() as db:
                user_ids = (await db.execute(
                    select(AgentTask.user_id).distinct())).scalars().all()
                for user_id in user_ids:
                    try:
                        await tick(db, user_id)
                    except Exception:
                        pass
        except Exception:
            pass
