# A1 — IA & Shell — manifest

Branch: `spec/a1-shell` (based on `integration/full-program` @ 7b0b575,
which already contains merged A2/A3/A4/A5/A6). Worktree:
`~/workspace/projects/sangam-worktrees/a1`. NOT pushed (per task).
Main checkout at `~/workspace/projects/sangam` untouched.
Coordinator-owned files untouched: `docs/ARCHITECTURE.md` (no new
backend routes, so the route table needs no rows), `README.md`,
`FIX_LOG.md`.

## What shipped

### 1. New information architecture (spec §3)

Exactly 8 top-level destinations, in sidebar order, each a real page;
Chat is pinned and is the only chat surface (never closed, duplicated,
or nested):

| # | Destination | URL | Page |
|---|---|---|---|
| 1 | Chat | `/chat` | Pinned chat view (existing composer, Auto mode, no Runs button) |
| 2 | Projects | `/projects`, `/projects/:id` | A3 `projects.js` list → project home |
| 3 | Studio | `/studio`, `/studio/:artifact` | A6 families/overview + Create/Media/Design segments |
| 4 | Code | `/code`, `/code/:repo` | Code agent + Spec & QA + Code map segments |
| 5 | Research | `/research`, `/research/:notebook` | Knowledge tab (search/graph, notebooks, study) |
| 6 | Agents | `/agents`, `/agents/:id` | Hub + Task board + Run History + Workflows + Security segments |
| 7 | Library | `/library` | Skills / MCP / Extensions / Prompts (existing view) |
| 8 | Settings | `/settings`, `/settings/:section` | Searchable control center (see §7 below) |

Work and Create are flattened completely: no container-that-opens-tabs
remains. `tabs.js` no longer opens strip tabs at all — its old API
(`showTool`, `showToolSection`, `showToolSub`, `openToolTab`,
`switchTab`, `closeTab`, `registerTabRenderer`) now navigates
destinations, so every existing caller keeps working. Sub-navigation
inside a destination is a segmented control at the top of the content
area (`data-dest-section` buttons), never a second sidebar.

### 2. URL router + redirects

NEW `mainfiles/frontend/js/features/shell/router.js` (pure, no DOM,
no imports — unit-tested from Node): `DESTINATIONS`,
`parseRoute`, `urlFor`, `resolveLegacyId`, `breadcrumbText`.
Unknown routes render a 404 page with a "Back to Chat" button.
Old destination ids REDIRECT, never 404:

| Old id | New URL |
|---|---|
| home | `/chat` |
| work | `/agents` |
| create | `/studio` |
| knowledge | `/research` |
| agents / teams / compare | `/agents` (hub segment) |
| code | `/code` |
| workflows | `/agents?section=workflows` |
| runs / activity | `/agents?section=run-history` |
| media | `/studio?section=media` |
| images / voice | `/studio?section=create` |
| design | `/studio?section=design` |
| skills | `/library?section=skills` |
| learn | `/research?section=explore` |
| analytics | `/settings/data` |

Old URL paths `/home`, `/work`, `/create`, `/knowledge` redirect the
same way. A router bug found by the new tests is fixed here:
`/settings/:section` is a section, not a detail param (it used to 404).

### 3. Top bar deleted

`index.html`: the tab strip (`#tabStrip`, `#mainTab`, `#tabAdd`) and
the tool-view title bar (`#toolViewTitle`, `#toolViewClose`) are gone.
The only header left is the pre-existing mobile menu bar (hamburger +
brand on small screens, needed to open the sidebar at all — not a
repeated destination title). In its place, a slim breadcrumb
(`#destBreadcrumb`) sits INSIDE the content area and is shown ONLY
when depth > 1 (e.g. `Agents / task-42`, `Settings / models`).
The sidebar rail highlights the active destination.

### 4. Mounted modules (previously unmounted)

- `features/projects/projects.js` (`renderProjectsView`,
  `renderProjectHome`) → Projects. `/projects/:id` opens the home.
- `features/memory/privacy.js` (`renderMemoryDashboard`) → Settings →
  Memory & Knowledge (rendered as its own block after the schema rows;
  it overwrites only its own container).
- `features/agents/taskboard.js` (`renderTaskBoard`) → Agents → Task
  board. Small signature change only: `renderTaskBoard(bodyEl, opts)`
  pre-selects `opts.taskId`, so `/agents/:id` lands on that task's
  steps/budget/audit/run history.
- `features/code-agent/spec-qa.js` (`specQaPanelHtml`, pipeline list +
  create + advance, QA levels) → Code → Spec & QA segment.
- `features/studio/a6-studio.js` (`A6_STUDIO_FAMILIES`, live
  `/studio/catalog` status) → Studio → Overview segment.
- A2 follow-up #3 DONE: "View run" in `message_view.js` now opens
  Agents → Run History (was Work → Activity), and the workflow-created
  toast, inspector runs link, runs empty-state links, image composer
  button (→ Studio), and slash commands (`/runs`, `/workflows`,
  `/agents`, `/knowledge`→Research, `/create`→Studio, plus new
  `/projects`, `/studio`, `/code`, `/research`) are all re-homed.

### 5. Command palette (Ctrl/Cmd+K; Ctrl+P kept as alias)

NEW `mainfiles/frontend/js/features/shell/palette_index.js` (pure,
Node-tested) + rewritten `features/palette/palette.js`. The index is
built live at open time from: all 8 destinations; all 17 settings
sections; installed skills (GET `/extensions`, kind=skill); saved
prompts (`PROMPT_TEMPLATES`, newly exported from `library.js`); models
(state); conversations (state); plus create actions (new chat /
project / artifact), switch-model items, toggle Auto, install-a-skill,
and built-in commands. "Run a saved prompt" prefills the composer and
focuses it — it never auto-sends (same contract as slash starters).
`app.js` no longer binds Ctrl+K to New chat, so the palette cannot
double-fire. Search is substring over label + keywords.

### 6. First-run (finished, not rewritten)

`features/setup/setup.js` is now 3 steps, skippable at every step,
never blocking:
1. Choose ONE path (cloud key / local Ollama / look around).
2. Only that path's action: cloud = paste key → live save + test →
   green check → suggested model (model list refreshed, model
   pre-selected); Ollama = detect → LIST models → test → first model
   pre-selected (was count-only); look-around = clearly labelled
   SAMPLE panel ("SAMPLE — not a real model response"), never a fake
   reply.
3. One guided first prompt, "What do you want to get done today?" →
   Ask sends through the normal composer in Auto mode. On the
   look-around path step 3 honestly says chat cannot answer yet and
   offers "Connect a provider" instead of faking an answer.
The skip path still dismisses to the non-blocking banner.

### 7. Empty states (audit — exactly one guided next action each)

| Destination (empty) | The one action |
|---|---|
| Chat | The composer itself (Send); step-3 guided prompt on first run |
| Projects | The create-project form ("No projects yet" + form) |
| Studio | "Create your first artifact" → Create segment |
| Code → Spec & QA | The create-pipeline form ("No spec pipelines yet") |
| Code → Code map | The search box ("Type a query above") |
| Research | The search box in Search & Graph |
| Agents → Task board | "New task" button ("No tasks yet. Create one") |
| Agents → Run History | "Run your first agent" → Task board (the old second CTA, "Create your first workflow", was REMOVED from `runs.js`) |
| Library | Existing skill/template cards; no competing CTA added |
| Settings | Never empty; sections with no backing setting render the honest note "No settings in this section yet." (no fake control) |

### 8. Settings control center (§7)

`shared/settings_schema.js` now defines the 17 spec sections
(General, Appearance, Chat & Responses, Models & Providers, Tools,
Memory & Knowledge, Projects & Context, Agents & Automation, Skills &
Library, Connectors & MCP, Voice & Audio, Image & Video, Security,
Data & Privacy, Appearance of code, Advanced, About) with legacy
category ids (`knowledge`, `research`, `voice_output`, `devices`)
redirecting in `settings_page.js`. The page was already searchable by
name AND description (`searchSettings` covers label + description +
key); it now also shows, on every row: label, description, **default**,
current value (the control itself), reset-to-default, and a
**requires-restart** marker where applicable. Read-only and
not-available rows render disabled with an explicit note instead of a
control that silently does nothing. Custom sections remapped:
provider keys / OmniRoute / routing / doctor / model fit → Models;
connectors → Connectors & MCP; memory browser + privacy dashboard →
Memory; voice + quality preview → Voice; feature toggles → Agents;
web-search test → Tools; presets → General; LAN devices → Security;
usage analytics → Data; server-only `.env` table + About → Advanced /
About.

Settings inventory — every key → section (62 keys; all in
`settings_schema.js`, all resettable from the UI):

| Section | Keys |
|---|---|
| General | `language` |
| Appearance | `theme`, `density`, `fontSize`, `reduceMotion`, `accentColor`*, `fontFamily`*, `cornerRadius`*, `motionIntensity`* |
| Chat & Responses | `defaultMode` (legacy), `composerMode` (A2), `toolMode` (A2), `adaptiveDepth` (A2), `defaultTemperature`, `defaultMaxTokens`, `showThinking`, `outputStyle`, `noSlop`, `adhdFriendly`, `formality`, `expertise` |
| Models & Providers | `routingRules`, `modelCombos`, `providers.preflight_warnings` (A6), `providers.cost_ranked_routing` (A6) |
| Tools | `webSearchEnabled`, `webSearchMaxResults`, `webSearchProvider`* |
| Memory & Knowledge | `memoryAutoExtract`, `memoryRetentionDays` (A3) |
| Projects & Context | `projectMemoryScope` (A3), `projectContextTopK` (A3) |
| Agents & Automation | `agentMaxSteps`, `requireApproval`, `notifyOnDone`, `agentRuntime.defaultApprovalPolicy`, `agentRuntime.tokenBudget`, `agentRuntime.costBudgetUsd`, `agentRuntime.maxConcurrentTasks`, `agentRuntime.circuitErrorThreshold`, `agentRuntime.circuitVelocityPerMin`, `agentRuntime.circuitNoProgressSteps`, `agentRuntime.notifyOnTaskDone`, `agentRuntime.schedulerEnabled` (requires restart) — all 9 A4 keys |
| Skills & Library | `marketplace.registry_status` (A6, read-only) |
| Connectors & MCP | (no schema keys — the live connectors section renders here) |
| Voice & Audio | `voiceAutoSpeak`, `voiceId`, `voiceSpeed` |
| Image & Video | `studio.diagrams.default_accent` (A6), `studio.diagrams.default_font` (A6), `studio.classroom.mp4_export` (A6, disabled: not available) |
| Security | `LAN_ENABLED`, `LAN_ALLOW_HTTP` |
| Data & Privacy | `analyticsOptIn` |
| Appearance of code | `spec_tdd_required` (A5), `spec_greencontract_min_level` (A5), `qa_replay_strict` (A5), `code_graph_max_files` (A5), `codeTheme`* |
| Advanced | `deploy_coolify_enabled`, `deploy_coolify_url`, `deploy_quickemu_enabled`, `deploy_require_approval`, `deploy_sandbox_mode` (all A5, deferred connectors — enabling alone deploys nothing) |
| About | (no schema keys — informational section only) |

\* = added by A1. `defaultMode` is legacy (superseded by A2
`composerMode`, no remaining `getSetting('defaultMode')` consumer found)
but kept, resettable, and harmless rather than deleted silently.

Keys NOT surfaced as editable controls, and why (no fake controls):
- `MASTER_KEY` — server-only secret; never shown or editable anywhere.
- Backend `.env`-only options (`APP_NAME`, `ENV`, `APP_DEBUG`,
  `API_PREFIX`, `ALLOWED_ORIGINS`, `MAX_UPLOAD_SIZE_MB`, provider base
  URLs, `REDIS_URL`, `WEB_SEARCH_API_KEY`, `QUALITY_*` defaults,
  `FEATURE_*` flags, `SANGAM_*` scheduler/workspace roots): listed in
  Settings → Advanced as a read-only table ("set in .env, restart
  required") because the backend reads them from its environment, not
  from the user-settings blob — an editable row would silently do
  nothing. Where a live equivalent exists it is linked: provider keys
  (Models → provider keys, live-tested), web-search provider (Tools),
  quality toggles (Chat & Responses), feature toggles (Agents →
  Features), agent scheduler toggle (Agents), Ollama status (Models →
  Model Fit / Doctor). If the coordinator wants these wired for real,
  that needs a backend settings-read path first; it is not claimed here.
- `marketplace.registry_status` IS surfaced but read-only (registry is
  a labelled stub per A6); `studio.classroom.mp4_export` IS surfaced
  but disabled (no MP4 service per A6).

### 9. Design system

Tokens already existed in `css/style.css` (`--accent`, `--font-*`,
`--radius-*`, `--dur-*`, `--space-*`, `--text-*`); A1 wires
Settings → Appearance to them live in `settings/appearance.js`:
`accentColor` (validated `#rrggbb`, sets `--accent` + `--accent-rgb`,
invalid values ignored), `fontFamily` (default/system/mono →
`--font-body`), `cornerRadius` (small/medium/large → `--radius-md`),
`motionIntensity` + `reduceMotion` (→ `--dur-med`/`--dur-fast`),
`codeTheme` (auto/github-dark/github-light → highlight.js theme).
Vanilla JS SPA kept; no framework introduced. Sidebar footer
(persistent): user avatar/profile (existing), usage meter (live
`/analytics/summary`, or the honest line "Usage unavailable" /
"Usage: local only" when the endpoint is off), command-palette hint
button (Ctrl K), help button (shortcuts modal).

### 10. Dead controls fixed in the shell

- Removed: tab strip, tab picker, tool-view title bar + close button,
  composer Runs button was already gone (A2); `#runsBtn` asserted
  absent in tests.
- Fixed: `home.js`/`work.js` are now unmounted legacy modules (not
  deleted, so nothing imports a missing file; their old `showTool`
  calls resolve through the new redirects if ever re-mounted).
- Fixed (real bug, found while mounting): A3's `projects.js` and
  `memory/privacy.js` treated `apiGet`/`apiPost` as returning parsed
  JSON, but `shared/http.js` returns a Response — the codebase
  convention is `await (await apiGet(...)).json()`. Projects would
  always have shown "No projects yet" and the memory dashboard would
  have shown nothing. Fixed in both modules (+ the same pattern in
  new `destinations.js`); all other `apiGet` callers already used the
  `.json()` form.
- Fixed: runs empty state had two competing CTAs; now one.
- Not faked: video family in Studio overview shows "not available in
  this build"; image/voice families show live engine status from
  `/studio/catalog`; diagram PNG stays not-offered (A6).

## New / changed frontend modules

NEW:
- `mainfiles/frontend/js/features/shell/router.js` — destinations,
  routes, redirects, breadcrumbs (pure).
- `mainfiles/frontend/js/features/shell/palette_index.js` — palette
  index + search + coverage (pure).
- `mainfiles/frontend/js/features/shell/destinations.js` — all 8
  destination pages + segmented-page helper.

CHANGED:
- `mainfiles/frontend/js/features/tabs/tabs.js` — rewritten as the
  destination router (old tab API preserved as navigation).
- `mainfiles/frontend/js/core/nav.js` — 8 rail items, no bottom list.
- `mainfiles/frontend/js/app.js` — new renderers, Ctrl+K unbound
  (palette owns it), footer buttons wired.
- `mainfiles/frontend/index.html` — strip/title bar removed,
  breadcrumb + sidebar footer added, keyhints updated.
- `mainfiles/frontend/css/style.css` — breadcrumb, segments, footer,
  sample panel, palette group styles (appended only).
- `mainfiles/frontend/js/features/palette/palette.js` — full index.
- `mainfiles/frontend/js/shared/settings_schema.js` — 17 sections,
  A4/A5/A6 keys, A1 token keys.
- `mainfiles/frontend/js/features/settings/settings_page.js` —
  defaults/restart/readonly/unavailable rows, section param, remapped
  custom sections, empty-section note, env-info + about sections.
- `mainfiles/frontend/js/features/settings/appearance.js` — live
  token application.
- `mainfiles/frontend/js/features/setup/setup.js` — 3-step first run.
- `mainfiles/frontend/js/features/sidebar/sidebar.js` — usage meter.
- `mainfiles/frontend/js/features/agents/taskboard.js` — `opts.taskId`
  pre-selection only.
- `mainfiles/frontend/js/features/library/library.js` —
  `PROMPT_TEMPLATES` exported (no behaviour change).
- `mainfiles/frontend/js/features/chat/message_view.js`,
  `features/composer/slash.js`, `features/composer/popovers.js`
  (comment only), `features/inspector/inspector.js`,
  `features/runs/runs.js`, `features/image/image.js` — re-homing only.
- `mainfiles/frontend/js/features/projects/projects.js`,
  `features/memory/privacy.js` — `apiGet`/`apiPost` JSON fix (above).
- `tests/test_a1_shell.py` (NEW), `tests/e2e/shell.spec.ts` (NEW),
  `tests/e2e/runs.spec.ts` (navigation reworked to Agents → Run History).

## Backend routes added

NONE. No `api.py` change, no new tables, no migrations. The
`ARCHITECTURE.md` route table is therefore untouched (correctly).

## Tests run (actual, proxy env vars unset, venv `~/workspace/.venvs/sangam-full`)

- `pytest tests/test_a1_shell.py` → **6 passed** (router + palette via
  Node, shell HTML, settings-schema coverage, mounts + View-run
  re-homing, TestClient mount-target existence: `/api/projects`,
  `/api/agent-tasks`, `/api/spec-v2`, `/api/studio/catalog`,
  `/api/memory/dashboard`, `/api/extensions`, `/api/chats`,
  `/api/user/settings`, `/api/artifacts`,
  `/api/code-graph/search-v2?q=x` — all refused 401, none 404).
- Regression set in the same runs:
  `test_a1_shell + test_a2 + test_a3 + test_a4 + test_a5 + test_a6 +
  test_docs_routes_drift` → **93 passed** (drift passes: zero new
  routes, zero stale rows).
- Frontend: `node --experimental-vm-modules
  scripts/check_frontend_modules.mjs` → **ALL 71 MODULES PARSE + LINK**
  (68 before + router, palette_index, destinations).
- A real bug was caught and fixed by the new tests mid-run
  (`/settings/:section` 404ing in the router) — see §2 above.

## What A1 could NOT verify (coordinator: run at merge)

- NO Playwright/browser runs (shared ports, per task). Specs written
  for the coordinator: `tests/e2e/shell.spec.ts` (destinations, no
  strip/title bar, legacy redirects, 404 + back-to-Chat, breadcrumb
  depth, palette reach, two-click reachability, empty states,
  first-run 3-step + labelled sample + skip) and the reworked
  `tests/e2e/runs.spec.ts` (Agents → Run History). Note: the runs
  visual-regression baseline (`runs-centre.png`) will differ now that
  the tab strip is gone — regenerate it on the first merge run rather
  than treating the diff as a failure.
- Physical first-run paths (real cloud key, real Ollama install) and
  the physical phone/QR path are unchanged from before and still
  unverified here; the setup code paths are the pre-existing ones,
  extended, not replaced.
- Live model selection in step 3 depends on the models module
  refreshing after a key save; if that refresh fails, step 3's Ask
  shows the honest "Select a provider" toast and the prompt stays in
  the composer (best-effort selection is wrapped in try/catch).

## Coordinator follow-ups (do NOT silently merge past these)

1. **Old e2e specs still navigate via the deleted tab picker** and
   will fail until reworked the same way `runs.spec.ts` was:
   `devices.spec.ts`, `fit.spec.ts` (tab picker → Settings),
   `diagrams.spec.ts`, `media.spec.ts` (→ Studio/Create segments),
   `knowledge.spec.ts`, `notebooks.spec.ts` (→ Research),
   `security.spec.ts` (Work → Security segment → Agents → Security),
   `skills.spec.ts` (Work → Engineering → Code → Agent),
   `smoke.spec.ts` (knowledge + `#mainTab` references),
   `workflows.spec.ts` (Work → Workflows → Agents → Workflows).
   The new shell gives them all a working path (rail `data-nav`,
   destination `data-dest-section`, palette); the specs just need the
   click targets updated.
2. `home.js` and `work.js` remain in the tree unmounted. Deleting them
   is a coordinator call (they are referenced by nothing after this
   change except the module checker, which scans all files either way).
3. `/agents/:id` lands on the Task board with that task pre-selected
   (real detail); `/studio/:artifact` shows the artifact header from
   GET `/artifacts/:id` above the overview; `/code/:repo` and
   `/research/:notebook` land on their destination (repo/notebook id
   in the breadcrumb, detail selection inside the page) — no fake
   detail view is rendered for those two.
4. `defaultMode` (legacy composer mode) is kept in the schema although
   A2's `composerMode` supersedes it; removing it is a coordinator
   call, since older saved settings blobs may still carry it.
