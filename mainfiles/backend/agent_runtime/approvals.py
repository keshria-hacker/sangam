"""Approval gate — EXTENDS the existing approval system, never forks it.

Policy evaluation order (identical to the agent loop's rule, extended
with per-task policies):

1. Blacklist first: :class:`backend.permission_policy.RiskPolicy` denies
   destructive calls (e.g. ``rm -rf /``) under EVERY policy, including
   ``automatic`` — an approval can never authorise a blacklisted call.
2. Per-task policy (stored on the task, normalised here):
   ``default`` — delegate to the existing policy (sensitive tools ask;
   :data:`backend.permission_policy.DEFAULT_APPROVAL_TOOLS`);
   ``once`` — the first sensitive call for a tool asks; once approved,
   that tool is recorded on the task and later calls run;
   ``always`` — every sensitive call asks;
   ``deny`` — sensitive calls are refused outright, no approval row.
3. A recorded decision for the step (the durable
   :class:`backend.hooks.AgentApproval` row) overrides the ask: approved
   runs, denied skips, pending still waits.

Aliases from the agent-loop vocabulary are normalised: ``automatic``
behaves like ``default`` with asking disabled (blacklist still denies),
``always_ask`` behaves like ``always``.
"""

from __future__ import annotations

from typing import Any

from ..permission_policy import DEFAULT_APPROVAL_TOOLS, DEFAULT_POLICY

TASK_POLICIES = {"default", "once", "always", "deny"}
_POLICY_ALIASES = {"automatic": "default", "auto": "default", "never": "default",
                   "always_ask": "always", "ask_all": "always"}


def normalize_policy(policy: str | None) -> str:
    """Normalise a task approval policy; raises ValueError if unknown."""
    key = (policy or "default").strip().lower()
    key = _POLICY_ALIASES.get(key, key)
    if key not in TASK_POLICIES:
        raise ValueError(
            f"unknown approval policy {policy!r} "
            f"(expected one of {sorted(TASK_POLICIES)})")
    return key


def is_sensitive(tool: str | None) -> bool:
    return bool(tool) and tool in DEFAULT_APPROVAL_TOOLS


def decide_for_step(
    tool: str | None,
    args: dict[str, Any] | None,
    task_policy: str = "default",
    approved_tools: list[str] | None = None,
    existing_decision: str | None = None,
) -> tuple[str, str]:
    """Return (decision, reason); decision in allow | ask | deny.

    ``existing_decision`` is the durable AgentApproval row status for
    this step (approved | denied | pending | None).
    """
    args = args or {}
    if tool:
        # Blacklist beats every policy and every prior approval.
        blacklist = DEFAULT_POLICY.evaluate(tool, args, approval_policy="automatic")
        if blacklist.decision == "deny":
            return "deny", blacklist.reason or "Blocked by risk policy."
    if existing_decision == "approved":
        return "allow", "Previously approved for this step."
    if existing_decision == "denied":
        return "deny", "Approval denied for this step."
    policy = normalize_policy(task_policy)
    if not is_sensitive(tool):
        return "allow", f"Tool {tool!r} is not sensitive." if tool else "No tool call."
    if policy == "deny":
        return "deny", "Per-task deny policy: sensitive actions are refused."
    if policy == "always":
        return "ask", f"Tool {tool!r} requires approval (always policy)."
    if policy == "once":
        if tool in (approved_tools or []):
            return "allow", f"Tool {tool!r} was approved once for this task."
        return "ask", f"Tool {tool!r} requires one-time approval for this task."
    # default: the existing policy (sensitive tools ask).
    decision = DEFAULT_POLICY.evaluate(tool, args, approval_policy="default")
    if decision.decision == "ask":
        return "ask", decision.reason
    if decision.decision == "deny":
        return "deny", decision.reason
    return "allow", decision.reason
