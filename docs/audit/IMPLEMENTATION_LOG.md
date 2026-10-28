# Sangam — Implementation Log (continuation, from 2026-10-28)

Branch: `integration/full-program`. Prior work is in `FIX_LOG.md`,
`docs/UI_SIMPLIFICATION.md`, and `docs/ALL_IN_ONE_COVERAGE.md`; this log
only records work from the 2026-10-28 continuation run onward. Task IDs
refer to `docs/audit/TASK_TRACKER.md`.

## 2026-10-28 — T1: guard hooks on the shared chat tool executor (P1)

- Gap (code evidence, not a claim from a button existing): the agent loop
  built its own executor with `default_guard_registry()` (`code_agent.py`),
  but the shared `executor` used by the chat provider tool path
  (`providers/__init__.py:716`) was `ToolExecutor()` with `hooks=None`.
  Its builtin tools include `run_bash` (no destructive-pattern check in
  the handler itself) and `write_file`/`edit_file`.
- Reproduction (stub registry swapped onto the shared executor, no real
  shell/file effect): before the fix, `shared.hooks` was `None` and a
  `run_bash` call with `rm -rf /` reached the handler. After the fix,
  the same call is blocked with `destructive-bash/rm-root` and the
  handler never runs.
- Change: `mainfiles/backend/tools/executor.py` — shared executor is now
  built by `_guarded_shared_executor()` with `default_guard_registry()`;
  module docstring updated. A caller constructing its own `ToolExecutor`
  without hooks keeps legacy behaviour and must opt in explicitly.
- Tests: new `tests/test_shared_executor_guards.py` (4 tests: hooks
  present; destructive bash blocked; protected-config write blocked;
  benign call still executes). Targeted run: 4/4 passed.
  Related: `test_deep_agent_core.py` + `test_mcp.py` passed with the
  change; `test_agents.py` failures in that run were a missing `litellm`
  install in the fresh venv, not this change.
- Full-suite totals: **1628 passed, 101 skipped, 0 failed** (28m23s,
  run with all proxy vars including NO_PROXY/no_proxy unset, TMPDIR on
  the main disk). Baseline at `d8e6312` was 1624 passed / 101 skipped /
  0 failed; the +4 is exactly the new guard tests. 17 warnings only
  (event-loop-closed / unawaited-coroutine noise in existing health
  tests, no failures).
- Playwright smoke (live, after T1–T3): 3/3 passed
  (register/rail/popovers/settings/chat/knowledge + 390px mobile).

## 2026-10-28 — T2: devices confirm dialogs (P2)

- Change: `mainfiles/frontend/js/features/settings/devices.js` — added
  `showDevicesConfirm()` following the Settings Reset-all
  confirm-overlay pattern (fresh element per open, Escape, backdrop
  click, focus on Cancel) and replaced the two remaining
  `window.confirm` calls (Revoke all devices; Regenerate certificate)
  with it. No other `window.confirm` call remains in frontend JS
  (only comments mention it).
- Verification: `node --check devices.js` OK;
  `node --experimental-vm-modules scripts/check_frontend_modules.mjs`
  → 65/65 parse + link. Live click-through of the two dialogs was not
  done in this run (no Playwright pass yet) — recorded as a limit, not
  claimed.

## 2026-10-28 — T3: command palette focus trap (P2)

- Change: `mainfiles/frontend/js/features/palette/palette.js` —
  palette container now traps Tab/Shift+Tab within its live focusable
  elements (input + rendered action buttons, queried at key time
  because the list re-renders); `openPalette()` records the previously
  focused element and `closePalette(true)` (Escape, backdrop click)
  returns focus to it if still connected. `runSelected()` closes
  without restoring, so the chosen action keeps its own focus target.
- Verification: `node --check palette.js` OK; frontend modules 65/65
  after the change. Live Tab cycling was not click-checked here.
  The palette's mousemove re-render is unchanged (pre-existing, minor).
