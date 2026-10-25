"""agent_runtime/loop.py — pi + odysseus loop primitives (Batch 10).

Pure, dependency-light building blocks the existing ``run_agent`` loop
can adopt incrementally. Nothing here calls a model.

pi imports
----------
* :class:`SteeringQueue` — user messages injected mid-run. ``steer()``
  appends; ``drain()`` returns and clears them in order; ``abort()``
  sets a flag the loop checks between steps (abort semantics: the run
  stops at the next step boundary, it never kills a tool mid-call —
  a mid-call kill would leave files half-written).
* :func:`plan_tool_calls` — parallel by default; a call is sequential
  when it declares it reads another call's output (``reads`` lists the
  ids it depends on). Returns ordered groups; each group runs in
  parallel, groups run in order. A dependency on an unknown id is an
  error, never silently dropped (odysseus no-substitution discipline).
* :func:`compact` / :class:`BranchStore` — compaction emits a structured
  summary plus the read/modified file lists, and a branch can be
  resumed later (session-tree navigation). Summaries are deterministic
  templates over the supplied transcript slice — no model call, so no
  invented content; the summary quotes only supplied text.

odysseus imports
----------------
* :class:`TurnContract` — frozen at run start: ``required <= offered
  <= executable``. ``check(tool)`` returns ``("ok", ...)``,
  ``("unavailable", ...)`` (required but not offered/executable: stop
  and say so, never substitute another tool), or ``("denied", ...)``
  (offered but not executable: policy refusal). The frozen snapshot is
  a plain dict copy, so later registry changes cannot widen a turn.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------- steering
class SteeringQueue:
    """Mid-run user messages + abort flag (pi steering)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._messages: list[str] = []
        self._aborted = False
        self._abort_reason = ""

    def steer(self, message: str) -> dict:
        """Inject a user message into a running run. Returns its position."""
        text = (message or "").strip()
        if not text:
            raise ValueError("steering message must not be empty")
        with self._lock:
            self._messages.append(text)
            return {"queued": len(self._messages), "message": text}

    def drain(self) -> list[str]:
        """Return queued steering messages in order and clear the queue."""
        with self._lock:
            out = list(self._messages)
            self._messages.clear()
            return out

    def pending(self) -> list[str]:
        with self._lock:
            return list(self._messages)

    def abort(self, reason: str = "") -> None:
        with self._lock:
            self._aborted = True
            self._abort_reason = reason or "aborted by user"

    @property
    def aborted(self) -> bool:
        with self._lock:
            return self._aborted

    @property
    def abort_reason(self) -> str:
        with self._lock:
            return self._abort_reason

    def check_abort(self) -> None:
        """Raise at a step boundary when aborted (loop checks this)."""
        if self.aborted:
            raise RunAborted(self.abort_reason)


class RunAborted(RuntimeError):
    """Raised at a step boundary when the user aborted the run."""


# ------------------------------------------------------- tool-call planning
@dataclass
class PlannedCall:
    """One model tool call with its dependency declaration."""

    id: str
    name: str
    args: dict = field(default_factory=dict)
    reads: list[str] = field(default_factory=list)  # ids this call reads

    @property
    def sequential(self) -> bool:
        return bool(self.reads)


def plan_tool_calls(calls: list[dict | PlannedCall]) -> list[list[PlannedCall]]:
    """Group tool calls into parallel groups honouring ``reads`` edges.

    * No ``reads`` -> every call lands in the first group (parallel).
    * A call with ``reads`` lands in a later group than every call it
      reads (sequential when a tool declares it reads another's output).
    * Duplicate ids or a dependency on an unknown id raise ValueError
      (never silently dropped); a dependency cycle raises ValueError.

    Returns a list of groups; groups run in order, calls inside one
    group may run in parallel.
    """
    planned: list[PlannedCall] = []
    seen: set[str] = set()
    for raw in calls or []:
        if isinstance(raw, PlannedCall):
            call = raw
        else:
            call = PlannedCall(
                id=str(raw.get("id", "")),
                name=str(raw.get("name", "")),
                args=dict(raw.get("args") or {}),
                reads=[str(r) for r in (raw.get("reads") or [])],
            )
        if not call.id:
            raise ValueError("tool call without an id cannot be planned")
        if call.id in seen:
            raise ValueError(f"duplicate tool call id: {call.id!r}")
        seen.add(call.id)
        planned.append(call)
    by_id = {c.id: c for c in planned}
    for call in planned:
        for dep in call.reads:
            if dep not in by_id:
                raise ValueError(
                    f"tool call {call.id!r} reads unknown call {dep!r}: "
                    "refusing to run with a dropped dependency")
            if dep == call.id:
                raise ValueError(f"tool call {call.id!r} reads itself")
    # Longest-path layering (Kahn-style): layer = 1 + max(layer of deps).
    layer: dict[str, int] = {}

    def depth(call_id: str, visiting: set[str]) -> int:
        if call_id in layer:
            return layer[call_id]
        if call_id in visiting:
            raise ValueError(f"tool-call dependency cycle involving {call_id!r}")
        visiting.add(call_id)
        deps = by_id[call_id].reads
        value = 1 + max((depth(d, visiting) for d in deps), default=0)
        visiting.discard(call_id)
        layer[call_id] = value
        return value

    for call in planned:
        depth(call.id, set())
    groups: dict[int, list[PlannedCall]] = {}
    for call in planned:
        groups.setdefault(layer[call.id], []).append(call)
    return [groups[k] for k in sorted(groups)]


def independent_calls(calls: list[dict | PlannedCall],
                      blocked_ids: set[str]) -> list[PlannedCall]:
    """Calls that may proceed while ``blocked_ids`` wait (async approval).

    A call is independent when neither it nor anything it reads is
    blocked. Used by the async approval channel: the run continues with
    exactly these calls while a risky call waits in the tray.
    """
    planned = [c if isinstance(c, PlannedCall) else PlannedCall(
        id=str(c.get("id", "")), name=str(c.get("name", "")),
        args=dict(c.get("args") or {}),
        reads=[str(r) for r in (c.get("reads") or [])]) for c in (calls or [])]
    blocked = set(blocked_ids or set())
    # Transitive: a call reading a blocked call is itself blocked.
    changed = True
    while changed:
        changed = False
        for call in planned:
            if call.id not in blocked and any(d in blocked for d in call.reads):
                blocked.add(call.id)
                changed = True
    return [c for c in planned if c.id not in blocked]


# ------------------------------------------------------------ turn contract
@dataclass
class TurnContract:
    """Frozen per-turn tool contract (odysseus AGENT_TURN_CONTRACT).

    Invariant enforced at construction: required <= offered <=
    executable. ``offered`` is what the turn may use; ``executable``
    is what the runtime can actually run (tool exists + policy allows).
    """

    required: list[str] = field(default_factory=list)
    offered: list[str] = field(default_factory=list)
    executable: list[str] = field(default_factory=list)
    tool_schemas: dict[str, dict] = field(default_factory=dict)  # frozen copies

    def __post_init__(self) -> None:
        self.required = list(self.required)
        self.offered = list(self.offered)
        self.executable = list(self.executable)
        self.tool_schemas = {k: dict(v) for k, v in (self.tool_schemas or {}).items()}
        req, off, exe = set(self.required), set(self.offered), set(self.executable)
        if not req <= off:
            raise ValueError(
                f"contract violated at freeze: required not subset of offered: "
                f"{sorted(req - off)}")
        if not off <= exe:
            raise ValueError(
                f"contract violated at freeze: offered not subset of executable: "
                f"{sorted(off - exe)}")

    def check(self, tool: str) -> tuple[str, str]:
        """Return (status, detail) for one tool call in this turn.

        * ``ok`` — the tool is offered and executable.
        * ``unavailable`` — required by the task but not in the frozen
          set: the run must STOP and say so, never substitute.
        * ``denied`` — not offered/executable in this turn.
        """
        if tool in self.executable and tool in self.offered:
            return "ok", ""
        if tool in self.required:
            return ("unavailable",
                    f"Tool {tool!r} is required by this task but is not "
                    "available in this turn's frozen tool set; refusing to "
                    "substitute a different tool.")
        return "denied", f"Tool {tool!r} is not offered in this turn."

    def to_dict(self) -> dict:
        return {"required": self.required, "offered": self.offered,
                "executable": self.executable,
                "tools": sorted(self.tool_schemas)}


# ---------------------------------------------------------------- compaction
_STOPWORDS = {"the", "and", "for", "with", "this", "that", "from", "into",
              "your", "you", "are", "was", "were", "have", "has", "will",
              "about", "after", "before", "when", "what", "which", "then"}


@dataclass
class CompactionSummary:
    """Structured compaction output (pi branch summarisation)."""

    branch_id: str
    parent_branch_id: str | None
    summary: str
    read_files: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    message_count: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {"branch_id": self.branch_id,
                "parent_branch_id": self.parent_branch_id,
                "summary": self.summary,
                "read_files": self.read_files,
                "modified_files": self.modified_files,
                "message_count": self.message_count,
                "created_at": self.created_at}


def compact(messages: list[dict], read_files: list[str] | None = None,
            modified_files: list[str] | None = None,
            parent_branch_id: str | None = None,
            max_chars: int = 2000) -> CompactionSummary:
    """Compact a transcript slice into a structured, quotable summary.

    Deterministic and honest: the summary lists the task (first user
    message, truncated), the last assistant conclusion (truncated), and
    counts — it never invents outcomes. File lists are deduplicated,
    sorted, and capped at 200 entries each.
    """
    msgs = list(messages or [])
    user_msgs = [str(m.get("content", "")) for m in msgs if m.get("role") == "user"]
    asst_msgs = [str(m.get("content", "")) for m in msgs
                 if m.get("role") == "assistant" and str(m.get("content", "")).strip()]
    task = (user_msgs[0][:300] if user_msgs else "(no user task recorded)")
    conclusion = (asst_msgs[-1][:300] if asst_msgs else "(no conclusion yet)")
    tool_msgs = sum(1 for m in msgs if m.get("role") == "tool")
    summary = (
        f"Task: {task}\n"
        f"Messages compacted: {len(msgs)} "
        f"({len(user_msgs)} user, {len(asst_msgs)} assistant, {tool_msgs} tool)\n"
        f"Files read: {len(read_files or [])}; files modified: {len(modified_files or [])}\n"
        f"Latest conclusion: {conclusion}"
    )[:max_chars]
    return CompactionSummary(
        branch_id=f"br-{uuid.uuid4().hex[:12]}",
        parent_branch_id=parent_branch_id,
        summary=summary,
        read_files=sorted(set(read_files or []))[:200],
        modified_files=sorted(set(modified_files or []))[:200],
        message_count=len(msgs))


class BranchStore:
    """In-memory session tree: compactions keyed by branch id.

    A branch resumes by id; resuming from a compaction creates a child
    branch whose parent is the resumed one (session-tree navigation).
    This store is intentionally in-memory for a single run — durable
    session persistence stays with the existing Runs centre.
    """

    def __init__(self) -> None:
        self._branches: dict[str, CompactionSummary] = {}

    def save(self, summary: CompactionSummary) -> CompactionSummary:
        self._branches[summary.branch_id] = summary
        return summary

    def get(self, branch_id: str) -> CompactionSummary | None:
        return self._branches.get(branch_id)

    def list_branches(self) -> list[dict]:
        return [b.to_dict() for b in self._branches.values()]

    def resume(self, branch_id: str, new_messages: list[dict] | None = None,
               read_files: list[str] | None = None,
               modified_files: list[str] | None = None) -> CompactionSummary:
        """Resume a branch: compact new messages as its child branch."""
        parent = self._branches.get(branch_id)
        if parent is None:
            raise ValueError(f"unknown branch: {branch_id!r}")
        merged_read = list(parent.read_files) + list(read_files or [])
        merged_mod = list(parent.modified_files) + list(modified_files or [])
        child = compact(new_messages or [], read_files=merged_read,
                        modified_files=merged_mod, parent_branch_id=branch_id)
        child.summary = (f"Resumed from branch {branch_id}.\n"
                         f"Parent summary:\n{parent.summary}\n---\n{child.summary}")
        self._branches[child.branch_id] = child
        return child


# ------------------------------------------------------- slow-tool promotion
def slow_tool_promotion(elapsed_s: float, threshold_s: float = 60.0) -> dict:
    """Odysseus background-job promotion rule for a long tool call.

    Returns {promote: bool, reason}: calls over the budget should be
    promoted to a background job surfaced in the Runs feed instead of
    blocking the turn. No job is created here — the caller owns jobs.
    """
    if elapsed_s >= threshold_s:
        return {"promote": True,
                "reason": f"tool call ran {elapsed_s:.0f}s (>= {threshold_s:.0f}s budget); "
                          "promote to a background job in the Runs feed"}
    return {"promote": False, "reason": ""}
