# FIX_LOG.md — Sangam Bug Fixes

**Date:** 2026-10-09

## Phase 6 Fixes

### Broken ES Module Imports (Critical)
**Found by:** Playwright golden path tests + `check_frontend_modules.mjs`

1. **`js/shared/runlog.js`**: Imported from `'../../shared/utils.js'` (wrong — file is in `js/shared/`, so `../../` escapes to root). Fixed to `'./utils.js'`.
   - **Impact:** 404 broke module loading, stuck app on auth loading screen.

2. **`js/features/inspector/inspector.js`**: Imported `getSelectedModel` from `'../models/models.js'` (doesn't export it). Fixed to `'../../core/state.js'`.
   - **Impact:** Module load error, app failed to initialize.

3. **`js/features/presets/presets.js`**: Two bad imports:
   - `'../shared/settings_store.js'` → `'../../shared/settings_store.js'`
   - `'../shared/toast.js'` → `'../../shared/toast.js'`
   - **Impact:** Found by `check_frontend_modules.mjs`, would have broken presets feature.

**Lesson:** `node --check` is insufficient for ES modules. Use `node --experimental-vm-modules scripts/check_frontend_modules.mjs` which validates imports/exports through V8.

### Test Suite Flakiness
**Symptom:** Different tests fail on different full-suite runs; all pass in isolation.
**Root cause:** Test pollution via shared database/app state.
**Status:** Known issue, not introduced in Phase 6. Tests pass reliably in isolation.

### Auth Flow in TEST_MODE
**Symptom:** Playwright tests couldn't log in.
**Root cause:** Test used weak password (`goldenpath123`) that failed the password policy (requires uppercase).
**Fix:** Used `Goldenpath123` and registered the test user via API before running tests.

## Phase 1-5 Fixes (Summary)

- **Phase 1:** Deleted dead `/api/agentic-reasoning` route; fixed voice fetch abort; fixed tool tab re-render; fixed Design Studio project ID regeneration.
- **Phase 2:** Settings persistence via `settings_json`; feature flags with runtime overrides.
- **Phase 3:** Approval gate for sensitive tools; knowledge graph unification.
- **Phase 4:** Fixed `highlight.highlightElement` → `window.hljs.highlightElement`; fixed undeclared `btn` in Learn.
- **Phase 5:** Automations API gap (config in list + single GET).
