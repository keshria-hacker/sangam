"""
api_routes/goals_routes.py — Wave-2 deep-knowledge: Goal + Task API.

Surfaced in the Work tab via API (frontend wiring is the parent's;
this module + goal_models.py are the endpoints + data model).

  POST   /goals                        create goal (tree via parent_id)
  GET    /goals                        goals with task counts
  GET    /goals/{id}                   goal tree (subgoals + tasks)
  PATCH  /goals/{id}                   title/description/status
  POST   /goals/{id}/tasks             create task under a goal
  GET    /goals/{id}/tasks             tasks of a goal
  GET    /tasks                        open tasks (or all with ?open=false)
  GET    /tasks/{id}                   one task
  PATCH  /tasks/{id}                   status/priority/work_ref/assignee

Importing this module registers the handlers on the shared router
AND the goals/tasks tables on Base.metadata. The parent wires it by
importing this module from api.py (routes are not self-mounting).
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..goal_models import (
    GOAL_STATUSES,
    TASK_STATUSES,
    WORK_REF_TYPES,
    Goal,
    Task,
    goal_out,
    goal_tree,
    open_tasks,
    set_goal_status,
    set_task_status,
    task_out,
)
from .common import router

__all__ = [
    "create_goal", "list_goals", "get_goal", "update_goal",
    "create_task", "list_goal_tasks", "list_tasks", "get_task",
    "update_task",
]

def _new_goal_id() -> str:
    from ..goal_models import _new_id

    return _new_id("goal")


def _new_task_id() -> str:
    from ..goal_models import _new_id

    return _new_id("task")


async def _get_goal(db: AsyncSession, user_id: str, goal_id: str) -> Goal:
    row = await db.get(Goal, goal_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Goal not found")
    return row


async def _get_task(db: AsyncSession, user_id: str, task_id: str) -> Task:
    row = await db.get(Task, task_id)
    if row is None or row.user_id != user_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


class GoalIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    parent_id: str | None = None


class GoalUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: str | None = None


@router.post("/goals", status_code=201)
async def create_goal(
    payload: GoalIn, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    if payload.parent_id is not None:
        await _get_goal(db, user.id, payload.parent_id)
    row = Goal(id=_new_goal_id(), user_id=user.id, title=payload.title,
               description=payload.description or "",
               parent_id=payload.parent_id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return goal_out(row)


@router.get("/goals")
async def list_goals(
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    goals = (await db.execute(
        select(Goal).where(Goal.user_id == user.id)
        .order_by(desc(Goal.created_at), desc(Goal.id))
    )).scalars().all()
    out = []
    for g in goals:
        item = goal_out(g)
        tasks = (await db.execute(
            select(Task).where(Task.user_id == user.id, Task.goal_id == g.id)
        )).scalars().all()
        item["task_count"] = len(tasks)
        item["open_task_count"] = sum(
            1 for t in tasks if t.status not in ("done", "cancelled"))
        out.append(item)
    return {"goals": out}


@router.get("/goals/{goal_id}")
async def get_goal(
    goal_id: str, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    tree = await goal_tree(db, user.id, goal_id)
    if tree is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return tree


@router.patch("/goals/{goal_id}")
async def update_goal(
    goal_id: str, payload: GoalUpdateIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    row = await _get_goal(db, user.id, goal_id)
    if payload.title is not None:
        row.title = payload.title
    if payload.description is not None:
        row.description = payload.description
    if payload.status is not None:
        if payload.status not in GOAL_STATUSES:
            raise HTTPException(status_code=422, detail=f"Unknown goal status: {payload.status}")
        set_goal_status(row, payload.status)
    await db.commit()
    await db.refresh(row)
    return goal_out(row)


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    parent_id: str | None = None
    priority: str = "medium"
    assignee_team: str | None = None
    work_ref_type: str | None = None
    work_ref_id: str | None = None


class TaskUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    assignee_team: str | None = None
    work_ref_type: str | None = None
    work_ref_id: str | None = None


def _check_work_ref(payload_work_ref_type: str | None) -> None:
    if payload_work_ref_type is not None and payload_work_ref_type not in WORK_REF_TYPES:
        raise HTTPException(
            status_code=422, detail=f"Unknown work_ref_type: {payload_work_ref_type}")


@router.post("/goals/{goal_id}/tasks", status_code=201)
async def create_task(
    goal_id: str, payload: TaskIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    goal = await _get_goal(db, user.id, goal_id)
    _check_work_ref(payload.work_ref_type)
    if payload.parent_id is not None:
        parent = await _get_task(db, user.id, payload.parent_id)
        if parent.goal_id != goal.id:
            raise HTTPException(status_code=422, detail="Subtask parent belongs to another goal")
    row = Task(id=_new_task_id(), user_id=user.id, goal_id=goal.id,
               parent_id=payload.parent_id, title=payload.title,
               description=payload.description or "", priority=payload.priority,
               assignee_team=payload.assignee_team,
               work_ref_type=payload.work_ref_type, work_ref_id=payload.work_ref_id)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return task_out(row)


@router.get("/goals/{goal_id}/tasks")
async def list_goal_tasks(
    goal_id: str, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    goal = await _get_goal(db, user.id, goal_id)
    rows = (await db.execute(
        select(Task).where(Task.user_id == user.id, Task.goal_id == goal.id)
        .order_by(Task.created_at, Task.id)
    )).scalars().all()
    return {"goal_id": goal.id, "tasks": [task_out(r) for r in rows]}


@router.get("/tasks")
async def list_tasks(
    goal_id: str | None = None, open_only: bool = True,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    if open_only:
        rows = await open_tasks(db, user.id, goal_id=goal_id)
    else:
        stmt = select(Task).where(Task.user_id == user.id).order_by(
            desc(Task.created_at), desc(Task.id))
        if goal_id is not None:
            stmt = stmt.where(Task.goal_id == goal_id)
        rows = (await db.execute(stmt)).scalars().all()
    return {"tasks": [task_out(r) for r in rows]}


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str, db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    return task_out(await _get_task(db, user.id, task_id))


@router.patch("/tasks/{task_id}")
async def update_task(
    task_id: str, payload: TaskUpdateIn,
    db: AsyncSession = Depends(get_db), user=Depends(get_current_user),
):
    row = await _get_task(db, user.id, task_id)
    _check_work_ref(payload.work_ref_type)
    if payload.title is not None:
        row.title = payload.title
    if payload.description is not None:
        row.description = payload.description
    if payload.status is not None:
        if payload.status not in TASK_STATUSES:
            raise HTTPException(status_code=422, detail=f"Unknown task status: {payload.status}")
        set_task_status(row, payload.status)
    if payload.priority is not None:
        row.priority = payload.priority
    if payload.assignee_team is not None:
        row.assignee_team = payload.assignee_team
    if payload.work_ref_type is not None:
        row.work_ref_type = payload.work_ref_type
    if payload.work_ref_id is not None:
        row.work_ref_id = payload.work_ref_id
    await db.commit()
    await db.refresh(row)
    return task_out(row)
