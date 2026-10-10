"""
api_routes/teams_routes.py — multi-agent team API.

Gated end-to-end by FEATURE_MULTI_AGENT. Team runs are synchronous
(non-streaming) JSON: specialists fan out concurrently, the coordinator
synthesizes, and the full result (including per-specialist outputs) is
returned for the UI to render.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..feature_flags import is_enabled
from ..database import get_db
from ..teams import TeamError, list_teams, run_team
from .common import router


def _require_teams() -> None:
    if not is_enabled("multi_agent"):
        raise HTTPException(status_code=404, detail="Multi-agent teams are not enabled")


class TeamRunIn(BaseModel):
    team_id: str = Field(min_length=1)
    task: str = Field(min_length=1, max_length=8000)
    model: str | None = None


@router.get("/teams")
async def get_teams():
    """List available agent teams."""
    _require_teams()
    return list_teams()


@router.post("/teams/run")
async def run_team_endpoint(
    payload: TeamRunIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Run a team on a task: fan-out to specialists, fan-in via coordinator."""
    _require_teams()
    from ..analytics import events as _ae, optional_user_id, record_event as _record
    from ..llm import default_model_id

    model_id = payload.model or await default_model_id(db)
    if not model_id:
        raise HTTPException(status_code=400, detail="No model available.")
    try:
        result = await run_team(payload.team_id, payload.task, model_id, db)
    except TeamError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _record(db, await optional_user_id(request, db), _ae.TEAM_RUN,
                  {"team_id": payload.team_id})
    if result.error and not result.synthesis:
        raise HTTPException(status_code=502, detail=result.error)
    return result.to_dict()


@router.post("/teams/run/stream")
async def run_team_stream_endpoint(
    payload: TeamRunIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Stream a team run as SSE: per-specialist output + synthesis."""
    _require_teams()
    from fastapi.responses import StreamingResponse
    from ..llm import default_model_id
    from ..teams.streaming import stream_team_run, format_sse, new_run_id

    model_id = payload.model or await default_model_id(db)
    if not model_id:
        raise HTTPException(status_code=400, detail="No model available.")

    run_id = new_run_id()

    async def _gen():
        async for event in stream_team_run(payload.team_id, payload.task, model_id, db, run_id=run_id):
            # Check if client disconnected
            if await request.is_disconnected():
                break
            yield format_sse(event)

    return StreamingResponse(_gen(), media_type="text/event-stream")


class TeamStopIn(BaseModel):
    run_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)


@router.post("/teams/stop-agent")
async def stop_agent_endpoint(payload: TeamStopIn):
    """Stop a single specialist mid-stream via task cancellation."""
    _require_teams()
    from ..teams.streaming import stop_specialist

    stopped = stop_specialist(payload.run_id, payload.agent_id)
    return {"run_id": payload.run_id, "agent_id": payload.agent_id, "stopped": stopped}


class TeamRetryIn(BaseModel):
    team_id: str = Field(min_length=1)
    task: str = Field(min_length=1, max_length=8000)
    agent_id: str = Field(min_length=1)
    model: str | None = None


@router.post("/teams/retry-agent")
async def retry_agent_endpoint(
    payload: TeamRetryIn,
    db: AsyncSession = Depends(get_db),
):
    """Retry a single specialist agent."""
    _require_teams()
    from ..llm import default_model_id
    from ..teams.definitions import get_team
    from ..teams.runner import _run_specialist

    model_id = payload.model or await default_model_id(db)
    if not model_id:
        raise HTTPException(status_code=400, detail="No model available.")

    team = get_team(payload.team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    spec = next((s for s in team.specialists if s.id == payload.agent_id), None)
    if not spec:
        raise HTTPException(status_code=404, detail="Agent not found in team")

    result = await _run_specialist(spec, payload.task, model_id, db)
    return {
        "agent_id": result.agent_id,
        "role": result.role,
        "output": result.output,
        "error": result.error,
        "elapsed_s": round(result.elapsed_s, 2),
    }
