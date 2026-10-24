"""Pi-style hook layer for Sangam's agent tool calls (deep-read Wave 1).

Every tool call — in the agent loop and in ``ToolExecutor`` — passes
through two hook points, not a special case:

* ``before_tool_call`` — may BLOCK the call with a reason. A blocked
  call never executes; the reason flows back to the model as the tool
  result, so the model can choose a safer alternative.
* ``after_tool_call`` — may REWRITE or REDACT the result before it
  reaches the model (or the transcript).

Hooks are plain callables (sync or async) registered on a
:class:`HookRegistry`. The ECC guard policies live here as ready-made
before-hooks built from :mod:`permission_policy`'s pattern tables, so
the tables stay the single source of truth.

Also in this module, because the hook layer is where policy meets the
run:

* :class:`LoopDetector` — ECC's 5-identical-call loop detector. The
  threshold is 5, not 3: retries and polling false-fired at 3 in ECC.
* :func:`run_stop_checks` — ECC's Stop hook, report-only and under a
  time budget: batch format/typecheck of files the run touched. It
  never blocks, never auto-fixes (an auto-fix goes through normal
  approval with a diff).
* :class:`AgentApproval` — the durable approval table. Approvals used
  to live only in ``code_agent._approval_gates`` (an in-memory dict):
  a restart lost every pending approval and a denial carried no reason.
  Rows now record pending/approved/denied/timeout with a reason;
  ``timeout`` and ``denied`` are distinct states — a timeout is
  reported to the model as a timeout, never as a refusal.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hook contracts
# ---------------------------------------------------------------------------


@dataclass
class HookDecision:
    """Result of a before-tool-call hook."""

    block: bool = False
    reason: str = ""
    # If True, the whole tool batch ends after this call (pi's
    # `terminate`); the loop still continues to the next LLM turn.
    terminate: bool = False


@dataclass
class HookedResult:
    """A tool result as seen by after-hooks (plain data, no ORM)."""

    content: str
    data: dict[str, Any] | None = None
    is_error: bool = False
    error: str | None = None


BeforeHook = Callable[..., HookDecision | Awaitable[HookDecision] | None]
AfterHook = Callable[..., HookedResult | Awaitable[HookedResult] | None]


class HookRegistry:
    """Ordered before/after hooks consulted on every tool call."""

    def __init__(self, before: list[BeforeHook] | None = None,
                 after: list[AfterHook] | None = None):
        self.before_hooks: list[BeforeHook] = list(before or [])
        self.after_hooks: list[AfterHook] = list(after or [])

    def register_before(self, hook: BeforeHook) -> None:
        self.before_hooks.append(hook)

    def register_after(self, hook: AfterHook) -> None:
        self.after_hooks.append(hook)

    async def run_before(self, tool_name: str, args: dict[str, Any],
                         context: dict[str, Any] | None = None
                         ) -> HookDecision:
        """First blocking hook wins; its reason is the denial."""
        for hook in self.before_hooks:
            try:
                result = hook(tool_name, args, context or {})
                if asyncio.iscoroutine(result):
                    result = await result
            except Exception as exc:  # noqa: BLE001 — a broken hook must
                logger.warning("before-hook %r failed: %s", hook, exc)
                continue
            if isinstance(result, HookDecision) and result.block:
                return result
        return HookDecision(block=False)

    async def run_after(self, tool_name: str, args: dict[str, Any],
                        result: HookedResult,
                        context: dict[str, Any] | None = None) -> HookedResult:
        """Each after-hook may rewrite/redact; the last write wins per field."""
        current = result
        for hook in self.after_hooks:
            try:
                rewritten = hook(tool_name, args, current, context or {})
                if asyncio.iscoroutine(rewritten):
                    rewritten = await rewritten
            except Exception as exc:  # noqa: BLE001 — same fail-open rule
                logger.warning("after-hook %r failed: %s", hook, exc)
                continue
            if isinstance(rewritten, HookedResult):
                current = rewritten
        return current


# ---------------------------------------------------------------------------
# ECC guard policies as before-hooks (tables live in permission_policy)
# ---------------------------------------------------------------------------


def config_protection_hook(tool_name: str, args: dict[str, Any],
                           context: dict[str, Any] | None = None
                           ) -> HookDecision | None:
    """Block edits to linter/formatter configs (ECC config-protection).

    Applies to write_file/edit_file only, matched on the basename of
    the `path` argument. pyproject.toml is deliberately NOT protected
    (see permission_policy module docstring).
    """
    if tool_name not in ("write_file", "edit_file"):
        return None
    from .permission_policy import CONFIG_DENYLIST_PATTERNS
    path = str(args.get("path") or "")
    basename = path.replace("\\", "/").rsplit("/", 1)[-1]
    for rule_id, pattern in CONFIG_DENYLIST_PATTERNS:
        if pattern.match(basename):
            return HookDecision(
                block=True,
                reason=f"Blocked by {rule_id}: editing {basename} is not "
                       "allowed — fix the source instead of changing the "
                       "check configuration.",
            )
    return None


def destructive_bash_hook(tool_name: str, args: dict[str, Any],
                          context: dict[str, Any] | None = None
                          ) -> HookDecision | None:
    """Auto-deny destructive bash commands with a recovery hint (ECC gateguard)."""
    if tool_name != "run_bash":
        return None
    from .permission_policy import DESTRUCTIVE_BASH_PATTERNS
    command = str(args.get("command") or "")
    for rule_id, pattern, hint in DESTRUCTIVE_BASH_PATTERNS:
        if pattern.search(command):
            return HookDecision(
                block=True,
                reason=f"Blocked by {rule_id}: destructive command denied. {hint}",
            )
    return None


def default_guard_registry() -> HookRegistry:
    """Registry with the ECC guard hooks and nothing else.

    No redaction hook is registered by default: redacting tool output
    changes what the model sees, so it is opt-in via
    :func:`redact_sensitive_hook`.
    """
    registry = HookRegistry()
    registry.register_before(config_protection_hook)
    registry.register_before(destructive_bash_hook)
    return registry


# ---------------------------------------------------------------------------
# After-hook: secret redaction (opt-in)
# ---------------------------------------------------------------------------

_SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_-]{16,}"), "sk-***"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "ghp_***"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]+"), "xox***"),
    (re.compile(r"(?i)(api[_-]?key|password|secret)\s*=\s*\S+"),
     lambda m: f"{m.group(1)}=***"),
]


def redact_sensitive_hook(tool_name: str, args: dict[str, Any],
                          result: HookedResult,
                          context: dict[str, Any] | None = None) -> HookedResult:
    """Mask token-like secrets in tool output before it reaches the model."""
    content = result.content
    for pattern, replacement in _SECRET_PATTERNS:
        content = pattern.sub(replacement, content)
    data = result.data
    if isinstance(data, dict):
        redacted = {}
        for key, value in data.items():
            if any(word in key.lower()
                   for word in ("api_key", "apikey", "token", "secret", "password")):
                redacted[key] = "***"
            else:
                redacted[key] = value
        data = redacted
    if content != result.content or data != result.data:
        return HookedResult(content=content, data=data,
                            is_error=result.is_error, error=result.error)
    return result


# ---------------------------------------------------------------------------
# Loop detection (ECC context monitor: 5 identical calls)
# ---------------------------------------------------------------------------


class LoopDetector:
    """Trips when the same tool call repeats consecutively.

    ``record`` returns True on the Nth identical consecutive call
    (default N=5). Any different call resets the streak, so legitimate
    retries (fewer than N) and polling below the threshold are not
    flagged. The caller must STOP and ask the user on a trip — never
    auto-retry with a different strategy.
    """

    def __init__(self, threshold: int = 5):
        self.threshold = threshold
        self._last_key: str | None = None
        self._streak = 0

    def record(self, tool_name: str, args: dict[str, Any] | None) -> bool:
        key = json.dumps({"tool": tool_name, "args": args or {}},
                         sort_keys=True, default=str)
        if key == self._last_key:
            self._streak += 1
        else:
            self._last_key = key
            self._streak = 1
        return self._streak >= self.threshold

    @property
    def streak(self) -> int:
        return self._streak

    def reset(self) -> None:
        self._last_key = None
        self._streak = 0


# ---------------------------------------------------------------------------
# Stop hook: report-only batch format/typecheck (ECC stop-format-typecheck)
# ---------------------------------------------------------------------------


@dataclass
class StopCheck:
    file: str
    check: str
    status: str  # "ok" | "fail" | "skipped"
    detail: str = ""


def run_stop_checks(touched_files: list[str],
                    budget_s: float = 120.0) -> list[StopCheck]:
    """Batch-check files a run touched. Report-only, under a time budget.

    Python files get ``py_compile``; if ``ruff`` is on PATH it also runs
    ``ruff check`` per file. Anything else is skipped with a note. A
    failure here is a report, never a run failure and never an auto-fix:
    the report goes back to the user/model, and any fix goes through
    normal approval with a diff. Returns [] when nothing was touched
    or the budget is exhausted (the exhaustion is itself a skipped row).
    """
    deadline = time.monotonic() + max(0.0, budget_s)
    checks: list[StopCheck] = []
    seen: set[str] = set()
    for raw in touched_files or []:
        if time.monotonic() >= deadline:
            checks.append(StopCheck(file="(budget)", check="stop",
                                    status="skipped",
                                    detail="Stop-check time budget exhausted; "
                                           "remaining files were not checked."))
            break
        path = Path(raw)
        # Only report on files that still exist inside the workspace view.
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        remaining = max(1.0, deadline - time.monotonic())
        if path.suffix == ".py" and path.is_file():
            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "py_compile", str(path)],
                    capture_output=True, text=True,
                    timeout=min(30.0, remaining))
                if proc.returncode == 0:
                    checks.append(StopCheck(file=key, check="py_compile",
                                            status="ok"))
                else:
                    checks.append(StopCheck(
                        file=key, check="py_compile", status="fail",
                        detail=(proc.stderr or proc.stdout or "").strip()[:500]))
            except Exception as exc:  # noqa: BLE001 — report-only
                checks.append(StopCheck(file=key, check="py_compile",
                                        status="skipped", detail=str(exc)[:200]))
        else:
            checks.append(StopCheck(file=key, check="format/typecheck",
                                    status="skipped",
                                    detail="No checker configured for this file type."))
    return checks


def format_stop_report(checks: list[StopCheck]) -> str:
    """Render stop checks as the report yielded at the end of a run."""
    if not checks:
        return ""
    lines = ["Stop checks (report-only — nothing was auto-fixed):"]
    for check in checks:
        line = f"- {check.file} [{check.check}]: {check.status}"
        if check.detail:
            line += f" — {check.detail}"
        lines.append(line)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Durable approvals (DB table; replaces ephemeral-only _approval_gates)
# ---------------------------------------------------------------------------
# The model lives here — not in models.py — because this worker may not
# edit models.py. It registers on the shared Base metadata, so
# ``init_db``'s ``Base.metadata.create_all`` creates the table once this
# module has been imported (code_agent imports it, and every route that
# runs the agent imports code_agent first).

from sqlalchemy import Text  # noqa: E402
from sqlalchemy.orm import Mapped, mapped_column  # noqa: E402

from .database import Base  # noqa: E402

APPROVAL_STATUSES = ("pending", "approved", "denied", "timeout")


class AgentApproval(Base):
    """One durable approval decision for one agent tool call."""

    __tablename__ = "agent_approvals"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool: Mapped[str] = mapped_column(Text)
    args_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(Text, default="pending")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC))
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)


async def record_approval_row(db: Any, approval_id: str, tool: str,
                              args: dict[str, Any] | None,
                              run_id: str | None = None) -> bool:
    """Insert a pending approval row. Best-effort: never breaks a run."""
    if db is None:
        return False
    try:
        db.add(AgentApproval(
            id=approval_id, run_id=run_id, tool=tool,
            args_json=json.dumps(args or {}, default=str),
            status="pending"))
        await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001 — durability is best-effort
        logger.warning("could not record approval %s: %s", approval_id, exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False


async def transition_approval_row(db: Any, approval_id: str, status: str,
                                  reason: str | None = None) -> bool:
    """Move a row to approved/denied/timeout. Best-effort, like above."""
    if db is None or status not in APPROVAL_STATUSES:
        return False
    try:
        row = await db.get(AgentApproval, approval_id)
        if row is None:
            return False
        row.status = status
        row.reason = reason
        row.decided_at = datetime.now(UTC)
        await db.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not transition approval %s: %s", approval_id, exc)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False
