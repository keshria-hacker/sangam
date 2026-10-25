# Sangam — Code Tree (perfect-flow program)

Module map: backend routes, the two new packages, and the frontend
shell. Route counts come from `ARCHITECTURE.md` §13.2 (the drift
test enforces the table against the live router).

## Backend routes (`mainfiles/backend/api_routes/`)

| File | Surface |
|---|---|
| `projects_routes.py` | Project workspaces (18 routes + memory dashboard) |
| `spec_routes.py` + `spec_qa_routes.py` | Spec pipeline v2 (11) + QA package (3) |
| `code_graph_routes.py` | Code intelligence (4): Python/JS/TS/Go/Rust/Java |
| `a6_studio_routes.py` | Providers (4), studio (3), diagrams export (1), marketplace (3), connectors health/permissions (2), blind compare (2) |
| `intelligence_routes.py` | Response intelligence (3): route dry-run, harper, modes |
| `agent_runtime_routes.py` | Agent runtime (17): tasks, steps, audit, notifications |
| `chat_stream_routes.py` | Chat stream + response-intelligence wiring |
| `quality_routes.py` | ADHD/slop/Harper preview + lint |
| `memory_routes.py` + `memory_v2_routes.py` | Memory V2 + privacy dashboard |
| `knowledge_routes.py` + `notebooks_routes.py` | Knowledge graph + notebooks |
| `devices_routes.py` | LAN pairing (QR/code, approve/claim/revoke) |
| `workflows_routes.py` | DAG workflows (+ `approval` node type) |
| `runs_routes.py` | Runs centre feed |
| `media_jobs_routes.py` + `media_routes.py` | Media jobs (note: `/media/jobs` was shadowed by `/media/{media_id}` in Phase 4 and fixed to `/media-jobs`) |
| `security_routes.py` | Security workspace + pentest graph |
| `skills_v2_routes.py` + `extensions_routes.py` | Skills marketplace + registry |
| `providers_routes.py` + `models_routes.py` + `fit_routes.py` | Providers, model catalogue, fit advisor |
| `diagrams_routes.py` + `image_routes.py` + `voice_routes.py` | Diagrams (44 types), image ops, voice |
| `connectors_routes.py` | OAuth connectors + MCP |
| `deploy_interface.py` (backend root) | Deploy connector interface only (`deferred`) |
| `system_routes.py` + `settings_routes.py` + `features_routes.py` | Health, settings, feature flags |

## New packages

- `backend/agent_runtime/` — `planner.py` (validated plans, topo
  order, cycle rejection), `state_machine.py`, `scheduler.py`
  (hourly/daily/weekly/cron + event + webhook), `approvals.py`
  (extends the permission policy), `budgets.py` (0 = unlimited,
  unknown stays unknown), `circuit.py`, `executor.py`, `runner.py`,
  `service.py`, `store.py` (restart-safe tables), `models.py`.
- `backend/response_intelligence/` — `pipeline.py` (intake → …
  → post-actions), `classification.py` (rule-first + deterministic
  keyword scorer, labelled as such), `schema.py`, `config.py`,
  `prompt_injector.py`.

## Frontend shell (the IA in code)

- `js/features/shell/router.js` — pure: DESTINATIONS, URL shapes,
  `LEGACY_ID_REDIRECTS`, `LEGACY_PATH_REDIRECTS`,
  `LEGACY_SETTING_SECTIONS` lives in `shared/settings_schema.js`.
- `js/features/tabs/tabs.js` — `navigate()` (pushState), `showTool()`
  (current ids navigate, old ids redirect), `routeFromLocation()`,
  section activators, view cache. Also closes the mobile drawer on
  navigation.
- `js/features/shell/destinations.js` — one renderer per
  destination; segments via `[data-dest-section]`.
- `js/core/nav.js` — `NAV_ITEMS` (the 8), `renderRail()`,
  `markRailActive()`. The rail renders into `#railNav` in
  `index.html`; a stale `.rail-nav{display:none}` hid it until this
  program.
- `js/features/palette/palette.js` — Ctrl/Cmd+K (+Ctrl+P alias),
  lazy model list at open time.
- `js/app.js` — boot order (rail + palette BEFORE the model probe),
  `startApplication()`, scheduler lifespans in `backend/main.py`.
- `js/shared/settings_schema.js` — `SETTING_CATEGORIES` (17),
  `SETTINGS_SCHEMA`, legacy section map.
- `js/features/settings/settings_page.js` — control-center render;
  `sections.js` — custom sections (devices in Security, quality
  preview in Voice, memory dashboard in Memory, …).

## Tests

- `tests/test_a3_projects_memory.py`, `test_a5_spec_qa.py`,
  `test_a6_studio_skills.py`, `test_a2_*` (intelligence),
  `test_a4_*` (agent runtime), `test_a1_*` (shell) — per-merge
  suites; the drift test enforces the ARCHITECTURE route table.
- `tests/e2e/*.spec.ts` — Playwright gate (25 green this program).
- `scripts/check_frontend_modules.mjs` — module parse + link gate.
