"""agent_runtime models — durable task state (restart-safe by design).

All runtime state lives in these tables, never only in memory, so a task
survives an app restart: re-creating the runtime against the same DB
recovers the task, its completed steps, its pending approvals, and its
budget/circuit state, and a later run resumes from the pending steps.

Approval decisions themselves reuse :class:`backend.hooks.AgentApproval`
(the existing durable approval table); steps point at it via
``approval_id``. This module adds no second approval table.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _now() -> datetime:
    return datetime.now(UTC)


class AgentTask(Base):
    """One planned agent task: a plan (steps with dependencies) plus the
    policy/budget/schedule that govern its execution.

    status: draft | pending | running | paused | waiting_approval |
    completed | failed | cancelled (see state_machine.TASK_TRANSITIONS).
    approval_policy: default | once | always | deny (aliases automatic /
    always_ask are normalised on write by approvals.normalize_policy).
    trigger: manual | hourly | daily | weekly | cron | event | webhook.
    token_budget / cost_budget_usd: 0 means unlimited.
    """

    __tablename__ = "agent_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    approval_policy: Mapped[str] = mapped_column(String(20), default="default")
    token_budget: Mapped[int] = mapped_column(default=0)
    cost_budget_usd: Mapped[float] = mapped_column(default=0.0)
    tokens_used: Mapped[int] = mapped_column(default=0)
    cost_used: Mapped[float] = mapped_column(default=0.0)
    budget_exceeded: Mapped[bool] = mapped_column(default=False)
    circuit_tripped: Mapped[bool] = mapped_column(default=False)
    circuit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger: Mapped[str] = mapped_column(String(64), default="manual")
    enabled: Mapped[bool] = mapped_column(default=True)
    next_run: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    webhook_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    def config(self) -> dict:
        try:
            return json.loads(self.config_json or "{}")
        except (ValueError, TypeError):
            return {}

    def set_config(self, value: dict) -> None:
        self.config_json = json.dumps(value)

    def summary(self) -> dict:
        try:
            return json.loads(self.summary_json or "{}")
        except (ValueError, TypeError):
            return {}


class AgentTaskStep(Base):
    """One step of a task plan. ``name`` is the plan identity used by
    ``depends_on``; ``status`` follows state_machine.STEP_TRANSITIONS.
    ``result_json`` holds the real step output (never fabricated); a
    step that never ran has no result. ``approval_id`` points at a
    :class:`backend.hooks.AgentApproval` row when the step is gated.
    """

    __tablename__ = "agent_task_steps"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("agent_tasks.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32), default="echo")
    tool: Mapped[str | None] = mapped_column(String(128), nullable=True)
    args_json: Mapped[str] = mapped_column(Text, default="{}")
    depends_on_json: Mapped[str] = mapped_column(Text, default="[]")
    order: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(default=0)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    def args(self) -> dict:
        try:
            out = json.loads(self.args_json or "{}")
            return out if isinstance(out, dict) else {}
        except (ValueError, TypeError):
            return {}

    def depends_on(self) -> list:
        try:
            out = json.loads(self.depends_on_json or "[]")
            return out if isinstance(out, list) else []
        except (ValueError, TypeError):
            return []

    def result(self):
        if self.result_json is None:
            return None
        try:
            return json.loads(self.result_json)
        except (ValueError, TypeError):
            return self.result_json


class AgentAuditEvent(Base):
    """One readable audit row for a task. The audit trail is the
    durable record; the Runs store (``agent_runs``) gets a mirror row
    on terminal completion so run history and audit agree.
    """

    __tablename__ = "agent_audit_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_id: Mapped[str | None] = mapped_column(
        String(32), index=True, nullable=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(128))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class AgentNotification(Base):
    """In-app completion notification (no external service required).
    ``kind``: completed | failed | approval_needed | budget_exceeded |
    circuit_tripped | scheduled.
    """

    __tablename__ = "agent_notifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    task_id: Mapped[str | None] = mapped_column(
        String(32), index=True, nullable=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
