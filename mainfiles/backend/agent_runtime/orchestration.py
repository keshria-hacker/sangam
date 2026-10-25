"""agent_runtime/orchestration.py — one run-shape engine (Batch 10).

Converges the three parallel orchestration systems onto single,
testable primitives. No model calls here — the caller supplies a
``review`` callable / task runner; this module owns the shape.

* :class:`TaskGraph` — superpowers §12 + mattpocock §14 subagent-per-
  task: tasks with blocking edges, a ready frontier (tasks whose deps
  are done), fresh context per task (the caller creates it — the graph
  never reuses a task's context for another task), a review gate per
  task, and a branch review at the end. ``four_stop_rule`` encodes
  superpowers' only-4-stop-reasons contract (irreversible/destructive,
  security-sensitive, side-effect outside the worktree, plan broken).
* Hive mode (munder-difflin §11): :func:`drain_inbox` (an agent drains
  its inbox before finishing) and :func:`escalate_critical_only`
  (routine traffic is resolved by the coordinator; only destructive /
  spend / scope / conflict items reach the human tray).
* Orca §10 typed nodes: :class:`AskNode` (blocking question with a
  timeout) and :class:`GateNode` (human-or-rule decision before an edge
  proceeds); :func:`handoff_to_worktree` moves ownership to a fresh
  worktree + fresh context (not a subagent call in the same context).
* Overmind §6: :func:`propose_from_eval` — after a cassette/replay run,
  PROPOSE (never silently apply) a model/prompt change with the eval
  delta as evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


# ------------------------------------------------------------ task graph
FOUR_STOP_REASONS = (
    "irreversible-or-destructive",
    "security-sensitive",
    "side-effect-outside-worktree",
    "plan-too-broken-to-proceed",
)


def four_stop_rule(reason: str) -> dict:
    """superpowers 'rulings, not stalls': only 4 reasons may stop a run.

    Anything else must be recorded as a decision and the run continues.
    Returns {stop: bool, reason, ruling}.
    """
    if reason in FOUR_STOP_REASONS:
        return {"stop": True, "reason": reason,
                "ruling": f"Run stops: {reason}."}
    return {"stop": False, "reason": reason,
            "ruling": f"Recorded as a decision, run continues: {reason}."}


@dataclass
class FlowTask:
    id: str
    title: str
    depends_on: list[str] = field(default_factory=list)
    status: str = "pending"  # pending | ready | running | review | done | failed
    review: dict | None = None  # per-task review gate outcome


class TaskGraph:
    """Ticket graph with blocking edges + ready-frontier execution."""

    def __init__(self, tasks: list[dict | FlowTask]) -> None:
        self.tasks: dict[str, FlowTask] = {}
        for raw in tasks or []:
            task = raw if isinstance(raw, FlowTask) else FlowTask(
                id=str(raw.get("id", "")), title=str(raw.get("title", "")),
                depends_on=[str(d) for d in (raw.get("depends_on") or [])])
            if not task.id:
                raise ValueError("flow task without an id")
            if task.id in self.tasks:
                raise ValueError(f"duplicate flow task id: {task.id!r}")
            self.tasks[task.id] = task
        for task in self.tasks.values():
            for dep in task.depends_on:
                if dep not in self.tasks:
                    raise ValueError(
                        f"task {task.id!r} depends on unknown task {dep!r}")
                if dep == task.id:
                    raise ValueError(f"task {task.id!r} depends on itself")
        self._check_cycles()

    def _check_cycles(self) -> None:
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in done:
                return
            if task_id in visiting:
                raise ValueError(f"ticket-graph cycle involving {task_id!r}")
            visiting.add(task_id)
            for dep in self.tasks[task_id].depends_on:
                visit(dep)
            visiting.discard(task_id)
            done.add(task_id)

        for task_id in self.tasks:
            visit(task_id)

    def frontier(self) -> list[FlowTask]:
        """Ready frontier: pending tasks whose blockers are all done."""
        return [t for t in self.tasks.values()
                if t.status == "pending"
                and all(self.tasks[d].status == "done" for d in t.depends_on)]

    def execution_order(self) -> list[str]:
        """Deterministic topological order (frontier order, stable)."""
        order: list[str] = []
        statuses = {tid: t.status for tid, t in self.tasks.items()}
        pending = set(self.tasks)
        while pending:
            ready = sorted(tid for tid in pending
                           if all(statuses[d] == "done" for d in
                                  self.tasks[tid].depends_on))
            if not ready:
                raise ValueError("ticket-graph cycle: no ready task remains")
            for tid in ready:
                order.append(tid)
                statuses[tid] = "done"
                pending.discard(tid)
        return order

    def mark(self, task_id: str, status: str) -> FlowTask:
        task = self.tasks.get(task_id)
        if task is None:
            raise ValueError(f"unknown task: {task_id!r}")
        if status not in ("pending", "ready", "running", "review", "done", "failed"):
            raise ValueError(f"unknown task status: {status!r}")
        task.status = status
        return task

    def review_task(self, task_id: str, review: dict) -> FlowTask:
        """Per-task review gate: a task reaches done only via review.

        ``review`` must carry ``verdict`` in {"approve", "request-changes"}.
        On request-changes the task returns to pending with the review
        attached (fresh context on retry — the caller re-runs it).
        """
        task = self.tasks.get(task_id)
        if task is None:
            raise ValueError(f"unknown task: {task_id!r}")
        verdict = (review or {}).get("verdict")
        if verdict not in ("approve", "request-changes"):
            raise ValueError("review verdict must be 'approve' or 'request-changes'")
        task.review = dict(review)
        task.status = "done" if verdict == "approve" else "pending"
        return task

    def branch_review(self) -> dict:
        """Final branch review: only meaningful when every task is done."""
        unfinished = sorted(tid for tid, t in self.tasks.items()
                            if t.status != "done")
        return {"complete": not unfinished, "unfinished": unfinished,
                "tasks": len(self.tasks),
                "done": sum(1 for t in self.tasks.values() if t.status == "done")}

    def to_dict(self) -> dict:
        return {"tasks": [{"id": t.id, "title": t.title,
                           "depends_on": t.depends_on, "status": t.status,
                           "review": t.review} for t in self.tasks.values()],
                "frontier": [t.id for t in self.frontier()]}


# ------------------------------------------------------------------- hive
CRITICAL_KEYWORDS = ("destructive", "delete", "drop", "spend", "cost",
                     "payment", "scope", "conflict", "secret", "credential",
                     "production", "deploy")


def drain_inbox(inbox: list[dict]) -> dict:
    """Hive inbox-drain: an agent finishes only after draining its inbox.

    Returns {drained: [...ids in order...], remaining: [...]}. ``inbox``
    items are dicts with at least ``id``; items without an id are
    reported as remaining (never silently dropped).
    """
    drained: list[str] = []
    remaining: list[dict] = []
    for item in inbox or []:
        item_id = (item or {}).get("id")
        if item_id:
            drained.append(str(item_id))
        else:
            remaining.append(item)
    return {"drained": drained, "remaining": remaining,
            "finished": not remaining}


def escalate_critical_only(items: list[dict]) -> dict:
    """God-orchestrator escalation contract (munder-difflin).

    Routine items are resolved by the coordinator (``handled``);
    only items matching destructive / spend / scope / conflict /
    secret / production keywords escalate to the human tray.
    """
    handled: list[dict] = []
    escalated: list[dict] = []
    for item in items or []:
        text = f"{item.get('title', '')} {item.get('body', '')}".lower()
        if any(k in text for k in CRITICAL_KEYWORDS):
            escalated.append(item)
        else:
            handled.append(item)
    return {"handled": handled, "escalated": escalated}


# ------------------------------------------------------------ ask/gate nodes
@dataclass
class AskNode:
    """Orca blocking ask: coordinator/worker question with a timeout."""

    id: str
    question: str
    timeout_s: float = 300.0
    answer: str | None = None

    def answer_question(self, answer: str) -> dict:
        if not (answer or "").strip():
            raise ValueError("ask answer must not be empty")
        self.answer = answer.strip()
        return {"id": self.id, "answered": True, "answer": self.answer}

    def to_dict(self) -> dict:
        return {"id": self.id, "question": self.question,
                "timeout_s": self.timeout_s, "answered": self.answer is not None,
                "answer": self.answer}


@dataclass
class GateNode:
    """Orca decision gate: a DAG edge proceeds only on an explicit pass."""

    id: str
    rule: str  # human-readable rule, e.g. "human approves the plan"
    decision: str | None = None  # None | "pass" | "block"
    decided_by: str = ""  # "human" | "rule"

    def decide(self, decision: str, decided_by: str = "human") -> dict:
        if decision not in ("pass", "block"):
            raise ValueError("gate decision must be 'pass' or 'block'")
        if decided_by not in ("human", "rule"):
            raise ValueError("gate decided_by must be 'human' or 'rule'")
        self.decision = decision
        self.decided_by = decided_by
        return {"id": self.id, "decision": decision, "decided_by": decided_by}

    @property
    def open(self) -> bool:
        return self.decision == "pass"


def handoff_to_worktree(repo: str | Path, parent_dir: str | Path,
                        name: str, branch: str | None = None) -> dict:
    """Orca ownership handoff: move work to a FRESH worktree + context.

    This is not a subagent call in the same context: the caller gets a
    new worktree path and must start a fresh context there. Raises
    WorktreeError (surfaced, not hidden) when git cannot create it.
    """
    from ..worktrees import create_worktree
    wt = create_worktree(repo, parent_dir, name, branch=branch)
    return {"worktree": str(wt.path), "branch": branch or "",
            "fresh_context_required": True,
            "detail": "Ownership moved: continue only in the new worktree "
                      "with a fresh context; the old context must not "
                      "write to the original checkout for this task."}


# --------------------------------------------------------- optimise from evals
def propose_from_eval(eval_before: dict, eval_after: dict,
                      change: dict) -> dict:
    """Overmind optimisation loop, proposal-only (never silently applied).

    ``eval_before``/``eval_after`` are {score, cases, passed} style
    summaries from a cassette/replay run; ``change`` describes the
    proposed model/prompt change. Returns the proposal with the eval
    delta as evidence and ``applied: False`` — application is a human
    act (Settings), never this function's side effect.
    """
    def _score(e: dict) -> float:
        try:
            return float(e.get("score"))
        except (TypeError, ValueError):
            passed, cases = e.get("passed"), e.get("cases")
            if isinstance(passed, (int, float)) and cases:
                return float(passed) / float(cases)
            return 0.0

    before, after = _score(eval_before or {}), _score(eval_after or {})
    return {"applied": False,
            "change": dict(change or {}),
            "eval_before": dict(eval_before or {}),
            "eval_after": dict(eval_after or {}),
            "delta": after - before,
            "recommendation": ("adopt" if after > before else
                               "reject — no measured improvement"),
            "evidence": f"eval delta {after - before:+.3f} "
                        f"({before:.3f} -> {after:.3f})"}
