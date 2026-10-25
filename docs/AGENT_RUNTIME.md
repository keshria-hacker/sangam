# Sangam — Agent Runtime (perfect-flow program)

## Shape: a wrapper, never a duplicate

`backend/agent_runtime/` wraps the existing `code_agent`,
`automations`, `workflows`, and `security` modules. It does not
re-implement them. A task plan is validated (topological order, cycle
rejection) and executed as a state machine (task steps with explicit
states); terminal outcomes mirror to the Runs centre as
`kind=agent-task`, so agent work is visible next to chat, workflow,
and media runs.

## Components

- **Planner.** Validates task plans before anything runs; cycles are
  rejected, order is topological.
- **State machine.** Task/step states are explicit and persisted.
- **Scheduler.** Hourly/daily/weekly/cron (via the existing schedule
  parsing) plus event triggers and token-authenticated webhook
  triggers. Opt-in via `SANGAM_AGENT_SCHEDULER=1`; without it the
  scheduler returns immediately and tests are unaffected. The workflow
  scheduler next to it in `main.py` lifespan is separate.
- **Approval gate.** Extends the existing permission policy: the
  blacklist denies under every policy, and decisions reuse the durable
  approval table (not an in-memory allowlist). Security runs need
  explicit per-run approval, sandboxed/isolated execution, an audit
  log, and own-systems-only guardrails. A workflow `approval` node
  pauses the run as `waiting_approval`; downstream nodes never execute
  until approved.
- **Budget meter.** 0 = unlimited. Unknown usage is reported as
  unknown, never estimated (a gauge that rebuilt a fresh meter and
  lost the unknown flag was caught and fixed during testing).
- **Circuit breaker.** Server-side; a failing provider/tool path
  trips it instead of retrying forever.
- **Audit log + notification bus.** Every agent action is logged
  (`agent_audit_events`); in-app notifications surface approvals and
  completions (`agent_notifications`).
- **Persistence.** New tables `agent_tasks`, `agent_task_steps`,
  `agent_audit_events`, `agent_notifications` — restart-safe. The
  task layer resumes mid-plan; resumed *workflows* re-run from input
  (documented limit — only the task layer resumes mid-plan).
- **Scheduler cron semantics.** Simplified next-hour semantics for
  cron (documented limit, not a full cron engine).

## Surfaces

- 17 agent routes (see `ARCHITECTURE.md` §13.2) + task board UI
  (Agents → tasks; `/agents/:id` pre-selects the task).
- Pentest graph endpoint: Recon → Vuln-hunter → Validator → Reporter,
  backed by a real SecurityRun with the PASS gate intact. All
  must-not-build exclusions hold: no unrestricted exploitation, no
  bypass/backdoor tooling, no third-party targeting without proven
  scope, no CAPTCHA/WAF bypass, no DDoS/RAT/phishing tooling.
- Council / Deliberate mode and hive Teams v2 (capped debate) live in
  the agent layer from the earlier deep-read run; the MiroFish swarm
  as a whole is out of scope (the capped debate is the substitute).

## Documented limits

- No live LLM run or live passive recon was exercised end to end in
  this environment (stubbed at provider boundaries in tests).
- Scheduler cron keeps simplified next-hour semantics.
- Resumed workflows re-run from input; only the task layer resumes
  mid-plan.
- Per-message tool overrides steer the normal stream path, not the
  separate agent path.
