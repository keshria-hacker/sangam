"""
api_routes/routing_routes.py — backend routing rule evaluation (Phase 7).

Routing rules are stored in user settings (routingRules as JSON).
This endpoint evaluates them server-side so every client and automation
uses the same logic.
"""
from __future__ import annotations

import json

from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from .common import router


class RoutingEvaluateIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


def evaluate_routing_rules(message: str, rules: list[dict]) -> str | None:
    """Evaluate routing rules against a message. Returns model_id or None."""
    lower = message.lower()
    for r in rules:
        if not r.get("enabled", True):
            continue
        keywords = [
            k.strip().lower()
            for k in (r.get("keywords") or "").split(",")
            if k.strip()
        ]
        if keywords and any(k in lower for k in keywords):
            return r.get("model_id")
    return None


@router.post("/routing/evaluate")
async def evaluate_routing(
    payload: RoutingEvaluateIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Evaluate the user's routing rules against a message.

    Returns {"model_id": ...} if a rule matches, {"model_id": None} otherwise.
    """
    from ..models import UserPreference

    from sqlalchemy import select
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == user.id)
    )
    pref = result.scalar_one_or_none()

    rules = []
    if pref and pref.settings_json:
        try:
            settings = json.loads(pref.settings_json)
            rules_raw = settings.get("routingRules", "[]")
            rules = json.loads(rules_raw) if isinstance(rules_raw, str) else rules_raw
        except Exception:
            rules = []

    model_id = evaluate_routing_rules(payload.message, rules or [])
    return {"model_id": model_id, "matched": model_id is not None}
