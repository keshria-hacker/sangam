"""
api_routes/runs_routes.py — agent run history (Phase 3).

Stores completed agent runs for search, review, and re-run.
"""
import json
import uuid
from datetime import datetime, UTC

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import AgentRun
from .common import router


class RunIn(BaseModel):
    kind: str  # 'agent' | 'code-agent' | 'team'
    title: str
    model: str | None = None
    status: str = "done"
    tokens: int = 0
    cost_usd: float = 0.0
    steps: list[dict] | None = None
    error: str | None = None


@router.post("/runs", status_code=201)
async def record_run(payload: RunIn, db: AsyncSession = Depends(get_db),
                     user=Depends(get_current_user)):
    """Record a completed agent run."""
    run = AgentRun(
        id=f"run-{uuid.uuid4().hex[:12]}",
        user_id=user.id,
        kind=payload.kind,
        title=payload.title[:200],
        model=payload.model,
        status=payload.status,
        tokens=payload.tokens,
        cost_usd=payload.cost_usd,
        steps_json=json.dumps(payload.steps or [])[:50000],
        error=payload.error,
        created_at=datetime.now(UTC),
    )
    db.add(run)
    await db.commit()
    return {"id": run.id}


@router.get("/runs")
async def list_runs(db: AsyncSession = Depends(get_db),
                    user=Depends(get_current_user),
                    q: str | None = None,
                    kind: str | None = None,
                    limit: int = 50):
    """List run history, newest first. Optional search."""
    stmt = select(AgentRun).where(AgentRun.user_id == user.id)
    if kind:
        stmt = stmt.where(AgentRun.kind == kind)
    if q:
        stmt = stmt.where(AgentRun.title.ilike(f"%{q}%"))
    stmt = stmt.order_by(desc(AgentRun.created_at)).limit(min(limit, 200))
    runs = (await db.execute(stmt)).scalars().all()
    return {"runs": [
        {"id": r.id, "kind": r.kind, "title": r.title, "model": r.model,
         "status": r.status, "tokens": r.tokens, "cost_usd": r.cost_usd,
         "error": r.error, "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in runs
    ]}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, db: AsyncSession = Depends(get_db),
                  user=Depends(get_current_user)):
    """Get a single run with its steps."""
    run = await db.get(AgentRun, run_id)
    if not run or run.user_id != user.id:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Run not found")
    steps = []
    try:
        steps = json.loads(run.steps_json or "[]")
    except (ValueError, TypeError):
        pass
    return {
        "id": run.id, "kind": run.kind, "title": run.title, "model": run.model,
        "status": run.status, "tokens": run.tokens, "cost_usd": run.cost_usd,
        "error": run.error, "steps": steps,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }
