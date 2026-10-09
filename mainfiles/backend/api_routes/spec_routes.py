"""
api_routes/spec_routes.py — spec wizard API (Phase 4).
"""
from fastapi import Depends
from pydantic import BaseModel

from ..auth import get_current_user
from ..spec_wizard import build_spec, spec_to_agent_task
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
    """Convert a spec into a Code Agent task."""
    spec = build_spec(payload.title, payload.problem, payload.goals,
                      payload.constraints, payload.plan, payload.tasks)
    return {"task": spec_to_agent_task(spec), "spec": spec}
