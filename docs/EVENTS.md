# Sangam — Events, Runs & Telemetry (perfect-flow program)

## The single Activity feed (Runs centre)

Agents → Run History is the single place where work is observed:
live runs, run history, artifacts, media jobs, workflow runs. Every
kind of work mirrors there with its kind preserved:

- chat responses → "View run" from the response action menu
- agent tasks → `kind=agent-task`
- workflows → workflow runs (a `waiting_approval` run pauses at its
  approval node; downstream never executes unapproved)
- media jobs → transcribe / tts / dub / image as observable jobs

The old composer Runs button/pill is removed by spec (A2): history
is reached via Agents → Run History, not from the composer. The old
Work → Activity path redirects there.

## SSE event protocol

Chat streams over SSE (see `ARCHITECTURE.md` §5.2/§5.3 for the wire
shape). The response pipeline adds pipeline events (intake, routing
decision, tool choice in Auto mode, validation) so the Tools popover
can show what Auto actually chose, per message, with per-message
overrides for the next turn.

## In-app notification bus

Agent approvals, completions, and scheduler outcomes publish to the
in-app bus (`agent_notifications`, restart-safe). There is no
push/email notification path in this build; the bus is in-app only.

## Telemetry

Default OFF (user-approved default 6). When enabled, the ledger
records chat USAGE telemetry (Phase 0) and run outcomes; it never
records message content, keys, or tokens. The usage meter in the
sidebar footer shows "Usage unavailable" before auth and "Usage:
local only" when there is nothing billable — never an invented
number. Cost is reported as unknown (`cost_known=False`) until a
caller passes a real `price_per_1k_usd`; the old fake `len//4` cost
meter was replaced with a real meter in the deep-read run.

## Audit log

Agent actions, security runs, approvals, and pairing events append
to the audit log (`agent_audit_events` + security audit). Password
reset revokes paired LAN devices as well as sessions.
