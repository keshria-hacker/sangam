"""Task planner — validate a plan (steps + dependencies) before it runs.

A plan is a list of step dicts: ``{name, kind, tool?, args?, depends_on?}``.
Validation is pure (no DB, no LLM): unique names, known kinds, dependency
references that exist, and no cycles (Kahn topological sort, same approach
as the workflow engine). An invalid plan is rejected at creation time
(422), never mid-run.
"""

from __future__ import annotations

from typing import Any


class PlanError(ValueError):
    """Plan validation failure; message is safe to return to the client."""


STEP_KINDS = {
    "echo",  # deterministic passthrough (tests, demos, dry runs)
    "text",  # template render via the workflow engine
    "transform",  # upper/lower/reverse/trim/title via the workflow engine
    "tool",  # one tool call, approval-gated per policy (see approvals.py)
    "workflow",  # run an existing DAG workflow row (incl. approval nodes)
    "approval",  # human-approval step: pauses the task until decided
    "security_phase",  # one Recon/Vuln-hunter/Validator/Reporter phase step
    "agent",  # code_agent loop (needs a configured model; fails clearly if none)
}


def validate_plan(steps: Any) -> list[str]:
    """Validate ``steps``; return step names in topological order.

    Raises PlanError on: non-list/empty plans, missing/duplicate names,
    unknown kinds, a tool step without a tool, unknown dependencies,
    or a dependency cycle.
    """
    if not isinstance(steps, list) or not steps:
        raise PlanError("plan.steps must be a non-empty list")
    by_name: dict[str, dict] = {}
    for step in steps:
        if not isinstance(step, dict) or not step.get("name"):
            raise PlanError("every plan step needs a name")
        name = str(step["name"])
        if name in by_name:
            raise PlanError(f"duplicate step name: {name}")
        if step.get("kind", "echo") not in STEP_KINDS:
            raise PlanError(f"step {name}: unknown kind {step.get('kind')!r}")
        if step.get("kind") == "tool" and not step.get("tool"):
            raise PlanError(f"step {name}: tool steps need a tool name")
        if step.get("kind") == "security_phase" and step.get("args", {}).get("phase") not in (
                "recon", "vuln-hunter", "validator", "reporter"):
            raise PlanError(
                f"step {name}: security_phase needs args.phase in "
                "recon/vuln-hunter/validator/reporter")
        by_name[name] = step
    indegree: dict[str, int] = {name: 0 for name in by_name}
    outgoing: dict[str, list[str]] = {name: [] for name in by_name}
    for name, step in by_name.items():
        deps = step.get("depends_on") or []
        if not isinstance(deps, list):
            raise PlanError(f"step {name}: depends_on must be a list")
        for dep in deps:
            if dep not in by_name:
                raise PlanError(f"step {name}: depends on unknown step {dep!r}")
            if dep == name:
                raise PlanError(f"step {name}: depends on itself")
            outgoing[dep].append(name)
            indegree[name] += 1
    queue = [name for name, deg in indegree.items() if deg == 0]
    order: list[str] = []
    while queue:
        name = queue.pop(0)
        order.append(name)
        for nxt in outgoing[name]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if len(order) != len(by_name):
        raise PlanError("plan contains a dependency cycle")
    return order


def plan_summary(steps: list[dict]) -> dict:
    """Counts for a plan (used by the task board before any run)."""
    kinds: dict[str, int] = {}
    for step in steps or []:
        kinds[str(step.get("kind", "echo"))] += 1
    return {"total": len(steps or []), "kinds": kinds}
