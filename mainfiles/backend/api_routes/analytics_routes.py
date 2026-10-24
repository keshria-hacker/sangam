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


@router.get("/analytics/summary")
async def analytics_summary(
    days: int = 14,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Quota-view summary: the shape Settings > Models & Routing polls.

    Batch 8 fix: the routing quota view polled ``/analytics/summary``,
    which never existed, so it always fell back to "Analytics not
    enabled". Windows, stated honestly because they differ: ``messages``
    is the count of message_sent events in the last ``days`` days from
    the database; ``tokens``/``cost_usd`` are process-lifetime totals
    from the in-memory provider telemetry ledger (reset on restart, and
    cost stays 0.0 unless the caller supplied prices — the ledger never
    invents a price). Single-user app, so the process-global ledger is
    the requesting user's ledger.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from ..analytics.events import MESSAGE_SENT
    from ..contracts import telemetry_ledger
    from ..models import AnalyticsEvent

    _require_analytics()
    days = max(1, min(days, 90))
    since = datetime.now(UTC) - timedelta(days=days)
    messages = await db.scalar(
        select(func.count()).where(
            AnalyticsEvent.user_id == current_user.id,
            AnalyticsEvent.event_type == MESSAGE_SENT,
            AnalyticsEvent.created_at >= since,
        )
    ) or 0
    totals = telemetry_ledger.totals()
    return {"summary": {
        "messages": int(messages),
        "tokens": int(totals["input_tokens"]) + int(totals["output_tokens"]),
        "cost_usd": totals["cost_usd"],
    }}
