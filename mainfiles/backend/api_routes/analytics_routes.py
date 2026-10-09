"""
api_routes/analytics_routes.py — private analytics dashboard API.

Opt-in via FEATURE_ANALYTICS. Only the requesting user's own aggregates
are exposed; raw events never leave the backend.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics import get_stats
from ..auth import get_current_user
from ..config import settings
from ..feature_flags import is_enabled
from ..database import get_db
from .common import router


def _require_analytics() -> None:
    if not is_enabled("analytics"):
        raise HTTPException(status_code=404, detail="Analytics are not enabled")


@router.get("/analytics/stats")
async def analytics_stats(
    days: int = 14,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Aggregate usage stats for the current user (last N days)."""
    _require_analytics()
    days = max(1, min(days, 90))
    return await get_stats(db, current_user.id, days=days)
