"""
analytics/stats.py — aggregate usage stats for the dashboard.

All queries are per-user and bounded (last N days). No raw events leave
the backend — only counts and top-K lists.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from ..feature_flags import is_enabled


async def get_stats(db: Any, user_id: str, days: int = 14) -> dict[str, Any]:
    """Usage stats for the last `days` days."""
    from ..models import AnalyticsEvent

    if not is_enabled("analytics"):
        return {"enabled": False}
    since = datetime.now(UTC) - timedelta(days=days)

    # Events per day.
    day_col = func.date(AnalyticsEvent.created_at).label("day")
    per_day_rows = (
        await db.execute(
            select(day_col, func.count())
            .where(
                AnalyticsEvent.user_id == user_id,
                AnalyticsEvent.created_at >= since,
            )
            .group_by(day_col)
            .order_by(day_col)
        )
    ).all()
    per_day = [{"day": str(day), "count": count} for day, count in per_day_rows]

    # Events by type.
    by_type_rows = (
        await db.execute(
            select(AnalyticsEvent.event_type, func.count())
            .where(
                AnalyticsEvent.user_id == user_id,
                AnalyticsEvent.created_at >= since,
            )
            .group_by(AnalyticsEvent.event_type)
            .order_by(func.count().desc())
        )
    ).all()
    by_type = [{"type": et, "count": c} for et, c in by_type_rows]

    # Top models (from message_sent properties).
    from .events import MESSAGE_SENT

    model_rows = (
        await db.execute(
            select(AnalyticsEvent.properties)
            .where(
                AnalyticsEvent.user_id == user_id,
                AnalyticsEvent.event_type == MESSAGE_SENT,
                AnalyticsEvent.created_at >= since,
            )
            .limit(5000)
        )
    ).scalars().all()
    model_counts: dict[str, int] = {}
    import json

    for raw in model_rows:
        try:
            model = (json.loads(raw or "{}")).get("model")
        except (ValueError, TypeError):
            model = None
        if model:
            model_counts[model] = model_counts.get(model, 0) + 1
    top_models = [
        {"model": m, "count": c}
        for m, c in sorted(model_counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
    ]

    total = sum(c for _, c in by_type_rows)
    return {
        "enabled": True,
        "days": days,
        "total_events": total,
        "per_day": per_day,
        "by_type": by_type,
        "top_models": top_models,
    }
