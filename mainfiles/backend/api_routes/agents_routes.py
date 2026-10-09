"""
api_routes/agents_routes.py — Agent Hub: custom agents CRUD + runs (Phase 3).

Sangam-native; no external product names in the API.
"""
import json

from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import llm
from ..auth import get_current_user
from ..code_agent import CHAT_AGENT_TOOLS, CODE_AGENT_TOOLS, run_agent
from ..database import get_db
from ..models import CustomAgent
from .common import router

ALL_TOOLS = sorted(set(CHAT_AGENT_TOOLS) | set(CODE_AGENT_TOOLS))


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    system_prompt: str | None = None
    model_id: str | None = Field(default=None, max_length=128)
    tool_names: list[str] | None = None
    max_steps: int = Field(default=8, ge=1, le=25)


class AgentRunIn(BaseModel):
    task: str = Field(min_length=1)


def _out(agent: CustomAgent) -> dict:
    try:
        tools = json.loads(agent.tool_names) if agent.tool_names else []
    except (ValueError, TypeError):
        tools = []
    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "model_id": agent.model_id,
        "tool_names": tools,
        "max_steps": agent.max_steps,
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
        "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
    }


async def _get_owned(agent_id: str, user_id: str, db: AsyncSession) -> CustomAgent:
    agent = await db.get(CustomAgent, agent_id)
    if not agent or agent.user_id != user_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.get("/agents")
async def list_agents(db: AsyncSession = Depends(get_db),
                      current_user=Depends(get_current_user)):
    """List the caller's custom agents."""
    res = await db.execute(
        select(CustomAgent).where(CustomAgent.user_id == current_user.id)
        .order_by(CustomAgent.updated_at.desc())
    )
    return [_out(a) for a in res.scalars().all()]


@router.post("/agents")
async def create_agent(payload: AgentIn, db: AsyncSession = Depends(get_db),
                       current_user=Depends(get_current_user)):
    """Create a custom agent."""
    tools = [t for t in (payload.tool_names or []) if t in ALL_TOOLS]
    agent = CustomAgent(
        user_id=current_user.id,
        name=payload.name.strip(),
        description=(payload.description or "").strip() or None,
        system_prompt=(payload.system_prompt or "").strip() or None,
        model_id=(payload.model_id or "").strip() or None,
        tool_names=json.dumps(tools),
        max_steps=payload.max_steps,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return _out(agent)


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db),
                    current_user=Depends(get_current_user)):
    return _out(await _get_owned(agent_id, current_user.id, db))


@router.put("/agents/{agent_id}")
async def update_agent(agent_id: str, payload: AgentIn, db: AsyncSession = Depends(get_db),
                       current_user=Depends(get_current_user)):
    agent = await _get_owned(agent_id, current_user.id, db)
    tools = [t for t in (payload.tool_names or []) if t in ALL_TOOLS]
    agent.name = payload.name.strip()
    agent.description = (payload.description or "").strip() or None
    agent.system_prompt = (payload.system_prompt or "").strip() or None
    agent.model_id = (payload.model_id or "").strip() or None
    agent.tool_names = json.dumps(tools)
    agent.max_steps = payload.max_steps
    await db.commit()
    await db.refresh(agent)
    return _out(agent)


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db),
                       current_user=Depends(get_current_user)):
    agent = await _get_owned(agent_id, current_user.id, db)
    await db.delete(agent)
    await db.commit()
    return {"ok": True}


@router.post("/agents/{agent_id}/run")
async def run_custom_agent(agent_id: str, payload: AgentRunIn,
                           db: AsyncSession = Depends(get_db),
                           current_user=Depends(get_current_user)):
    """Run a custom agent on a task. Streams SSE: thought, tool_call, tool_result, answer, done, error."""
    agent = await _get_owned(agent_id, current_user.id, db)
    task = (payload.task or "").strip()
    if not task:
        raise HTTPException(status_code=422, detail="Task is required")

    model_id = agent.model_id or await llm.default_model_id(db)
    if not model_id:
        raise HTTPException(status_code=400, detail="No model available")
    try:
        tool_names = json.loads(agent.tool_names) if agent.tool_names else []
    except (ValueError, TypeError):
        tool_names = []
    tool_names = [t for t in tool_names if t in ALL_TOOLS] or CHAT_AGENT_TOOLS
    max_steps = max(1, min(int(agent.max_steps or 8), 25))

    async def _stream():
        kwargs = {}
        if agent.system_prompt and agent.system_prompt.strip():
            kwargs["system_prompt"] = agent.system_prompt.strip()
        async for step in run_agent(task, model_id, db,
                                    tool_names=tool_names,
                                    max_iterations=max_steps,
                                    **kwargs):
            data = {"kind": step.kind, "content": step.content}
            if step.tool_name:
                data["tool"] = step.tool_name
            yield f"data: {json.dumps(data)}\n\n"
        yield "data: {\"kind\": \"end\"}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")
