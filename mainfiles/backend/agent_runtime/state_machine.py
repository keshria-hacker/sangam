"""State machines for tasks and steps (server-side, never a browser timer).

Terminal states are final: ``completed`` and ``cancelled`` accept no
further transition. ``failed`` may return to ``pending`` exactly once
per resume attempt (the user fixes the cause — e.g. raises the budget —
then resumes); the run endpoint enforces that a failed task only resumes
from its still-pending steps, never by re-running completed ones.
"""

from __future__ import annotations

TASK_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending", "cancelled"},
    "pending": {"running", "paused", "cancelled"},
    "running": {"paused", "completed", "failed", "waiting_approval", "cancelled"},
    "paused": {"running", "pending", "cancelled"},
    "waiting_approval": {"pending", "paused", "cancelled"},
    "failed": {"pending", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}

STEP_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"running", "skipped", "waiting_approval"},
    "running": {"completed", "failed", "skipped", "waiting_approval"},
    "waiting_approval": {"pending", "skipped", "completed"},
    "completed": set(),
    "failed": set(),
    "skipped": set(),
}


class StateError(ValueError):
    """Illegal state transition; message is safe to return to the client."""


def can_transition(current: str, target: str, table: dict[str, set[str]]) -> bool:
    return target in table.get(current or "", set())


def transition(current: str, target: str, table: dict[str, set[str]]) -> str:
    """Return ``target`` or raise StateError for an illegal transition."""
    if not can_transition(current, target, table):
        raise StateError(f"cannot move from {current!r} to {target!r}")
    return target
