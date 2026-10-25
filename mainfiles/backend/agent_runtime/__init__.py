"""agent_runtime — A4 (perfect-flow) agent/task runtime.

Thin orchestration layer that WRAPS the existing engines instead of
duplicating them:

* task plans / state machine / scheduler / approval gate / budget meter /
  circuit breaker / audit log / notification bus live here;
* execution delegates to :mod:`backend.code_agent` (agent loop + approval
  rows), :mod:`backend.automations` (schedule parsing), :mod:`backend.workflows`
  (DAG engine + canvas), and :mod:`backend.security_guardrails` (allowlist,
  passive recon, phase order, PASS report gate).

Nothing here invents tool output: a step either runs a real handler, waits
for a real human decision, or fails with a real error. Usage is only
counted when a runner reports it; unknown usage is reported as unknown,
never estimated (see :mod:`backend.code_agent.CostMeter`).
"""

from . import budgets, circuit, planner, state_machine  # noqa: F401

__all__ = ["budgets", "circuit", "planner", "state_machine"]
