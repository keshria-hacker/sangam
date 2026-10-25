"""agent_runtime/approval.py — async approval channel (Batch 10).

claw-code's portable lesson (out-of-context notification routing) +
coucou's ambient approval UX, on top of Sangam's existing approval
backend — NOT a replacement for it:

* The per-run approval policy (default/automatic/always_ask), the
  risk-tier policy (blacklist wins), and the durable DB approval rows
  in ``hooks.py`` are unchanged. This module adds the *waiting shape*.
* Old shape (blocking): the SSE stream stalls on a gated call until
  the user answers in chat.
* New shape (async): :func:`defer` parks the risky call in the tray
  with a capped preview; the run continues with independent calls
  only (see ``loop.independent_calls``); the decision arrives later
  from chat OR from a paired LAN device through the tray endpoint.
  A deferred call is never executed before its decision, and a
  decision applies exactly once — a second decision is refused.

The tray store here is in-memory per process (the "Needs you" tray in
Work). Durable approval rows remain the audit log: callers that have
a DB session should still record the row via ``hooks.record_approval_row``
exactly as ``code_agent.run_agent`` does today; this channel does not
invent its own audit trail.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DeferredApproval:
    """One risky call waiting in the tray."""

    id: str
    run_id: str
    tool: str
    args_preview: str
    status: str = "pending"  # pending | approved | denied | expired
    decision: str = ""
    reason: str = ""
    source: str = ""  # "chat" | "paired-device" | "" (undecided)
    call_id: str = ""  # tool-call id, so the run matches the decision back
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"id": self.id, "run_id": self.run_id, "tool": self.tool,
                "args_preview": self.args_preview, "status": self.status,
                "decision": self.decision, "reason": self.reason,
                "source": self.source, "created_at": self.created_at}


class AsyncApprovalChannel:
    """Tray for deferred approvals with exactly-once decisions."""

    def __init__(self) -> None:
        self._items: dict[str, DeferredApproval] = {}

    def defer(self, run_id: str, tool: str, args: dict | None = None,
              call_id: str | None = None) -> DeferredApproval:
        """Park a risky call. ``args`` are preview-capped, never stored raw
        beyond 500 chars (previews only — the full args stay with the run)."""
        preview = "" if args is None else str(args)[:500]
        item = DeferredApproval(
            id=f"def-{uuid.uuid4().hex[:12]}", run_id=run_id or "",
            tool=tool, args_preview=preview, call_id=call_id or "")
        self._items[item.id] = item
        return item

    def pending(self, run_id: str | None = None) -> list[DeferredApproval]:
        items = [i for i in self._items.values() if i.status == "pending"]
        if run_id is not None:
            items = [i for i in items if i.run_id == run_id]
        return items

    def get(self, approval_id: str) -> DeferredApproval | None:
        return self._items.get(approval_id)

    def decide(self, approval_id: str, approved: bool,
               source: str = "chat", reason: str = "") -> dict:
        """Apply a decision exactly once. Returns {ok, ...} or {ok: False, error}."""
        item = self._items.get(approval_id)
        if item is None:
            return {"ok": False, "error": f"unknown deferred approval: {approval_id!r}"}
        if item.status != "pending":
            return {"ok": False, "error": f"approval already {item.status}; decisions apply once"}
        if source not in ("chat", "paired-device"):
            return {"ok": False, "error": "source must be 'chat' or 'paired-device'"}
        item.status = "approved" if approved else "denied"
        item.decision = "allow" if approved else "deny"
        item.source = source
        item.reason = (reason or "")[:500]
        return {"ok": True, "id": item.id, "status": item.status,
                "decision": item.decision, "source": source}

    def tray(self) -> list[dict]:
        """The 'Needs you' tray: pending items first, then decided."""
        pending = [i.to_dict() for i in self.pending()]
        decided = [i.to_dict() for i in self._items.values() if i.status != "pending"]
        return pending + decided


# Process-wide tray (the Work destination polls this via the API).
CHANNEL = AsyncApprovalChannel()
