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
| F3 | Command palette has no focus trap; re-renders on mousemove | P2 accessibility | Completed 2026-10-29 (trap 2026-10-28; mousemove now updates selection in place instead of rebuilding the list DOM) |
| F4 | Workflows canvas has no special mobile handling (absolute 140px nodes, overflow-hidden) | P2, larger job | Completed 2026-10-28 (scrollable canvas + edge layer sized to node extent + touch-action none + Enter/Space node selection) |
| F5 | Diagram PNG export is client-side canvas rasterisation with no server renderer; failure is only a toast | P3 | Completed 2026-10-29 (explicit canvas dims + white background + specific error toasts for toBlob-null / canvas-unavailable / image-load failure; server raster renderer still deferred as follow-up) |
| F6 | Knowledge Export is memories-JSON only | P3 | Completed 2026-10-29 (one-click export is now sangam-knowledge-export.json: memories + code-graph dump + notebook references + uploaded-document references via new GET /api/files; per-section degradation instead of all-or-nothing) |
| F7 | Live runs never verified here: physical phone QR scan, real two-device LAN/mDNS, Docker isolation, real-driver browser-agent run, live model pipeline/council runs | Blocked (needs device / network / model) | Open |

## Tasks in this run

| ID | Description | Files | Acceptance | Status |
|----|-------------|-------|------------|--------|
| T1 | Wire ECC guard hooks into the shared chat tool executor so destructive-bash and config-protection rules apply on the chat provider path, not only the agent loop | `mainfiles/backend/tools/executor.py`, `tests/test_shared_executor_guards.py`, `docs/audit/*` | Destructive `run_bash` and protected-config `write_file` are blocked before the handler runs on the shared executor; benign calls still execute; targeted tests pass | Completed 2026-10-28; full suite 1628/101/0 |
| T2 | Replace the two `window.confirm` calls in `settings/devices.js` with the existing confirm-overlay pattern | `mainfiles/frontend/js/features/settings/devices.js` | No `window.confirm` call remains in that file; frontend module check passes | Completed 2026-10-28; frontend 65/65, smoke 3/3 |
| T3 | Command palette focus trap + return focus on dismiss | `mainfiles/frontend/js/features/palette/palette.js` | Tab/Shift+Tab cycle within the open palette; Escape/backdrop return focus to the element focused before opening; running an action does not steal its focus back | Completed 2026-10-28; frontend 65/65, smoke 3/3, live Tab cycling not click-checked here |
| T4 (F4) | Workflows canvas mobile handling | `mainfiles/frontend/css/style.css`, `mainfiles/frontend/js/features/workflows/workflows.js` | At 390px, a node at x=900 is reachable by scrolling the canvas; edge layer covers the full node extent; nodes have touch-action none; Enter on a focused node selects it with focus restored | Completed 2026-10-28; frontend 65/65, live 390px check 1/1 (temporary spec, deleted after the run) |
| T5 (F5) | Diagram PNG export hardening (client-side only; no server renderer) | `mainfiles/frontend/js/features/create/diagrams.js` | Explicit canvas dimensions (decoded size → viewBox → width/height attrs → 800x600), opaque white background before drawImage, distinct error toasts for toBlob-null, canvas-unavailable, and image-load failure; SVG export untouched | Completed 2026-10-29; frontend 65/65, smoke 3/3, live PNG download 400x300 verified 2/2 (temporary spec, deleted after the run) |
| T6 (F6) | Knowledge Export covers code graph + notebooks + documents, not memories only | `mainfiles/frontend/js/features/knowledge/knowledge.js`, `mainfiles/backend/api_routes/files_routes.py` (new GET /api/files), `ARCHITECTURE.md` §13.2, `tests/test_knowledge_export_files.py` | Knowledge Export button downloads sangam-knowledge-export.json with memories + code-graph dump + notebook references + uploaded-document references; one failing section degrades to a note, not a failed export; GET /api/files returns references only (no stored_path, no extracted_text) | Completed 2026-10-29; frontend 65/65, smoke 3/3, targeted tests 4/4 (incl. drift test), live export bundle verified 2/2 (temporary spec, deleted after the run) |
| T7 (F3) | Palette mousemove re-render | `mainfiles/frontend/js/features/palette/palette.js` | Hovering a palette item moves selection without rebuilding the list DOM (first item element stays connected); focus-trap comment updated (list re-renders on filter only) | Completed 2026-10-29; frontend 65/65, node --check OK; live hover check not completed (palette-open step in the temporary spec never opened the palette in this harness — code + module check only, recorded as a limit, not claimed) |
| T8 | Agent CostMeter pricing: saved cost_budget was unenforceable (no production caller passed a price, so cost_known was always False) | `mainfiles/backend/providers/pricing.py` (new), `mainfiles/backend/code_agent.py`, `tests/test_cost_meter_pricing.py` | Prices derived from LiteLLM's bundled cost table for the run's model (input/output per-token, provider-prefix stripped); unknown model stays unknown, never fabricated; explicit flat rate still wins; budget check stops a run over budget | Completed 2026-10-29; new tests 8/8, deep-agent + agents suites 38/38 with the new tests, drift 1/1, frontend 65/65 |
| T9 | Agent cost snapshot never reached the UI (no route forwarded on_usage_detail) | `mainfiles/backend/api_routes/agents_routes.py`, `mainfiles/backend/api_routes/code_agent_routes.py`, `mainfiles/backend/code_agent.py` (run_code_agent forwards on_usage_detail), `mainfiles/frontend/js/shared/runlog.js`, `mainfiles/frontend/css/style.css`, `tests/test_agent_usage_sse.py` | All three streaming agent routes emit a final 'usage' event (latest cumulative snapshot) before 'end'; RunLog renders tokens in/out/total + cost when known, 'cost unknown (unpriced model)' otherwise; no usage event when no model response happened | Completed 2026-10-30; new route tests 3/3, pricing + drift 12/12 with the new tests, frontend 65/65; live browser rendering of the usage line not click-checked here |

## Completed in this run

- T1, T2, T3 (2026-10-28, commit `c828653` on `integration/full-program`,
  pushed, 0 ahead/behind) — see `docs/audit/IMPLEMENTATION_LOG.md`.
- T4 / F4 (2026-10-28, commit `7a0cf96` on `integration/full-program`,
  pushed, 0 ahead/behind) — workflows canvas mobile handling, see log.
- T5 / F5 + T6 / F6 (2026-10-29, commit `f2d8a04`, pushed 2026-10-29
  after an independent full-suite rerun went green — see log) —
  diagram PNG hardening + Knowledge Export expansion, see log.
- T7 / F3 (2026-10-29, commit `cf7943c` on `integration/full-program`,
  pushed, 0 ahead/behind) — palette mousemove no longer rebuilds the
  list DOM, see log.
- T8 (2026-10-29, commit `a92b191` on `integration/full-program`,
  pushed, 0 ahead/behind) — agent CostMeter pricing from LiteLLM's
  cost table, see log.
- T9 (2026-10-30, commit filled at push time) — agent 'usage' SSE
  event + RunLog rendering, see log.
