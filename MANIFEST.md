# A4 — Agents, Tasks & Automation: manifest

Branch: `spec/a4-agent-runtime` (based on `integration/full-program` @ 740306f).
Scope rule honoured: no changes to `~/workspace/projects/sangam` (main
checkout), no changes to `docs/ARCHITECTURE.md`, `README.md`, or
`FIX_LOG.md` (coordinator-owned). Nothing pushed.

## What it is

A thin runtime that WRAPS the existing engines instead of duplicating
them: `code_agent.py` (agent loop + durable `AgentApproval` rows),
`automations.py` (schedule parsing), `workflows.py` (DAG engine),
`security_guardrails.py` / `security_catalog.py` (allowlist, passive
recon, phase order, PASS report gate), `permission_policy.py` (risk
tiers / blacklist). New code is orchestration only: planner, state
machine, scheduler, approval gate, budget meter, circuit breaker, audit
log, notification bus, restart-safe persistence.

## New / changed routes (all under /api; 17 new)

| Method | Path | Notes |
|---|---|---|
| POST | /agent-tasks | Create task; plan validated (422 on cycle/unknown dep/unknown kind) |
| GET | /agent-tasks | List, filters `status`, `trigger` |
| GET | /agent-tasks/{task_id} | Detail: steps, budget gauge, `audit_count` |
| POST | /agent-tasks/{task_id}/run | Execute / resume pending steps |
| POST | /agent-tasks/{task_id}/pause | pending/running → paused (409 otherwise) |
| POST | /agent-tasks/{task_id}/cancel | → cancelled (409 if terminal) |
| POST | /agent-tasks/{task_id}/record-usage | Observed usage + budget enforcement |
| GET | /agent-tasks/{task_id}/audit | Audit trail, oldest first |
| GET | /agent-tasks/{task_id}/notifications | Task notifications |
| POST | /agent-tasks/scheduler/tick | Run everything due: agent tasks + workflows |
| POST | /agent-tasks/security-graph | Recon→Vuln-hunter→Validator→Reporter task (see below) |
| POST | /agent-tasks/{task_id}/event | Event trigger (trigger must be `event`, name must match config) |
| POST | /agent-tasks/{task_id}/webhook | Public router, per-task token; wrong token → 404 (no leak) |
| GET | /agent-approvals | Approval queue, `status` filter (default pending), scoped via owning task |
| POST | /agent-tasks/{task_id}/approvals/{approval_id}/decide | `{approved, reason}`; durable row + step re-armed |
| GET | /agent-notifications | In-app notifications, `unread_only` filter |
| POST | /agent-notifications/{notification_id}/read | Mark read |

Unchanged routes touched only as callers: existing `/workflows/*`
(now also serves the `approval` node type + `waiting_approval` status),
`/security/*` (unchanged), `/runs` (receives `agent-task` mirrors).

## New / changed frontend modules

- NEW `mainfiles/frontend/js/features/agents/taskboard.js` — exports
  `renderTaskBoard(bodyEl)`. Destination-agnostic: the coordinator's
  shell mounts it under Agents. Task list, task detail (steps with
  completed/failed/skipped counts, budget gauges as `<progress>`),
  approval queue (approve/deny with reason prompt), run history (Runs
  store, `kind=agent-task`), audit trail, notifications, task creation
  form, scheduler tick button. No new dependencies; imports only
  `shared/http.js`, `shared/toast.js`, `shared/utils.js`.
- No changes to `tabs.js`, sidebar, shell, `settings_schema.js`, or any
  other frontend module.

## New settings keys (for the coordinator's Settings centre; NOT yet
## added to settings_schema.js — that file is shared, coordinator merges)

Section for all: **Agents & Automation** (spec §7).

| Name | Label | Description | Default |
|---|---|---|---|
| agentRuntime.defaultApprovalPolicy | Default task approval policy | Per-task approval policy for new tasks: default (sensitive tools ask), once, always, or deny. Blacklisted calls are denied under every policy. | `default` |
| agentRuntime.tokenBudget | Default token budget per task | Token budget for new tasks; 0 = unlimited. Exceeding it stops the run. | `0` |
| agentRuntime.costBudgetUsd | Default cost budget per task (USD) | Cost budget for new tasks; 0 = unlimited. Only enforced on reported (known) usage, never on estimates. | `0.0` |
| agentRuntime.maxConcurrentTasks | Max concurrent tasks | Cap on tasks the scheduler tick runs in one pass (safety bound; runs are request-scoped otherwise). | `3` |
| agentRuntime.circuitErrorThreshold | Circuit breaker: consecutive errors | Failed steps in a row before the circuit trips and stops the run. | `5` |
| agentRuntime.circuitVelocityPerMin | Circuit breaker: steps per minute | Steps started inside 60s before the circuit trips (runaway-loop guard). | `30` |
| agentRuntime.circuitNoProgressSteps | Circuit breaker: no-progress steps | Consecutive steps with empty or unchanged output before the circuit trips. | `3` |
| agentRuntime.notifyOnTaskDone | Notify on task completion | In-app notification when a task completes, fails, needs approval, exceeds budget, or trips the circuit. | `true` |
| agentRuntime.schedulerEnabled | Enable background scheduler | Opt-in 30s scheduler loop (`SANGAM_AGENT_SCHEDULER=1`); off by default so tests never get surprise runs. The tick endpoint works regardless. | `false` |

Existing keys NOT duplicated: `agentMaxSteps`, `requireApproval`,
`notifyOnDone` already exist in the agents category.

## DB / model changes (new tables; no existing table altered)

- `agent_tasks` — task + policy + budgets + trigger + schedule + circuit
  flags + summary/config JSON. (New model file; `models.py` untouched.)
- `agent_task_steps` — plan steps with status/result/error/attempts and
  `approval_id` → `agent_approvals.id` (reuses the existing durable
  approval table; no second approval table).
- `agent_audit_events` — readable audit trail per task.
- `agent_notifications` — in-app notifications (no external service).
- Terminal task outcomes also mirror to existing `agent_runs`
  (`kind=agent-task`, title `"<title> [<task_id>]"`) so run history,
  audit, and notifications agree.
- No migration file: tables are created by `Base.metadata.create_all`
  once `backend.api` imports the routes module (same pattern as the
  `hooks.AgentApproval` / security tables).

## Exactly what changed in api.py (ONE block)

```python
# A4 (perfect-flow): importing this module registers the agent-runtime
# routes (tasks, approvals, audit, notifications, scheduler tick,
# security graph) on the shared router. This is the ONLY api.py change.
from .api_routes import agent_runtime_routes  # noqa: F401
```

## Other code changes (worktree only)

- NEW `mainfiles/backend/agent_runtime/` package:
  `models.py`, `planner.py` (validate plan, topo order, cycle rejection),
  `state_machine.py` (task/step transitions; completed/cancelled terminal),
  `budgets.py` (meter; 0 = unlimited; unknown usage never estimated),
  `circuit.py` (error-storm / velocity / no-progress, server-side),
  `approvals.py` (policies default/once/always/deny + automatic/always_ask
  aliases; blacklist beats every policy — extends `permission_policy`,
  does not fork it), `executor.py` (topo execution, resume-safe,
  dependency-failure skips, approval pauses, budget/circuit stops),
  `runner.py` (dispatch to real handlers only), `store.py`
  (serialisers, audit/notification helpers, Runs mirror),
  `service.py` (create/run/decide/record-usage/pause/cancel/security-graph),
  `scheduler.py` (due filters, tick, opt-in loop).
- EDIT `mainfiles/backend/workflows.py` (gap fix, not a rebuild): new
  `approval` node type. The run input's `__approvals` map decides it:
  `approved` passes, `denied` fails as a dead letter, missing pauses
  the run with status `waiting_approval` (downstream nodes skipped,
  never executed). `run_workflow_row` maps `approval_required:` errors
  to `waiting_approval` instead of `failed`. All other engine
  guarantees (timeouts, retries, dead letters, idempotency, replay,
  `run_if`) unchanged.
- NEW `tests/test_a4_agent_runtime.py` (19 tests).

## Security workspace: what was added, what was NOT

Added (fits without duplicating the security module):
POST /agent-tasks/security-graph creates a runtime task whose four
steps are Recon → Vuln-hunter → Validator → Reporter, backed by a real
`SecurityRun`. It reuses `check_scope` (target must be allowlisted at
creation AND re-checked by every phase step), `run_passive_recon`
(passive only) for Recon, `next_phase` for phase order, and the same
PASS gate as `/security/runs/{id}/report` for Reporter (fails listing
blockers unless every finding is validated PASS). Active tool execution
is deliberately NOT duplicated: Vuln-hunter/Validator steps record the
phase and state explicitly that tools still execute only via the
Security workspace's own per-run approval.
NOT built (exclusions stay absolute): no DDoS/RAT/phishing/brute-force/
wireless/session-hijack/backdoor/WAF-bypass/third-party-target tooling,
no unrestricted exploitation, no auto-install-and-run of tools. No
guardrail was weakened; no existing security route was changed.

## Partial / blocked (honest)

- Workflow approval nodes pause at the node, but a resumed workflow
  re-runs from its input (existing replay semantics) rather than
  resuming mid-graph. Documented in the workflows docstring; the task
  layer does resume mid-plan (completed steps are never re-run).
- The `agent` task-step kind delegates to `code_agent.run_agent` and
  needs a configured model; with no model it fails with a clear error
  (never a fake answer). No live LLM run was exercised here (no model
  in this environment) — see "Could not verify".
- Scheduler cron keeps the existing simplified next-hour semantics
  from `automations.parse_schedule` (stated in `scheduler.py`); it is
  not full cron evaluation.
- The background scheduler loop (`start_agent_scheduler`) is NOT wired
  into `main.py` lifespan by this branch (that file is merge-sensitive);
  the coordinator should wire it next to `start_workflow_scheduler`
  if the loop is wanted, or operators can call the tick endpoint.
  Same for mounting `renderTaskBoard` under Agents (shell agent's job).

## Coordinator actions needed at merge

1. Add the 17 routes above to `ARCHITECTURE.md` §13.2 — the drift test
   currently fails ONLY on those missing rows (zero stale rows).
   Verified: `test_docs_routes_drift.py` diff = exactly these routes.
2. Add the 9 settings keys above to the Settings centre (and, if
   wanted, to `settings_schema.js`).
3. Mount `renderTaskBoard` under the Agents destination.
4. Optionally wire `agent_runtime.scheduler.start_agent_scheduler`
   into the app lifespan next to `start_workflow_scheduler`.
5. Run the Playwright specs (NOT run by this branch — shared ports):
   `tests/e2e/workflows.spec.ts` (canvas + 3-node flow UI path),
   `tests/e2e/runs.spec.ts` (Runs centre incl. `agent-task` mirrors),
   `tests/e2e/security.spec.ts` (security workspace regression), plus a
   new task-board spec if the shell agent adds one (task list → detail
   → approval queue → run history). API proof for the 3-node flow
   (LLM→condition→tool) is in `test_api_workflow_approval_node_and_3node_flow`.

## Tests run (actual, this worktree, proxy env vars unset)

- `tests/test_a4_agent_runtime.py` — 19 passed (planner, state machine,
  budget, circuit, approvals, executor gating/budget/circuit/resume,
  API create/run/audit/notification/Runs-mirror, approval gate block +
  deny, record-usage budget stop, circuit trip, plan validation,
  restart-resume with a fresh app instance on the same DB file,
  workflow approval node + 3-node LLM→condition→tool flow + the same
  flow as a runtime task step, security graph + scope refusal,
  scheduler tick for tasks + workflows + webhook + event triggers).
- Regression set in the same run:
  `tests/test_a4_agent_runtime.py tests/test_phase3_workflows.py
  tests/test_agents.py tests/test_batch2_security.py tests/test_phase3.py`
  — **51 passed**.
- Frontend: `node --experimental-vm-modules
  scripts/check_frontend_modules.mjs` — **64/64 modules parse + link**
  (63 before + new `taskboard.js`).
- Drift: `tests/test_docs_routes_drift.py` — 1 failed, diff = exactly
  the 17 new routes above (coordinator-owned docs update, see §1).

## Could not verify (needs coordinator / live environment)

- Playwright UI paths (forbidden here: shared ports :8001/:5500) —
  task-board rendering in a real browser, workflow canvas drag/drop.
- A live `agent` step with a real model/provider, and live passive
  recon against a real target (tests stub the provider boundary and
  the recon fetchers; the recon code path itself is the real function).
- Real two-device / LAN behaviour: untouched by this branch.
- The background scheduler loop running for 30s+ in a live server
  (tick logic is tested; the loop itself is opt-in and unwired).
