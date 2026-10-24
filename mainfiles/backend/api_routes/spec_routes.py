"""
api_routes/spec_routes.py — spec API (Phase 4, Wave-1 rework).

spec_wizard.py is retired. Specs are now spec-kit documents built by
spec_chain; /spec/to-task no longer dumps the whole spec into one
agent prompt — it returns one brief per task (task_briefs), which is
how the chain's implement stage dispatches agents.
"""
from fastapi import Depends
from pydantic import BaseModel

from ..auth import get_current_user
from ..spec_chain import build_spec, render_tasks, task_briefs
from .common import router


class SpecIn(BaseModel):
    title: str
    problem: str = ""
    goals: list[str] = []
    constraints: list[str] = []
    plan: list[str] = []
    tasks: list[str] = []


@router.post("/spec/build")
async def build_spec_doc(payload: SpecIn, user=Depends(get_current_user)):
    """Build a spec document from wizard inputs."""
    spec = build_spec(payload.title, payload.problem, payload.goals,
                      payload.constraints, payload.plan, payload.tasks)
    return {"spec": spec}


@router.post("/spec/to-task")
async def spec_to_task(payload: SpecIn, user=Depends(get_current_user)):
    """Convert a spec into per-task agent briefs (one brief per task).

    The retired whole-spec single-prompt dispatch is gone: ``task``
    carries the first task's brief for single-task callers, and
    ``task_briefs`` carries one brief per task.
    """
    spec = build_spec(payload.title, payload.problem, payload.goals,
                      payload.constraints, payload.plan, payload.tasks)
    task_items = [{"title": t, "files": ["src/app.py"], "parallel": False}
                  for t in payload.tasks]
    briefs = task_briefs(spec, render_tasks(task_items)) if task_items else []
    return {"task_briefs": [b["brief"] for b in briefs],
            "task": briefs[0]["brief"] if briefs else spec,
            "spec": spec}
