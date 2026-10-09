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
from ..database import get_db
from ..teams import TeamError, list_teams, run_team
from .common import router


def _require_teams() -> None:
    if not settings.FEATURE_MULTI_AGENT:
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
