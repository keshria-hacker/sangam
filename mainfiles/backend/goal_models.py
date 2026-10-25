"""
goal_models.py — Wave-2 deep-knowledge: Goal + Task threads
(paperclip port, single-user scope only).

Sangam previously could not represent "work that remains open": the
only "goals" were free-text strings on a spec payload. These tables
are the structural fix. They live here — NOT in models.py, per the
coordination rules — and are registered on Base.metadata when this
module (or goals_routes) is imported.

* Goal tree: self-referential ``parent_id``, status lifecycle
  planned -> active -> done | cancelled.
* Task tree: self-referential ``parent_id`` (subtasks), optional
  ``goal_id``, status lifecycle backlog -> todo -> in_progress ->
  in_review -> blocked -> done | cancelled (any listed status is
  accepted on update; the lifecycle is a convention, not a locked
  state machine — blocked tasks must be reachable from any state).
* ``work_ref`` bridge: ``work_ref_type`` + ``work_ref_id`` point at
  things Sangam already has — a team-run id, a workflow id, or a
  notebook id — so a task links to the run that closed it.
* ``status_version`` is an optimistic-concurrency counter, bumped
  on every status change (paperclip's ``statusVersion``).

Deliberately NOT ported: companies, multi-user, budgets, org chart.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

GOAL_STATUSES = ("planned", "active", "done", "cancelled")
TASK_STATUSES = ("backlog", "todo", "in_progress", "in_review", "blocked",
                 "done", "cancelled")
WORK_REF_TYPES = ("team_run", "workflow", "notebook", "run", "other")


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    parent_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("goals.id"), nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(16), default="planned")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    goal_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("goals.id"), nullable=True, default=None)
    parent_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("tasks.id"), nullable=True, default=None)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="backlog")
    status_version: Mapped[int] = mapped_column(Integer, default=0)
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    assignee_team: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    work_ref_type: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    work_ref_id: Mapped[str | None] = mapped_column(String(128), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


def goal_out(row: Goal) -> dict:
    return {
        "id": row.id, "title": row.title, "description": row.description,
        "parent_id": row.parent_id, "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def task_out(row: Task) -> dict:
    return {
        "id": row.id, "goal_id": row.goal_id, "parent_id": row.parent_id,
        "title": row.title, "description": row.description,
        "status": row.status, "status_version": row.status_version,
        "priority": row.priority, "assignee_team": row.assignee_team,
        "work_ref_type": row.work_ref_type, "work_ref_id": row.work_ref_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def set_task_status(row: Task, status: str) -> None:
    """Apply a status change, bumping the concurrency counter only
    when the status actually changes."""
    if status not in TASK_STATUSES:
        raise ValueError(f"Unknown task status: {status}")
    if row.status != status:
        row.status = status
        row.status_version = (row.status_version or 0) + 1
        row.updated_at = _now()


def set_goal_status(row: Goal, status: str) -> None:
    if status not in GOAL_STATUSES:
        raise ValueError(f"Unknown goal status: {status}")
    row.status = status
    row.updated_at = _now()


async def goal_tree(db: AsyncSession, user_id: str, goal_id: str) -> dict | None:
    """A goal with nested subgoals and its tasks (one level of task
    nesting is expanded inline; deeper nesting stays reachable via
    the task's own parent_id). Returns None when missing/foreign."""
    goal = await db.get(Goal, goal_id)
    if goal is None or goal.user_id != user_id:
        return None
    out = goal_out(goal)
    children = (await db.execute(
        select(Goal).where(Goal.user_id == user_id, Goal.parent_id == goal.id)
        .order_by(Goal.created_at, Goal.id)
    )).scalars().all()
    out["subgoals"] = [goal_out(c) for c in children]
    tasks = (await db.execute(
        select(Task).where(Task.user_id == user_id, Task.goal_id == goal.id)
        .order_by(Task.created_at, Task.id)
    )).scalars().all()
    by_parent: dict[str | None, list[dict]] = {}
    for t in tasks:
        by_parent.setdefault(t.parent_id, []).append(task_out(t))
    for t in by_parent.get(None, []):
        t["subtasks"] = by_parent.get(t["id"], [])
    out["tasks"] = by_parent.get(None, [])
    out["task_count"] = len(tasks)
    out["open_task_count"] = sum(
        1 for t in tasks if t.status not in ("done", "cancelled"))
    return out


async def open_tasks(db: AsyncSession, user_id: str, goal_id: str | None = None) -> list[Task]:
    """Tasks that remain open (not done/cancelled), optionally
    scoped to one goal — the "what needs me" list for the Work tab."""
    stmt = select(Task).where(
        Task.user_id == user_id,
        Task.status.notin_(("done", "cancelled")),
    ).order_by(desc(Task.created_at), desc(Task.id))
    if goal_id is not None:
        stmt = stmt.where(Task.goal_id == goal_id)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)
