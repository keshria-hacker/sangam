"""Service layer — the only place routes touch task state.

Owns: creation (plan validation + policy normalisation), execution
(state machine + executor + runner + persistence + audit + notification
+ Runs mirror), approval decisions (durable AgentApproval rows), usage
recording with budget enforcement, the pentest-graph constructor, and
the scheduler tick's task half. The scheduler module calls
:meth:`run_task`; routes call everything here.
"""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from ..automations import parse_schedule, validate_automation
from ..hooks import AgentApproval
from .approvals import normalize_policy
from .budgets import BudgetMeter
from .circuit import CircuitBreaker
from .executor import ExecutorConfig, execute_plan
from .models import AgentTask, AgentTaskStep
from .planner import PlanError, plan_summary, validate_plan
from .runner import run_step
from .state_machine import TASK_TRANSITIONS, StateError, transition
from .store import add_audit, add_notification, mirror_agent_run

TRIGGERS = {"manual", "hourly", "daily", "weekly", "cron", "event", "webhook"}


class TaskNotFound(Exception):
    pass


class TaskConflict(Exception):
    pass


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


async def get_task_or_404(db, task_id: str, user_id: str) -> AgentTask:
    task = await db.get(AgentTask, task_id)
    if task is None or task.user_id != user_id:
        raise TaskNotFound(f"task not found: {task_id}")
    return task


async def load_steps(db, task_id: str) -> list[AgentTaskStep]:
    rows = (await db.execute(
        select(AgentTaskStep).where(AgentTaskStep.task_id == task_id)
        .order_by(AgentTaskStep.order))).scalars().all()
    return list(rows)


def _step_dict(row: AgentTaskStep) -> dict:
    return {"name": row.name, "kind": row.kind, "tool": row.tool,
            "args": row.args(), "depends_on": row.depends_on(),
            "status": row.status, "result": row.result(),
            "error": row.error, "attempts": row.attempts,
            "timeout_seconds": (row.args().get("timeout_seconds")
                                if isinstance(row.args(), dict) else None)}


async def create_task(db, user_id: str, payload: dict) -> AgentTask:
    """Create a task + steps. Raises PlanError / ValueError (→ 422)."""
    title = str(payload.get("title") or "").strip()
    if not title:
        raise PlanError("title is required")
    steps_in = payload.get("steps") or []
    order = validate_plan(steps_in)
    policy = normalize_policy(payload.get("approval_policy"))
    trigger = str(payload.get("trigger") or "manual")
    if trigger not in TRIGGERS:
        raise PlanError(f"unknown trigger {trigger!r}")
    if trigger not in ("manual", "event", "webhook"):
        err = validate_automation(trigger, "agent")
        if err:
            raise PlanError(err)
    config = dict(payload.get("config") or {})
    if not isinstance(config, dict):
        raise PlanError("config must be an object")
    next_run = None
    if trigger not in ("manual", "event", "webhook"):
        next_run = parse_schedule(trigger)
    if payload.get("next_run"):
        try:
            next_run = datetime.fromisoformat(
                str(payload["next_run"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise PlanError(f"next_run is not ISO-8601: {exc}") from exc
    task = AgentTask(
        id=_new_id("task"), user_id=user_id, title=title[:200],
        agent_id=(payload.get("agent_id") or None),
        status="pending", approval_policy=policy,
        token_budget=int(payload.get("token_budget") or 0),
        cost_budget_usd=float(payload.get("cost_budget_usd") or 0.0),
        trigger=trigger, enabled=bool(payload.get("enabled", True)),
        next_run=next_run,
        webhook_token=(secrets.token_urlsafe(24) if trigger == "webhook" else None),
        config_json=json.dumps(config), created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC))
    db.add(task)
    by_name = {s["name"]: s for s in steps_in}
    for idx, name in enumerate(order):
        step_in = by_name[name]
        db.add(AgentTaskStep(
            id=_new_id("step"), task_id=task.id, user_id=user_id,
            name=name, kind=step_in.get("kind", "echo"),
            tool=step_in.get("tool"),
            args_json=json.dumps(step_in.get("args") or {}),
            depends_on_json=json.dumps(step_in.get("depends_on") or []),
            order=idx, status="pending"))
    add_audit(db, task.id, user_id, "task.created",
              f"Task created: {title} ({len(order)} steps, policy {policy}, "
              f"trigger {trigger}).")
    await db.commit()
    await db.refresh(task)
    return task


async def _approval_decisions(db, steps: list[AgentTaskStep]) -> dict[str, str | None]:
    decisions: dict[str, str | None] = {}
    for row in steps:
        if row.approval_id:
            approval = await db.get(AgentApproval, row.approval_id)
            decisions[row.name] = approval.status if approval else None
    return decisions


async def run_task(db, task: AgentTask, user_id: str,
                   run_input: dict | None = None) -> dict:
    """Execute a task's pending steps. Raises TaskConflict (→ 409) when
    the task is running, terminal, or blocked on undecided approvals."""
    if task.status == "running":
        raise TaskConflict("task is already running")
    if task.status in ("completed", "cancelled"):
        raise TaskConflict(f"task is {task.status}")
    steps_rows = await load_steps(db, task.id)
    decisions = await _approval_decisions(db, steps_rows)
    pending_approvals = [
        {"step": r.name, "approval_id": r.approval_id}
        for r in steps_rows
        if r.status == "waiting_approval"
        and decisions.get(r.name) not in ("approved", "denied")]
    if task.status == "waiting_approval" and pending_approvals:
        raise TaskConflict("task is waiting on approval decisions")
    # A fully-decided waiting task re-arms via paused, then runs.
    if task.status == "waiting_approval":
        try:
            transition(task.status, "paused", TASK_TRANSITIONS)
            task.status = "paused"
        except StateError as exc:
            raise TaskConflict(str(exc)) from exc
    # Any other state that reaches here resumes from pending steps.
    try:
        transition(task.status, "running", TASK_TRANSITIONS)
    except StateError as exc:
        raise TaskConflict(str(exc)) from exc
    task.status = "running"
    task.error = None
    task.last_run = datetime.now(UTC)
    task.updated_at = datetime.now(UTC)
    await db.commit()
    steps_rows = await load_steps(db, task.id)
    decisions = await _approval_decisions(db, steps_rows)

    config = task.config()
    circuit_cfg = config.get("circuit") or {}
    meter = BudgetMeter(token_budget=int(task.token_budget or 0),
                        cost_budget_usd=float(task.cost_budget_usd or 0.0),
                        tokens_used=int(task.tokens_used or 0),
                        cost_used=float(task.cost_used or 0.0))
    breaker = CircuitBreaker(
        max_consecutive_errors=int(circuit_cfg.get("max_consecutive_errors", 5)),
        max_steps_per_minute=int(circuit_cfg.get("max_steps_per_minute", 30)),
        max_no_progress=int(circuit_cfg.get("max_no_progress", 3)))
    step_dicts = [_step_dict(r) for r in steps_rows]
    ctx = {"db": db, "user_id": user_id, "task": task,
           "task_config": config,
           "workflow_approvals": config.get("workflow_approvals") or {}}
    try:
        updated, summary, events, needs = await execute_plan(
            step_dicts, run_step,
            ExecutorConfig(
                budget=meter, circuit=breaker,
                approval_policy=task.approval_policy,
                approved_tools=list(config.get("approved_tools") or []),
                approval_decisions=decisions),
            run_input=run_input or {}, ctx=ctx)
    except Exception as exc:  # noqa: BLE001 — a run must never hang the task
        task.status = "failed"
        task.error = f"executor error: {exc}"[:500]
        add_audit(db, task.id, user_id, "run.failed", task.error)
        add_notification(db, task.id, user_id, "failed", task.error)
        await db.commit()
        raise

    by_name = {r.name: r for r in steps_rows}
    for step in updated:
        row = by_name[step["name"]]
        row.status = step.get("status", "pending")
        row.result_json = (json.dumps(step["result"])
                           if step.get("result") is not None else None)
        row.error = step.get("error")
        row.attempts = int(step.get("attempts") or 0)
        row.updated_at = datetime.now(UTC)
    for event in events:
        add_audit(db, task.id, user_id, event["action"],
                  f"{event.get('step', '')}: {event.get('detail', '')}".strip(": "))
    # Create durable approval rows for newly gated steps.
    created_approvals: list[dict] = []
    for name in needs:
        row = by_name[name]
        step = next(s for s in updated if s["name"] == name)
        nodes = step.get("approval_nodes") or []
        if nodes:
            # One row per pending workflow approval node; the first is
            # the step's own approval_id, the rest live in task config.
            pending_map = dict(config.get("pending_workflow_approvals") or {})
            for node in nodes:
                approval = AgentApproval(
                    id=_new_id("appr"), run_id=task.id,
                    tool="workflow_approval",
                    args_json=json.dumps({"step": name, "workflow_node": node,
                                          "workflow_run_id":
                                          (step.get("result") or {}).get("workflow_run_id")
                                          if isinstance(step.get("result"), dict) else None}),
                    status="pending", created_at=datetime.now(UTC))
                db.add(approval)
                pending_map[node] = approval.id
                created_approvals.append({"step": name, "approval_id": approval.id,
                                          "workflow_node": node})
            config["pending_workflow_approvals"] = pending_map
            row.approval_id = created_approvals[0]["approval_id"] if created_approvals else row.approval_id
        elif not row.approval_id:
            approval = AgentApproval(
                id=_new_id("appr"), run_id=task.id,
                tool=(row.tool or row.kind),
                args_json=json.dumps(row.args()), status="pending",
                created_at=datetime.now(UTC))
            db.add(approval)
            row.approval_id = approval.id
            created_approvals.append({"step": name, "approval_id": approval.id})
    task.tokens_used = meter.tokens_used
    task.cost_used = meter.cost_used
    # Sticky unknown-usage flag (see store.budget_gauge): once any run
    # reports unknown usage, the gauge stays unknown until a run reports
    # fully known usage.
    config["usage_known"] = bool(config.get("usage_known", True)) and meter.usage_known
    task.set_config(config)
    stopped = summary.get("stopped_reason")
    if needs or stopped == "waiting_approval":
        task.status = "waiting_approval"
        add_notification(db, task.id, user_id, "approval_needed",
                         f"Task '{task.title}' needs approval "
                         f"({len(created_approvals)} pending).")
    elif stopped == "budget_exceeded":
        task.status = "failed"
        task.budget_exceeded = True
        task.error = "budget exceeded"
        add_notification(db, task.id, user_id, "budget_exceeded",
                         f"Task '{task.title}' stopped: budget exceeded.")
    elif stopped == "circuit_tripped":
        task.status = "failed"
        task.circuit_tripped = True
        task.circuit_reason = breaker.tripped_reason
        task.error = breaker.tripped_reason
        add_notification(db, task.id, user_id, "circuit_tripped",
                         f"Task '{task.title}' stopped: {breaker.tripped_reason}")
    elif summary.get("failed"):
        task.status = "failed"
        task.error = "one or more steps failed"
        add_notification(db, task.id, user_id, "failed",
                         f"Task '{task.title}' failed "
                         f"({summary['failed']} step(s) failed).")
    else:
        task.status = "completed"
        add_notification(db, task.id, user_id, "completed",
                         f"Task '{task.title}' completed: "
                         f"{summary['completed']} completed, "
                         f"{summary['skipped']} skipped, "
                         f"{summary['failed']} failed.")
    task.set_config(config)
    task.summary_json = json.dumps(summary)
    task.updated_at = datetime.now(UTC)
    if task.status in ("completed", "failed"):
        mirror_agent_run(db, task, steps_rows, task.status)
    await db.commit()
    await db.refresh(task)
    steps_rows = await load_steps(db, task.id)
    return {"task": task, "steps": steps_rows, "summary": summary,
            "needs_approval": created_approvals}


async def decide_approval(db, task: AgentTask, approval_id: str,
                          approved: bool, reason: str, user_id: str) -> dict:
    """Decide a pending runtime approval. The decision is durable (the
    AgentApproval row) and the step is re-armed: approved → runnable on
    the next run, denied → skipped. A denied workflow approval skips the
    step outright (no workflow re-run); an approved one is recorded in
    task config so the resume re-runs the workflow with __approvals."""
    approval = await db.get(AgentApproval, approval_id)
    if approval is None or approval.run_id != task.id:
        raise TaskNotFound(f"approval not found: {approval_id}")
    if approval.status != "pending":
        raise TaskConflict(f"approval is already {approval.status}")
    approval.status = "approved" if approved else "denied"
    approval.reason = (reason or "")[:1000]
    approval.decided_at = datetime.now(UTC)
    # Best-effort: unblock a concurrently waiting legacy agent loop too.
    try:
        from ..code_agent import resolve_approval

        resolve_approval(approval_id, approved, reason)
    except Exception:  # noqa: BLE001 — the DB row is authoritative
        pass
    try:
        args = json.loads(approval.args_json or "{}")
    except (ValueError, TypeError):
        args = {}
    config = task.config()
    steps_rows = await load_steps(db, task.id)
    target = None
    for row in steps_rows:
        if row.approval_id == approval_id:
            target = row
            break
    if target is None and args.get("step"):
        for row in steps_rows:
            if row.name == args["step"]:
                target = row
                break
    if target is not None:
        if approved:
            # Step stays waiting_approval until the next run resolves it
            # via the decision map; the executor then runs/completes it.
            pass
        else:
            target.status = "skipped"
            target.error = f"approval denied: {reason}" if reason else "approval denied"
            target.updated_at = datetime.now(UTC)
    if args.get("workflow_node"):
        node = args["workflow_node"]
        approvals = dict(config.get("workflow_approvals") or {})
        if approved:
            approvals[node] = "approved"
        else:
            approvals[node] = "denied"
        config["workflow_approvals"] = approvals
        pending_map = dict(config.get("pending_workflow_approvals") or {})
        pending_map.pop(node, None)
        config["pending_workflow_approvals"] = pending_map
    if task.approval_policy == "once" and approved and approval.tool:
        approved_tools = list(config.get("approved_tools") or [])
        if approval.tool not in approved_tools:
            approved_tools.append(approval.tool)
        config["approved_tools"] = approved_tools
    task.set_config(config)
    # Re-arm the task: once every pending approval is decided, a
    # waiting task becomes paused so the user resumes it explicitly.
    remaining = (await db.execute(
        select(AgentApproval).where(
            AgentApproval.run_id == task.id,
            AgentApproval.status == "pending"))).scalars().all()
    if task.status == "waiting_approval" and not remaining:
        try:
            transition(task.status, "paused", TASK_TRANSITIONS)
            task.status = "paused"
        except StateError:
            pass
    task.updated_at = datetime.now(UTC)
    add_audit(db, task.id, user_id,
              "approval.approved" if approved else "approval.denied",
              f"Approval {approval_id} ({approval.tool}): "
              f"{'approved' if approved else 'denied'}"
              + (f" — {reason}" if reason else ""))
    await db.commit()
    return {"approval_id": approval_id, "status": approval.status,
            "task_status": task.status}


async def record_usage(db, task: AgentTask, user_id: str,
                       tokens: int | None, cost_usd: float | None) -> dict:
    """Record observed usage (e.g. from an agent loop's CostMeter) and
    enforce the budget: crossing it stops the task immediately."""
    if task.status in ("completed", "cancelled"):
        raise TaskConflict(f"task is {task.status}")
    meter = BudgetMeter(token_budget=int(task.token_budget or 0),
                        cost_budget_usd=float(task.cost_budget_usd or 0.0),
                        tokens_used=int(task.tokens_used or 0),
                        cost_used=float(task.cost_used or 0.0))
    meter.add(tokens, cost_usd)
    task.tokens_used = meter.tokens_used
    task.cost_used = meter.cost_used
    _cfg = task.config()
    _cfg["usage_known"] = bool(_cfg.get("usage_known", True)) and meter.usage_known
    task.set_config(_cfg)
    task.updated_at = datetime.now(UTC)
    if meter.exceeded():
        try:
            transition(task.status, "failed", TASK_TRANSITIONS)
        except StateError:
            task.status = "failed"
        task.budget_exceeded = True
        task.error = "budget exceeded"
        add_audit(db, task.id, user_id, "run.budget_exceeded",
                  f"Recorded usage pushed the task over budget: "
                  f"{meter.tokens_used} tokens, ${meter.cost_used:.4f}.")
        add_notification(db, task.id, user_id, "budget_exceeded",
                         f"Task '{task.title}' stopped: budget exceeded.")
    else:
        add_audit(db, task.id, user_id, "usage.recorded",
                  f"Usage recorded: +{tokens} tokens, +${cost_usd}.")
    await db.commit()
    await db.refresh(task)
    return {"task": task}


async def set_task_state(db, task: AgentTask, target: str, user_id: str) -> AgentTask:
    """pause / cancel / re-arm, via the state machine (illegal → 409)."""
    try:
        transition(task.status, target, TASK_TRANSITIONS)
    except StateError as exc:
        raise TaskConflict(str(exc)) from exc
    task.status = target
    task.updated_at = datetime.now(UTC)
    add_audit(db, task.id, user_id, f"task.{target}", f"Task {target}.")
    await db.commit()
    await db.refresh(task)
    return task


async def create_security_graph(db, user_id: str, target: str, scope: str) -> dict:
    """Recon → Vuln-hunter → Validator → Reporter as runtime tasks.

    Fits without duplicating the security module: the target must
    already be allowlisted (checked here AND re-checked by every phase
    step), the underlying SecurityRun is created with the security
    module's own row + audit, phases advance with its next_phase, and
    the Reporter step enforces its PASS gate. Active tool execution is
    deliberately NOT duplicated: phase steps record the phase; tools
    still execute only via the Security workspace's own approval.
    """
    from ..security_guardrails import (
        PHASES, SecurityAllowlistTarget, SecurityRun, audit_row,
        check_scope, extract_host,
    )

    if not extract_host(target):
        raise PlanError("target must contain a hostname")
    patterns = (await db.execute(
        select(SecurityAllowlistTarget).where(
            SecurityAllowlistTarget.user_id == user_id))).scalars().all()
    if not check_scope(target, [p.host_pattern for p in patterns]):
        raise TaskConflict(
            "Target is out of scope: add it to the allowlist first. "
            "Runs are refused before any tool fires when no allowlist "
            "pattern matches.")
    run = SecurityRun(
        id=_new_id("sec"), user_id=user_id, target=target, scope=scope or "",
        tool_class="recon", status="pending", phase="recon")
    db.add(run)
    db.add(audit_row(run.id, user_id, "graph.created",
                     f"Pentest graph created via agent runtime: target={target}"))
    config = {"security_run_id": run.id, "security_graph": True}
    task_payload = {
        "title": f"Pentest graph: {target}",
        "approval_policy": "default", "trigger": "manual",
        "config": config,
        "steps": [
            {"name": phase, "kind": "security_phase",
             "args": {"phase": phase, "security_run_id": run.id},
             "depends_on": ([PHASES[i - 1]] if i else [])}
            for i, phase in enumerate(PHASES)
        ],
    }
    task = await create_task(db, user_id, task_payload)
    # create_task committed; the SecurityRun row rides along (same session).
    return {"task": task, "security_run_id": run.id}
