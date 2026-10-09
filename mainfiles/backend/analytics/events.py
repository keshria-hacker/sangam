"""
analytics/events.py — local-first event recording (openpanel-style).

Opt-in via FEATURE_ANALYTICS. Events are aggregate-friendly only: a type
plus small JSON properties. Message content and prompts are NEVER stored.
When the flag is off, record() is a silent no-op.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Well-known event types emitted across the backend.
MESSAGE_SENT = "message_sent"
TEAM_RUN = "team_run"
LESSON_STARTED = "lesson_started"
IMAGE_GENERATED = "image_generated"
VOICE_TTS = "voice_tts"
VOICE_STT = "voice_stt"
PACK_ENABLED = "pack_enabled"
SKILL_EXECUTED = "skill_executed"


async def optional_user_id(request: Any, db: Any) -> str | None:
    """Best-effort user id from the request's session. Returns None (never
    raises) when the request is unauthenticated — analytics then skips."""
    try:
        from ..auth import AUTH_COOKIE_NAME, _hash_token
        from ..models import AuthSession
        from datetime import UTC, datetime

        from sqlalchemy import select

        token = request.cookies.get(AUTH_COOKIE_NAME)
        if token is None:
            authorization = request.headers.get("authorization", "")
            if authorization.lower().startswith("bearer "):
                token = authorization[7:].strip()
        if not token:
            return None
        result = await db.execute(
            select(AuthSession.user_id).where(
                AuthSession.token_hash == _hash_token(token),
                AuthSession.expires_at > datetime.now(UTC),
            )
        )
        return result.scalar_one_or_none()
    except Exception:  # noqa: BLE001 — analytics never breaks product
        return None


async def record_event(
    db: Any,
    user_id: str | None,
    event_type: str,
    properties: dict[str, Any] | None = None,
) -> bool:
    """Record an analytics event. Returns True if stored."""
    from ..config import settings

    if not settings.FEATURE_ANALYTICS:
        return False
    if not user_id:
        return False
    try:
        from ..models import AnalyticsEvent

        db.add(
            AnalyticsEvent(
                user_id=user_id,
                event_type=event_type,
                properties=json.dumps(properties or {}),
            )
        )
        await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — analytics never breaks product
        logger.warning("analytics record failed: %s", exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False
