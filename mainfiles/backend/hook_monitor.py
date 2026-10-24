"""
hook_monitor.py — External-agent hook monitor + persistent approval
queue (coucou pattern, no brand assets, no notch clone).

An external agent (Claude Code, Codex, Gemini, ...) runs a small relay
as a hook command. The relay is THIS module's ``relay_event``: it
takes one stdin-JSON event, normalizes it onto canonical event names,
and appends approval requests to Sangam's FIFO approval queue.

Hard rules, copied from the reference behaviour:

- NEVER BLOCK the agent. Fire-and-forget events return at once; only
  a ``PermissionRequest`` waits, and only up to the caller's budget
  (the queue's ``wait_for_decision`` timeout, default 110 s, matching
  the reference decision budget). Connect/queue failures never raise
  into the agent: ``relay_stdin_line`` returns an exit-0 "no opinion"
  reply and the session carries on untouched.
- FIFO queue, ``max_pending = 5``: beyond that, the newest request
  falls back to its terminal (status ``fallback``) instead of queuing
  — the agent re-asks in its own terminal.
- STALE-CLICK GUARD: a decision applies ONLY if the clicked card is
  still the queue head. Deciding a non-head request returns
  ``{"ok": False, "error": "stale"}`` and changes nothing — a stale
  click can never answer the wrong request.
- Field caps: ordinary fields capped at 2,000 chars; Edit/Write diff
  fields at 256 KB each (512 KB total), because the live diff needs
  them. Oversize non-diff fields are truncated; they never poison
  the queue.
- Persistence: when a ``store_path`` is given, the queue is written
  atomically (tmp + rename) on every mutation and reloaded on init,
  so a restart does not drop in-flight approvals. Stored requests
  carry no secrets: only the tool, a capped command/input preview,
  session/project labels — never credentials. The raw token/phone
  path is separate (see ``phone_approval.py``).
- Event normalization: every agent's event names map onto the
  canonical set (Gemini ``BeforeTool`` -> ``PreToolUse``, etc.).

The SQLAlchemy row below follows the lan_pairing pattern (new tables
in new module files, never models.py); routes hydrate the in-memory
queue from these rows when they need DB durability instead of the
JSON store. The queue logic itself never touches the DB, so tests
drive it directly.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

MAX_PENDING = 5
FIELD_CAP = 2000
DIFF_FIELD_CAP = 256 * 1024
DIFF_TOTAL_CAP = 512 * 1024
DECISION_BUDGET_S = 110.0

# Canonical event names. Other agents' names map onto these.
CANONICAL_EVENTS = {"SessionStart", "UserPromptSubmit", "PreToolUse",
                    "PostToolUse", "Stop", "SessionEnd", "SubagentStart",
                    "SubagentStop", "PermissionRequest"}
EVENT_ALIASES = {
    "BeforeTool": "PreToolUse",
    "AfterTool": "PostToolUse",
    "PreTool": "PreToolUse",
    "PostTool": "PostToolUse",
    "ToolUse": "PreToolUse",
    "Permission": "PermissionRequest",
    "ApprovalRequest": "PermissionRequest",
}

DIFF_FIELDS = {"old_text", "new_text", "diff", "file_diff", "content"}


def _now() -> datetime:
    return datetime.now(UTC)


class HookApprovalRow(Base):
    """Durable row for one queued external-agent approval (lan_pairing
    pattern: the row is the fallback a fresh process hydrates from).
    No secrets are stored here — only capped previews."""

    __tablename__ = "hook_approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), default="")
    agent: Mapped[str] = mapped_column(String(64), default="")
    tool: Mapped[str] = mapped_column(String(128), default="")
    command_preview: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    decision: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


def normalize_event_name(name: str) -> str:
    """Map an agent's event name onto the canonical set; unknown
    names pass through unchanged (never rejected — an unknown event
    is a no-opinion event, not an error)."""
    name = (name or "").strip()
    return EVENT_ALIASES.get(name, name)


def cap_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Cap every string field; diff fields get the large cap, others
    the small one, with the diff total capped at 512 KB."""
    out: dict[str, Any] = {}
    diff_total = 0
    for key, value in (payload or {}).items():
        if not isinstance(value, str):
            out[key] = value
            continue
        if key in DIFF_FIELDS:
            allowed = min(DIFF_FIELD_CAP, max(0, DIFF_TOTAL_CAP - diff_total))
            out[key] = value[:allowed]
            diff_total += len(out[key])
        else:
            out[key] = value[:FIELD_CAP]
    return out


@dataclass
class QueuedApproval:
    id: str
    session_id: str
    agent: str
    tool: str
    command_preview: str
    status: str = "pending"  # pending | decided | fallback | expired
    decision: str = ""       # allow | deny (only when decided)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "session_id": self.session_id, "agent": self.agent,
                "tool": self.tool, "command_preview": self.command_preview,
                "status": self.status, "decision": self.decision,
                "created_at": self.created_at}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QueuedApproval":
        return cls(id=str(data["id"]), session_id=data.get("session_id", ""),
                   agent=data.get("agent", ""), tool=data.get("tool", ""),
                   command_preview=data.get("command_preview", ""),
                   status=data.get("status", "pending"),
                   decision=data.get("decision", ""),
                   created_at=float(data.get("created_at", time.time())))


class ApprovalQueue:
    """FIFO queue with max-pending fallback + stale-click guard.

    ``head()`` is the request on the card. ``decide()`` refuses any
    request that is not the head. Overflow requests are NOT queued:
    they return with status ``fallback`` so the agent re-asks in its
    own terminal.
    """

    def __init__(self, store_path: str | Path | None = None):
        self.store_path = Path(store_path) if store_path else None
        self._queue: list[QueuedApproval] = []
        if self.store_path and self.store_path.exists():
            try:
                raw = json.loads(self.store_path.read_text(encoding="utf-8"))
                self._queue = [QueuedApproval.from_dict(item) for item in raw]
            except (json.JSONDecodeError, OSError, KeyError, TypeError):
                self._queue = []

    def _persist(self) -> None:
        if not self.store_path:
            return
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.store_path.with_suffix(self.store_path.suffix + ".tmp")
        tmp.write_text(json.dumps([q.to_dict() for q in self._queue], indent=2),
                       encoding="utf-8")
        tmp.replace(self.store_path)

    def pending(self) -> list[QueuedApproval]:
        return [q for q in self._queue if q.status == "pending"]

    def head(self) -> QueuedApproval | None:
        pending = self.pending()
        return pending[0] if pending else None

    def enqueue(self, session_id: str, agent: str, tool: str,
                command_preview: str) -> QueuedApproval:
        if len(self.pending()) >= MAX_PENDING:
            overflow = QueuedApproval(
                id=f"hq-{uuid.uuid4().hex[:12]}", session_id=session_id, agent=agent,
                tool=tool, command_preview=(command_preview or "")[:FIELD_CAP],
                status="fallback")
            self._queue.append(overflow)
            self._persist()
            return overflow
        item = QueuedApproval(
            id=f"hq-{uuid.uuid4().hex[:12]}", session_id=session_id, agent=agent,
            tool=tool, command_preview=(command_preview or "")[:FIELD_CAP])
        self._queue.append(item)
        self._persist()
        return item

    def decide(self, approval_id: str, decision: str) -> dict[str, Any]:
        """Decide the HEAD request only. Stale clicks are refused and
        change nothing. ``decision`` must be 'allow' or 'deny'."""
        if decision not in ("allow", "deny"):
            return {"ok": False, "error": "decision must be 'allow' or 'deny'"}
        head = self.head()
        if head is None:
            return {"ok": False, "error": "queue empty"}
        if head.id != approval_id:
            return {"ok": False, "error": "stale",
                    "detail": "The clicked card is no longer the queue head; "
                              "the decision was not applied."}
        head.status = "decided"
        head.decision = decision
        self._persist()
        return {"ok": True, "id": head.id, "decision": decision}

    def get(self, approval_id: str) -> QueuedApproval | None:
        for item in self._queue:
            if item.id == approval_id:
                return item
        return None


def relay_event(event: dict[str, Any], queue: ApprovalQueue | None) -> dict[str, Any]:
    """Relay one hook event. Never raises, never blocks: when the
    queue is unavailable (Sangam down) the reply is exit-0
    'no-opinion' and the agent carries on untouched. Only
    PermissionRequest events create queue entries; everything else is
    acknowledged and dropped (the queue is an approval surface, not a
    telemetry sink)."""
    try:
        if queue is None:
            return {"decision": "no-opinion", "reason": "sangam unavailable"}
        raw_event = (event or {}).get("event") or (event or {}).get("hook_event_name") or ""
        name = normalize_event_name(str(raw_event))
        if name != "PermissionRequest":
            return {"decision": "no-opinion", "event": name}
        payload = cap_fields((event or {}).get("payload") or (event or {}).get("input") or {})
        tool = str(payload.get("tool") or payload.get("tool_name") or "")
        command = str(payload.get("command") or payload.get("input") or payload.get("command_preview") or "")
        agent = str((event or {}).get("coucou_agent") or (event or {}).get("agent") or "")
        # Agent tags are validated like the reference contract: lowercase
        # alnum-dash, 1..24 chars; anything else is dropped to "".
        import re as _re
        if agent and not _re.fullmatch(r"[a-z0-9-]{1,24}", agent):
            agent = ""
        item = queue.enqueue(session_id=str((event or {}).get("session_id") or ""),
                             agent=agent, tool=tool, command_preview=command[:FIELD_CAP])
        if item.status == "fallback":
            return {"decision": "no-opinion", "reason": "queue full; re-ask in terminal",
                    "approval_id": item.id}
        return {"decision": "pending", "approval_id": item.id,
                "detail": "Queued for approval; the agent waits up to the decision budget."}
    except Exception:
        # Never block the agent on a relay failure.
        return {"decision": "no-opinion", "reason": "relay error"}


def relay_stdin_line(line: str, queue: ApprovalQueue | None) -> dict[str, Any]:
    """Parse one stdin JSON line and relay it. Unparseable input is
    still exit-0 no-opinion — a malformed hook line must never kill
    the agent that invoked it."""
    try:
        event = json.loads(line)
        if not isinstance(event, dict):
            return {"decision": "no-opinion", "reason": "not a JSON object"}
        return relay_event(event, queue)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"decision": "no-opinion", "reason": "unparseable hook payload"}


if __name__ == "__main__":
    # Hook-command entry point: read stdin JSON lines, relay each to
    # the approval queue, print one JSON reply per line, exit 0 always.
    # The queue store path comes from SANGAM_HOOK_QUEUE_PATH (unset =
    # memory-only queue for this process). Never exits non-zero: a
    # hook failure must never kill the agent that invoked it.
    import os as _os
    import sys as _sys

    _store = _os.environ.get("SANGAM_HOOK_QUEUE_PATH") or None
    _queue: ApprovalQueue | None = None
    try:
        _queue = ApprovalQueue(_store)
    except Exception:
        _queue = None
    for _line in _sys.stdin:
        _line = _line.strip()
        if not _line:
            continue
        print(json.dumps(relay_stdin_line(_line, _queue)), flush=True)
    _sys.exit(0)
