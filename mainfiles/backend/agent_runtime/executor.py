"""Executor — runs a validated plan step by step, in topo order.

Pure orchestration over plain step dicts (the service layer persists
them); the actual work happens in the injected ``runner`` callable, so
unit tests can prove gating/budget/circuit behaviour with a test runner
while production runs the real runner (:mod:`backend.agent_runtime.runner`).

Guarantees:

* Resume-safe: steps already ``completed``/``skipped`` are never re-run;
  a run only executes ``pending`` steps (plus ``waiting_approval`` steps
  whose decision is now ``approved``).
* Dependency failure propagates: a step whose dependency did not
  complete is marked ``skipped`` (counted in the final summary), never
  executed on stale input.
* Approval gate blocks: a step that needs approval and has no approved
  decision is marked ``waiting_approval``, the runner is NEVER called
  for it, and the run pauses (later steps stay ``pending``).
* Budget enforced: the run stops the moment the meter reports exceeded
  (before a step, or right after a step's usage is recorded). Remaining
  steps stay ``pending`` so a budget raise + resume can continue.
* Circuit breaker enforced: on trip the run stops immediately.
* A denied sensitive action is ``skipped`` (not failed, not executed);
  independent steps still run, dependents of the skipped step skip too.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .approvals import decide_for_step
from .budgets import BudgetExceeded, BudgetMeter
from .circuit import CircuitBreaker
from .planner import validate_plan

RunnerResult = dict[str, Any]
Runner = Callable[[dict, dict], Awaitable[RunnerResult]]


@dataclass
class ExecutorConfig:
    budget: BudgetMeter = field(default_factory=BudgetMeter)
    circuit: CircuitBreaker = field(default_factory=CircuitBreaker)
    approval_policy: str = "default"
    approved_tools: list[str] = field(default_factory=list)
    # step name -> durable decision: approved | denied | pending | None
    approval_decisions: dict[str, str | None] = field(default_factory=dict)
    step_timeout_seconds: float = 120.0


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return str(value)


async def execute_plan(
    steps: list[dict],
    runner: Runner,
    config: ExecutorConfig,
    run_input: dict | None = None,
    ctx: dict | None = None,
) -> tuple[list[dict], dict, list[dict], list[str]]:
    """Execute ``steps`` in topo order.

    Returns (steps, summary, audit_events, needs_approval_names).
    ``summary`` counts completed/failed/skipped/pending/waiting_approval
    plus ``stopped_reason`` (None | budget_exceeded | circuit_tripped |
    waiting_approval). ``audit_events`` are plain dicts the service
    persists; ``needs_approval_names`` are steps for which the service
    must create a durable AgentApproval row (if none exists yet).
    """
    run_input = run_input or {}
    ctx = ctx or {}
    order = validate_plan(steps)
    by_name = {s["name"]: s for s in steps}
    outputs: dict[str, Any] = {}
    for step in steps:  # resume: completed outputs feed later steps
        if step.get("status") == "completed" and "result" in step:
            outputs[step["name"]] = step["result"]
    events: list[dict] = []
    needs_approval: list[str] = []
    stopped_reason: str | None = None

    def summary() -> dict:
        counts = {"completed": 0, "failed": 0, "skipped": 0,
                  "pending": 0, "waiting_approval": 0}
        for step in steps:
            status = step.get("status", "pending")
            if status in counts:
                counts[status] += 1
            else:  # running should never survive a run; count as pending
                counts["pending"] += 1
        counts["total"] = len(steps)
        counts["stopped_reason"] = stopped_reason
        return counts

    for name in order:
        step = by_name[name]
        status = step.get("status", "pending")
        if status in ("completed", "skipped", "failed"):
            continue
        if stopped_reason is not None:
            break
        # Dependency gate: every dependency must have completed.
        failed_deps = [d for d in (step.get("depends_on") or [])
                       if by_name[d].get("status") != "completed"]
        if failed_deps:
            step["status"] = "skipped"
            step["error"] = ("skipped: dependency not completed: "
                             + ", ".join(failed_deps))
            events.append({"action": "step.skipped", "step": name,
                           "detail": step["error"]})
            continue
        # Budget gate (before the step).
        try:
            config.budget.check()
        except BudgetExceeded as exc:
            stopped_reason = "budget_exceeded"
            events.append({"action": "run.budget_exceeded", "step": name,
                           "detail": str(exc)})
            break
        if config.circuit.tripped:
            stopped_reason = "circuit_tripped"
            events.append({"action": "run.circuit_tripped", "step": name,
                           "detail": config.circuit.tripped_reason or ""})
            break
        kind = step.get("kind", "echo")
        # Human-approval step: never runs a tool; it IS the gate.
        if kind == "approval":
            decision = config.approval_decisions.get(name)
            if decision == "approved":
                step["status"] = "completed"
                step["result"] = {"approval": "approved",
                                  "note": (step.get("args") or {}).get("note", "")}
                outputs[name] = step["result"]
                events.append({"action": "step.approved", "step": name,
                               "detail": "Human-approval step approved."})
                continue
            if decision == "denied":
                step["status"] = "skipped"
                step["error"] = "approval denied"
                events.append({"action": "step.denied", "step": name,
                               "detail": "Human-approval step denied."})
                continue
            step["status"] = "waiting_approval"
            if name not in needs_approval:
                needs_approval.append(name)
            stopped_reason = "waiting_approval"
            events.append({"action": "approval.requested", "step": name,
                           "detail": "Human approval required before continuing."})
            break
        # Tool approval gate: the runner is never called for ask/deny.
        if kind == "tool":
            decision, reason = decide_for_step(
                step.get("tool"), step.get("args") or {},
                task_policy=config.approval_policy,
                approved_tools=config.approved_tools,
                existing_decision=config.approval_decisions.get(name))
            if decision == "deny":
                step["status"] = "skipped"
                step["error"] = reason
                events.append({"action": "step.denied", "step": name,
                               "detail": reason})
                continue
            if decision == "ask":
                step["status"] = "waiting_approval"
                if name not in needs_approval:
                    needs_approval.append(name)
                stopped_reason = "waiting_approval"
                events.append({"action": "approval.requested", "step": name,
                               "detail": reason})
                break
        # Execute.
        config.circuit.record_step_start()
        if config.circuit.tripped:
            stopped_reason = "circuit_tripped"
            events.append({"action": "run.circuit_tripped", "step": name,
                           "detail": config.circuit.tripped_reason or ""})
            break
        step["status"] = "running"
        step["attempts"] = int(step.get("attempts") or 0) + 1
        step_ctx = {**ctx, "input": run_input, "outputs": dict(outputs)}
        try:
            result = await asyncio.wait_for(
                runner(step, step_ctx),
                timeout=float(step.get("timeout_seconds")
                              or config.step_timeout_seconds))
        except Exception as exc:  # noqa: BLE001 — step failure is data
            step["status"] = "failed"
            step["error"] = str(exc)[:500]
            config.circuit.record_error()
            events.append({"action": "step.failed", "step": name,
                           "detail": step["error"]})
            if config.circuit.tripped:
                stopped_reason = "circuit_tripped"
                events.append({"action": "run.circuit_tripped", "step": name,
                               "detail": config.circuit.tripped_reason or ""})
            continue
        if isinstance(result, dict) and result.get("waiting_approval"):
            # Runner-level gate (e.g. a workflow approval node waiting).
            step["status"] = "waiting_approval"
            step["result"] = result.get("output")
            step["approval_nodes"] = result.get("approval_nodes") or []
            if name not in needs_approval:
                needs_approval.append(name)
            stopped_reason = "waiting_approval"
            events.append({"action": "approval.requested", "step": name,
                           "detail": "Downstream approval required: "
                           + ", ".join(result.get("approval_nodes") or [])})
            break
        output = result.get("output") if isinstance(result, dict) else result
        step["status"] = "completed"
        step["result"] = output
        step["error"] = None
        outputs[name] = output
        config.circuit.record_success(_as_text(output))
        if isinstance(result, dict):
            config.budget.add(result.get("tokens"), result.get("cost_usd"))
        events.append({"action": "step.completed", "step": name,
                       "detail": f"Step completed ({step['attempts']} attempt(s))."})
        if config.budget.exceeded():
            stopped_reason = "budget_exceeded"
            events.append({"action": "run.budget_exceeded", "step": name,
                           "detail": "Budget exceeded after this step's usage."})
            break
        if config.circuit.tripped:
            stopped_reason = "circuit_tripped"
            events.append({"action": "run.circuit_tripped", "step": name,
                           "detail": config.circuit.tripped_reason or ""})
            break
    return steps, summary(), events, needs_approval
