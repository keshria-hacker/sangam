# Sangam — Task Tracker (continuation)

Branch: `integration/full-program` only. No merge to `main`, no tag, no
voice-cloning/video work without the user's explicit word (standing
boundaries from prior runs).

Baseline at tracker creation (2026-10-28): head `d8e6312`
(UI-only simplification, frontend-only). Prior verification recorded in
`docs/UI_SIMPLIFICATION.md` and `FIX_LOG.md` — this tracker does not
re-audit that work; it carries forward only its documented follow-ups.

## Standing boundaries

- Stay on `integration/full-program`; never force-push; never commit
  secrets, `.env` files, or private data.
- Security tools inside Sangam only with per-run approval, sandboxed /
  isolated execution, audit log, and own-systems-only guardrails.
- LAN access only with host pairing approval, expiring revocable
  per-device tokens, TLS by default; password reset revokes pairings.

## Open follow-ups (from prior runs, in priority order)

| ID | Task | Priority | Status |
|----|------|----------|--------|
| F1 | Chat provider tool path runs without ECC guard hooks (shared `executor` has `hooks=None`; agent loop has them) | P1 security | In progress 2026-10-28 |
| F2 | `settings/devices.js` still uses `window.confirm` for revoke-all / cert regeneration (Batch E covered Reset-all only) | P2 UI consistency | Open |
| F3 | Command palette has no focus trap; re-renders on mousemove | P2 accessibility | Trap implemented 2026-10-28; mousemove re-render still open (minor) |
| F4 | Workflows canvas has no special mobile handling (absolute 140px nodes, overflow-hidden) | P2, larger job | Open |
| F5 | Diagram PNG export is client-side canvas rasterisation with no server renderer; failure is only a toast | P3 | Open |
| F6 | Knowledge Export is memories-JSON only | P3 | Open |
| F7 | Live runs never verified here: physical phone QR scan, real two-device LAN/mDNS, Docker isolation, real-driver browser-agent run, live model pipeline/council runs | Blocked (needs device / network / model) | Open |

## Tasks in this run

| ID | Description | Files | Acceptance | Status |
|----|-------------|-------|------------|--------|
| T1 | Wire ECC guard hooks into the shared chat tool executor so destructive-bash and config-protection rules apply on the chat provider path, not only the agent loop | `mainfiles/backend/tools/executor.py`, `tests/test_shared_executor_guards.py`, `docs/audit/*` | Destructive `run_bash` and protected-config `write_file` are blocked before the handler runs on the shared executor; benign calls still execute; targeted tests pass | Completed 2026-10-28; full suite 1628/101/0 |
| T2 | Replace the two `window.confirm` calls in `settings/devices.js` with the existing confirm-overlay pattern | `mainfiles/frontend/js/features/settings/devices.js` | No `window.confirm` call remains in that file; frontend module check passes | Completed 2026-10-28; frontend 65/65, smoke 3/3 |
| T3 | Command palette focus trap + return focus on dismiss | `mainfiles/frontend/js/features/palette/palette.js` | Tab/Shift+Tab cycle within the open palette; Escape/backdrop return focus to the element focused before opening; running an action does not steal its focus back | Completed 2026-10-28; frontend 65/65, smoke 3/3, live Tab cycling not click-checked here |

## Completed in this run

- T1, T2, T3 (2026-10-28, single commit on `integration/full-program`;
  hash filled at push time) — see `docs/audit/IMPLEMENTATION_LOG.md`.
