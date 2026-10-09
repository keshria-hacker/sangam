"""
api_routes/compare_routes.py — parallel model comparison + Arena (Phase 6.4c).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, UTC

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import ArenaResult
from .common import router


class CompareIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    models: list[str] = Field(min_length=2, max_length=4)
    max_tokens: int = 500


@router.post("/compare")
async def compare_models(
    payload: CompareIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Run the same prompt against multiple models in parallel."""
    from ..llm import stream_completion

    async def _run_one(model_id: str) -> dict:
        started = time.monotonic()
        parts = []
        try:
            async for chunk in stream_completion(
                model_id,
                [{"role": "user", "content": payload.prompt}],
                db,
                max_tokens=payload.max_tokens,
            ):
                text = chunk if isinstance(chunk, str) else getattr(chunk, "text", None)
                if text:
                    parts.append(text)
            return {
                "model": model_id,
                "output": "".join(parts),
                "elapsed_s": round(time.monotonic() - started, 2),
                "error": None,
            }
        except Exception as exc:
            return {
                "model": model_id,
                "output": "",
                "elapsed_s": round(time.monotonic() - started, 2),
                "error": str(exc),
            }

    results = await asyncio.gather(*(_run_one(m) for m in payload.models))
    return {"results": list(results)}


class ArenaVoteIn(BaseModel):
    prompt: str = Field(min_length=1)
    winner_model: str = Field(min_length=1)
    loser_model: str = Field(min_length=1)
    models_compared: list[str] = Field(min_length=2)


@router.post("/arena/vote", status_code=201)
async def arena_vote(
    payload: ArenaVoteIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Record an Arena vote (which model won)."""
    result = ArenaResult(
        id=f"arena-{uuid.uuid4().hex[:12]}",
        user_id=user.id,
        prompt=payload.prompt[:500],
        winner_model=payload.winner_model,
        loser_model=payload.loser_model,
        models_compared=",".join(payload.models_compared),
        created_at=datetime.now(UTC),
    )
    db.add(result)
    await db.commit()
    return {"id": result.id}


@router.get("/arena/leaderboard")
async def arena_leaderboard(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Get Arena leaderboard (win rates by model)."""
    results = (
        await db.execute(
            select(ArenaResult)
            .where(ArenaResult.user_id == user.id)
            .order_by(desc(ArenaResult.created_at))
            .limit(1000)
        )
    ).scalars().all()

    wins: dict[str, int] = {}
    losses: dict[str, int] = {}
    for r in results:
        wins[r.winner_model] = wins.get(r.winner_model, 0) + 1
        losses[r.loser_model] = losses.get(r.loser_model, 0) + 1

    leaderboard = []
    for model in set(list(wins.keys()) + list(losses.keys())):
        w = wins.get(model, 0)
        l = losses.get(model, 0)
        total = w + l
        leaderboard.append({
            "model": model,
            "wins": w,
            "losses": l,
            "win_rate": round(w / total, 3) if total else 0,
        })

    leaderboard.sort(key=lambda x: x["win_rate"], reverse=True)
    return {"leaderboard": leaderboard, "total_votes": len(results)}
