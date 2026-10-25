"""Default step runner — dispatches each step kind to a REAL handler.

Wraps, never duplicates:

* ``text`` / ``transform`` — the workflow engine's single-node execution
  (:func:`backend.workflows.execute_definition`);
* ``tool`` read-only tools — :mod:`backend.tools.builtin` handlers;
* ``tool`` sensitive/other tools — :func:`backend.code_agent._execute_tool`
  (hook layer + risk-tier policy inside, so a second gate applies);
* ``workflow`` — :func:`backend.workflows.run_workflow_row`, including
  the engine's human-approval nodes (a workflow that hits an approval
  node returns ``waiting_approval`` instead of proceeding);
* ``security_phase`` — :mod:`backend.security_guardrails` helpers
  (allowlist scope re-check, passive recon, phase order, PASS gate);
* ``agent`` — :func:`backend.code_agent.run_agent` with the task's
  budget wired as ``max_cost_usd`` and real provider usage reported.

Usage is reported only when a handler reports it (agent loop usage,
or nothing). Text/tool/workflow steps report ``tokens=None`` — unknown,
never estimated.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select


def _step_args(step: dict) -> dict:
    args = step.get("args") or {}
    return args if isinstance(args, dict) else {}


async def _run_single_workflow_node(node: dict, run_input: dict) -> Any:
    from ..workflows import execute_definition

    outputs, _results, error = await execute_definition(
        {"nodes": [node], "edges": []}, run_input)
    if error:
        raise ValueError(error)
    return outputs.get(node["id"])


async def run_step(step: dict, ctx: dict) -> dict:
    """Run one step. Returns {output, tokens, cost_usd, waiting_approval,
    approval_nodes}. Raises on failure (the executor records it)."""
    kind = step.get("kind", "echo")
    args = _step_args(step)
    run_input = ctx.get("input") or {}
    outputs = ctx.get("outputs") or {}
    if kind == "echo":
        return {"output": args.get("text", ""), "tokens": None, "cost_usd": None}
    if kind == "text":
        template = args.get("template", args.get("text", ""))
        out = await _run_single_workflow_node(
            {"id": "t", "type": "text", "config": {"template": template}}, run_input)
        # Template placeholders reference {{nodes.<step>}}; the workflow
        # engine only knows its own node outputs, so re-render names the
        # task outputs explicitly when the template mentions a step.
        if isinstance(out, str):
            from ..workflows import render_template

            out = render_template(template, run_input, outputs)
        return {"output": out, "tokens": None, "cost_usd": None}
    if kind == "transform":
        prev = args.get("text")
        if prev is None and outputs:
            prev = list(outputs.values())[-1]
        out = await _run_single_workflow_node(
            {"id": "t", "type": "transform",
             "config": {"op": args.get("op", "trim")}},
            {"text": "" if prev is None else str(prev)})
        return {"output": out, "tokens": None, "cost_usd": None}
    if kind == "tool":
        return await _run_tool_step(step, args, ctx)
    if kind == "workflow":
        return await _run_workflow_step(step, args, ctx)
    if kind == "security_phase":
        return await _run_security_step(step, args, ctx)
    if kind == "agent":
        return await _run_agent_step(step, args, ctx)
    if kind == "approval":
        raise ValueError("approval steps are decided by humans, never executed")
    raise ValueError(f"unknown step kind: {kind!r}")


async def _run_tool_step(step: dict, args: dict, ctx: dict) -> dict:
    tool = step.get("tool") or ""
    if tool in ("web_search", "code_map"):
        from ..tools.builtin import code_map_handler, web_search_handler

        if tool == "web_search":
            out = await web_search_handler(
                str(args.get("query", "")), int(args.get("max_results", 5) or 5))
        else:
            out = await code_map_handler(
                str(args.get("query", "")), str(args.get("target", "")))
        return {"output": out, "tokens": None, "cost_usd": None}
    # Sensitive / other tools go through the agent engine's executor:
    # hooks + risk-tier policy run again inside, so runtime approval is
    # necessary but never sufficient for a blacklisted call.
    from ..code_agent import _execute_tool

    out = await _execute_tool(tool, dict(args))
    if isinstance(out, dict) and out.get("error"):
        raise ValueError(str(out["error"])[:500])
    return {"output": out, "tokens": None, "cost_usd": None}


async def _run_workflow_step(step: dict, args: dict, ctx: dict) -> dict:
    from ..models import Workflow
    from ..workflows import run_workflow_row

    db = ctx.get("db")
    user_id = ctx.get("user_id")
    workflow_id = args.get("workflow_id") or ""
    if db is None or not workflow_id:
        raise ValueError("workflow steps need a workflow_id and a database session")
    wf = await db.get(Workflow, workflow_id)
    if wf is None or wf.user_id != user_id:
        raise ValueError(f"workflow not found: {workflow_id}")
    wf_input = dict(ctx.get("input") or {})
    if isinstance(args.get("input"), dict):
        wf_input.update(args["input"])
    approvals = dict(ctx.get("workflow_approvals") or {})
    if approvals:
        wf_input["__approvals"] = approvals
    run = await run_workflow_row(wf, db, wf_input)
    node_results = {}
    try:
        node_results = json.loads(run.node_results_json or "{}")
    except (ValueError, TypeError):
        node_results = {}
    if run.status == "waiting_approval":
        pending_nodes = [nid for nid, res in node_results.items()
                         if isinstance(res, dict) and res.get("status") == "failed"
                         and str(res.get("error") or "").startswith("approval_required:")]
        return {"output": json.loads(run.output_json or "{}"),
                "tokens": None, "cost_usd": None,
                "waiting_approval": True, "approval_nodes": pending_nodes,
                "workflow_run_id": run.id}
    if run.status != "succeeded":
        raise ValueError(f"workflow run {run.status}: {run.error or ''}"[:500])
    return {"output": json.loads(run.output_json or "{}"),
            "tokens": None, "cost_usd": None, "workflow_run_id": run.id}


async def _run_security_step(step: dict, args: dict, ctx: dict) -> dict:
    """One pentest-graph phase. Reuses the security module's own rules:

    * scope is re-checked against the CURRENT allowlist before anything
      runs (deleting a target between graph creation and this step
      blocks the step, exactly like the security approve endpoint);
    * recon executes passive recon only (never probing/exploitation);
    * vuln-hunter / validator advance the phase — active tool execution
      stays behind the Security workspace's own per-run approval and is
      NOT duplicated here; the step output says so explicitly;
    * reporter enforces the same PASS gate as /security/runs/{id}/report:
      every finding must be validated PASS, otherwise the step fails
      listing the blockers.
    """
    from ..security_guardrails import (
        PHASES, SecurityAllowlistTarget, SecurityFinding, SecurityRun,
        audit_row, check_scope, next_phase, run_passive_recon,
    )

    db = ctx.get("db")
    user_id = ctx.get("user_id")
    phase = args.get("phase") or ""
    run_id = args.get("security_run_id") or (ctx.get("task_config") or {}).get("security_run_id") or ""
    if db is None or not run_id:
        raise ValueError("security_phase steps need a security_run_id")
    run = await db.get(SecurityRun, run_id)
    if run is None or run.user_id != user_id:
        raise ValueError(f"security run not found: {run_id}")
    patterns = (await db.execute(
        select(SecurityAllowlistTarget).where(
            SecurityAllowlistTarget.user_id == user_id))).scalars().all()
    if not check_scope(run.target, [p.host_pattern for p in patterns]):
        raise ValueError(
            "Target is out of scope at step time: the allowlist no longer "
            "covers it. Execution refused.")
    if phase not in PHASES:
        raise ValueError(f"unknown security phase: {phase}")
    if run.phase != phase:
        raise ValueError(
            f"security run is in phase {run.phase!r}, not {phase!r}; "
            "phases advance in order Recon -> Vuln-hunter -> Validator -> Reporter")
    if phase == "recon":
        result = run_passive_recon(run.target)
        db.add(audit_row(run.id, user_id, "graph.recon",
                         f"Pentest graph recon (passive only): target={run.target}"))
    elif phase == "reporter":
        rows = (await db.execute(
            select(SecurityFinding).where(SecurityFinding.run_id == run.id)
        )).scalars().all()
        blocking = [r for r in rows
                    if not (r.status == "validated" and r.validation_verdict == "PASS")]
        if blocking:
            raise ValueError(
                "Report refused: not every finding is validated PASS: "
                + ", ".join(r.title for r in blocking))
        result = {"report": "PASS gate satisfied",
                  "findings": [{"title": r.title, "severity": r.severity,
                                "validation_verdict": r.validation_verdict} for r in rows]}
        db.add(audit_row(run.id, user_id, "graph.report",
                         "Pentest graph report: PASS gate satisfied."))
    else:
        result = {
            "phase": phase,
            "note": ("Phase advanced only. Active tool execution is NOT run "
                     "by the graph step; it stays behind the Security "
                     "workspace's own per-run approval (see /security/runs)."),
        }
        db.add(audit_row(run.id, user_id, f"graph.{phase}",
                         f"Pentest graph phase {phase} recorded."))
    nxt = next_phase(phase)
    if nxt is not None:
        run.phase = nxt
    await db.commit()
    return {"output": result, "tokens": None, "cost_usd": None}


async def _run_agent_step(step: dict, args: dict, ctx: dict) -> dict:
    from ..code_agent import run_agent
    from ..llm import default_model_id

    db = ctx.get("db")
    if db is None:
        raise ValueError("agent steps need a database session")
    model = args.get("model") or await default_model_id(db)
    if not model:
        raise ValueError("agent step: no model configured")
    task = ctx.get("task")
    max_cost = float(task.cost_budget_usd) if task is not None and task.cost_budget_usd else 0.0
    policy = {"deny": "default", "once": "default", "always": "always_ask"}.get(
        (task.approval_policy if task is not None else "default"), "default")
    usage: dict[str, int | None] = {"tokens": None}
    answer = ""
    async for event in run_agent(
            args.get("task") or args.get("text") or "", model, db,
            tool_names=args.get("tools"),
            max_iterations=int(args.get("max_iterations", 5) or 5),
            approval_policy=policy, max_cost_usd=max_cost,
            on_usage=lambda total: usage.__setitem__("tokens", total)):
        if event.kind in ("answer", "done"):
            answer = event.content or answer
        if event.kind == "error":
            raise ValueError(event.content[:500])
    return {"output": answer, "tokens": usage["tokens"], "cost_usd": None}
