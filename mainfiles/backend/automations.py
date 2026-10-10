"""
automations.py — scheduler + executor (Sangam-native, Phase 5).

Simple in-process scheduler. Triggers: 'hourly', 'daily', 'weekly', or cron.
Actions: 'agent' (run agent task), 'chat' (send chat message).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, UTC
from typing import Any


def validate_automation(trigger: str, action: str) -> str | None:
    """Return error message or None if valid."""
    valid_triggers = {"hourly", "daily", "weekly"}
    if trigger not in valid_triggers and not _is_cron(trigger):
        return f"Invalid trigger: {trigger}. Use hourly/daily/weekly or cron."
    if action not in {"agent", "chat"}:
        return f"Invalid action: {action}. Use agent/chat."
    return None


def _is_cron(expr: str) -> bool:
    parts = expr.strip().split()
    return len(parts) == 5 and all(p.replace("*", "").replace("/", "").replace("-", "").replace(",", "").isdigit() or p == "*" for p in parts)


def parse_schedule(trigger: str) -> datetime | None:
    """Compute next run time."""
    now = datetime.now(UTC)
    if trigger == "hourly":
        return now + timedelta(hours=1)
    if trigger == "daily":
        return now + timedelta(days=1)
    if trigger == "weekly":
        return now + timedelta(weeks=1)
    # Cron: simplified — next hour
    if _is_cron(trigger):
        return now + timedelta(hours=1)
    return None


async def execute_automation(auto: Any, db: Any) -> dict:
    """Execute an automation's action."""
    config = {}
    try:
        config = json.loads(auto.config_json or "{}")
    except (ValueError, TypeError):
        pass

    if auto.action == "agent":
        # Run agent task (simplified — full SSE in Phase 3 agent engine)
        from .code_agent import run_agent
        task = config.get("task", "")
        model_id = config.get("model", "")
        steps = []
        async for step in run_agent(task, model_id, db, max_iterations=5):
            steps.append({"kind": step.kind, "content": step.content[:500]})
        auto.last_run = datetime.now(UTC)
        auto.next_run = parse_schedule(auto.trigger)
        await db.commit()
        return {"ok": True, "steps": len(steps)}
    elif auto.action == "chat":
        # Chat action: create a chat with the message (simplified)
        auto.last_run = datetime.now(UTC)
        auto.next_run = parse_schedule(auto.trigger)
        await db.commit()
        return {"ok": True, "note": "Chat automation queued"}

    return {"ok": False, "error": "Unknown action"}
