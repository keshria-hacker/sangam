"""agent_runtime — Batch 10: one Sangam-native agent runtime package.

Deep-read Wave 3 (agents-skills brief) found the loop fragmented across
``code_agent.py``, ``pipeline_agents.py``, ``workflows.py``, ``teams/``
and ``hive.py`` while ``backend/agent_runtime/`` held only ``__pycache__``.
This package is the missing glue — it does NOT replace ``run_agent``,
which stays the API-compatible loop. New code here is the portable
mechanism only, ported from source-level reading, never a second engine:

* ``loop`` — pi: steering queue + abort, parallel-vs-sequential tool
  planning, structured compaction with branch resume; odysseus: a frozen
  per-turn contract (required <= offered <= executable, no substitution).
* ``approval`` — claw-code / coucou: async approval — a risky call waits
  in the tray while the run continues with independent work; decisions
  arrive from chat or a paired LAN device through the same tray. The
  existing per-run approval policy + audit log are untouched.
* ``sandbox`` — OpenHands portable idea: a per-run sandbox/worktree as
  the DEFAULT code-agent context, plus a verify-style exit gate that
  runs the project's own test command. Docker isolation is NOT claimed
  as verified here: where Docker is absent the workspace fallback from
  ``security_guardrails`` runs and its warning is always recorded.
* ``orchestration`` — superpowers + mattpocock (subagent-per-task flow
  with blocking edges, fresh context per task, per-task + branch review),
  munder-difflin hive mode (inbox-drain, critical-only escalation,
  single-committer path), orca ask/gate nodes + worktree ownership
  handoff, overmind "propose from evals" (propose, never silently apply).
* ``drivers`` — PersonalJarvis dodaios: a RuntimeDriver protocol for
  supervised external agents (detect / start / health / kill / log-tail).
  Spawning is a library capability, deliberately NOT exposed as an
  arbitrary-command API endpoint (that would be unrestricted execution).
"""
from __future__ import annotations
