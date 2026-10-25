# A3 — Projects, Memory & Knowledge — manifest

Branch: `spec/a3-projects-memory` (based on `integration/full-program` @ 740306f).
Worktree: `~/workspace/projects/sangam-worktrees/a3`. NOT pushed (per task).
Coordinator: mount `frontend/js/features/projects/projects.js` under the new
Projects destination and `frontend/js/features/memory/privacy.js` under
Settings → Memory & Knowledge; update ARCHITECTURE.md §13.2 route table
(the drift test will report these new routes until the table is updated —
that file is coordinator-owned, deliberately untouched here).

## New routes (all on the authenticated `/api` router)

Projects (`mainfiles/backend/api_routes/projects_routes.py`):

| Method | Path | Notes |
|---|---|---|
| POST | /projects | Create; `memory_scope` project (default) \| global |
| GET | /projects | Excludes soft-deleted |
| GET | /projects/{id} | Home summary: instruction, counts (sources/tasks/open/chats) |
| PUT | /projects/{id} | Name/description/memory_scope |
| DELETE | /projects/{id} | Soft-delete; `?hard=true` permanently removes project rows and unlinks (never deletes) its tasks/chats |
| POST | /projects/{id}/instructions | New version supersedes current |
| GET | /projects/{id}/instructions | `{current, history}` |
| POST | /projects/{id}/sources | file (must exist) / url (ingest-on-add, SSRF-guarded, deduped) / chat (must exist); excluded URL sources skip fetch |
| GET | /projects/{id}/sources | Excludes soft-deleted |
| PUT | /projects/{id}/sources/{sid}/context | excluded/summary/full; un-exclude ingests a skipped/failed URL source |
| DELETE | /projects/{id}/sources/{sid} | Soft-delete |
| POST | /projects/{id}/tasks | REUSED goals Task (project_id set, goal_id NULL) |
| GET | /projects/{id}/tasks | |
| PATCH | /projects/{id}/tasks/{tid} | Title/description/priority/status (shared `set_task_status`, 422 on unknown status) |
| POST | /projects/{id}/chats | Chat row with `project_id` set |
| GET | /projects/{id}/chats | Only this project's chats |
| GET | /projects/{id}/context | Instruction + scoped retrieval (q) or stored source texts (no q) + open tasks + chats |
| GET | /projects/{id}/retrieve | Hybrid retrieval over ONLY this project's file ids + corrective grade/rewrite; citations carry grade + provenance "verified"; deliberately NO graph expansion and NO web fallback (both would break scoping) |

Memory (`mainfiles/backend/api_routes/memory_routes.py`):

| Method | Path | Notes |
|---|---|---|
| GET | /memory/dashboard | Stats + rooms + first 200 memories + retention preview (`?older_than_days=N`) + conversation-vs-persistent separation (live chat/message counts). Retention itself runs through existing POST /memory/forget (confirm + filter required) — no second deletion path. |

Changed (no new path, behaviour only):

- GET /knowledge/retrieve — response gains `graph_expansion` (entity + 1-hop
  memory-graph relations whose entity tokens appear in the query, each
  `provenance: "inferred"`); chunk citations gain `provenance: "verified"`;
  web-fallback citations gain `provenance: "inferred"`. Corrective
  grade/rewrite loop unchanged, now shared by project retrieve.
- GET /knowledge/graph — response gains `backlinks`: `{node_id: [linking node ids]}`.
- Notebook PUT /notebooks/{id}/sources/{sid}/context — un-excluding a URL
  source now ingests it (previously it stayed text-less forever).
- Chat stream file path — now `retrieve_hybrid_chunks` (was vector-only).
- Notebook `_full_source_text` (file + URL paths) — now `retrieve_hybrid_chunks`
  (was vector-only), falling back to stored text as before.

## New/changed frontend modules

- NEW `mainfiles/frontend/js/features/projects/projects.js` —
  `renderProjectsView(containerEl)` (list → home) and
  `renderProjectHome(containerEl, projectId)`; sections Overview /
  Instructions / Sources / Tasks / Chats + project-scoped retrieve box
  showing grade + provenance per citation. Destination-agnostic: no tab
  id, sidebar entry, or route assumed.
- NEW `mainfiles/frontend/js/features/memory/privacy.js` —
  `renderMemoryDashboard(containerEl)`; stats, separation explainer,
  per-memory delete, retention preview + bulk forget (confirm-gated),
  JSON export.
- CHANGED `mainfiles/frontend/js/features/knowledge/knowledge.js` —
  node detail panel shows a "Linked from" backlinks section from
  `graphData.backlinks` (no other behaviour change).
- CHANGED `mainfiles/frontend/js/shared/settings_schema.js` — 3 new keys
  (see below). Frontend check: 65/65 modules parse + link.

## New settings keys (for the coordinator's Settings center)

| Key | Label | Description | Default | Section |
|---|---|---|---|---|
| `memoryRetentionDays` | Memory retention (days) | Dashboard forget preview uses this many days by default. 0 = keep memories forever; nothing is auto-deleted. | `0` (number, 0–3650) | Memory & Knowledge |
| `projectMemoryScope` | Default project memory scope | New projects retrieve only their own sources (project) or all uploads (global). Per-project override on the project itself. | `project` (select: project/global) | Memory & Knowledge |
| `projectContextTopK` | Project retrieval results | How many chunks project-scoped retrieval returns. | `5` (number, 1–20) | Memory & Knowledge |

Note: `memoryRetentionDays` is advisory only — there is intentionally no
auto-delete job. The dashboard preview + confirm-gated forget is the
control; a silent background deleter would violate the privacy rules.

## DB / model changes

- NEW tables (registered on import of `projects_routes`, notebooks
  precedent; created by `create_all`): `projects`, `project_sources`,
  `project_instructions` — all with `created_at`/`updated_at`;
  `projects` and `project_sources` also have `deleted_at` (soft-delete).
- `chats.project_id` (nullable VARCHAR(32), NULL = unscoped/legacy) —
  in `models.py`, plus an idempotent ALTER in
  `database._add_missing_columns` for existing SQLite DBs.
- `tasks.project_id` (nullable VARCHAR(32), NULL = goal/global task) —
  in `goal_models.py`, plus an idempotent ALTER in
  `database._add_missing_columns`. DECISION (documented, per task):
  project tasks REUSE the goals Task system — no duplicate task table,
  lifecycle, or status machine. `task_out` now also returns `project_id`.
- No other tables touched. No migration files (repo uses `create_all` +
  `_add_missing_columns`, same pattern as prior waves).

## Exactly what changed in api.py

One import+register block only (after the memory_v2 import, before the
doctor router): imports the projects_routes handlers
(`add_project_instruction`, `add_project_source`, `create_project`,
`create_project_chat`, `create_project_task`, `delete_project`,
`delete_project_source`, `get_project`, `get_project_context`,
`list_project_chats`, `list_project_instructions`, `list_project_sources`,
`list_project_tasks`, `list_projects`, `retrieve_project`,
`set_project_source_context`, `update_project`, `update_project_task`).
Importing the module registers all `/projects/*` routes on the shared
router. No other api.py change.

## Other files changed (all in this worktree)

- `mainfiles/backend/hybrid_retrieval.py` — `make_citation` adds
  `provenance: "verified"` (grounded stored chunk; "inferred" is reserved
  for graph/web signals, which label themselves).
- `mainfiles/backend/knowledge_graph.py` — `build_knowledge_graph`
  returns `backlinks` reverse index.
- `mainfiles/backend/api_routes/knowledge_routes.py` — `graph_expansion_for_query`
  helper; provenance labels; `graph_expansion` in retrieve response.
- `mainfiles/backend/api_routes/chat_stream_routes.py` — hybrid retrieval
  for attached files (import + call only).
- `mainfiles/backend/api_routes/notebooks_routes.py` — hybrid retrieval
  in `_full_source_text` (2 sites); ingest-on-unexclude in
  `set_source_context`.
- `mainfiles/backend/api_routes/memory_routes.py` — GET /memory/dashboard.
- `mainfiles/backend/models.py`, `goal_models.py`, `database.py` — see DB section.
- `tests/test_a3_projects_memory.py` — 13 new tests (see below).

## Tests (actual runs, proxies unset, venv `~/workspace/.venvs/sangam-full`)

- NEW `tests/test_a3_projects_memory.py`: **13 passed** (project CRUD +
  soft/hard delete, instruction versioning, task reuse + 422 + cross-project
  404, chat scoping, source dedupe/404/422, scoping proof incl. hybrid
  call-arg file ids, hybrid provenance unit, graph backlinks unit,
  knowledge retrieve provenance + graph expansion, notebook URL retrieve,
  notebook excluded→full ingest, dashboard shape + retention preview,
  chat-stream hybrid wiring guard).
- Regression (touched areas): `test_phase2_hybrid_retrieval.py`,
  `test_phase2_remainder.py`, `test_deep_knowledge.py`, `test_memory.py`,
  `test_batch4_memory.py`, `test_rag.py`, `test_deep_memory_chat.py` —
  **140 passed, 0 failed** (single run, 135.96s). Combined with the 13
  new tests: 153 passed across all touched areas.
- Frontend: `node --experimental-vm-modules scripts/check_frontend_modules.mjs`
  → **ALL 65 MODULES PARSE + LINK** (incl. 2 new + edited knowledge.js).

## Specs the coordinator should run at merge time (not run here — shared ports)

- Any Playwright spec covering Projects (new), Knowledge graph (backlinks
  panel), and Memory dashboard, plus the full pytest suite and the docs
  drift test AFTER updating ARCHITECTURE.md §13.2 with the routes above.
  Smoke/Playwright were deliberately not run by this specialist (shared
  :8001/:5500).

## Partial / blocked / not verified (honest list)

- Project retrieve/context were verified with mocked hybrid retrieval
  (call-arg scoping) plus real stored-text context; a live Chroma-backed
  project retrieve was NOT run here (Chroma query path is the same
  `retrieve_hybrid_chunks` already covered by Phase 2 tests).
- Global `/knowledge/retrieve` graph expansion surfaces the user's
  memory-graph relations; it is intentionally NOT in project retrieve
  (would leak cross-project entities). Project-scoped entity expansion
  would need project-linked entities, which do not exist yet.
- `memoryRetentionDays` is advisory (see settings note); there is no
  scheduled auto-forget, by design.
- Persistent memory itself is user-wide (single-user Chroma store);
  project "memory scope" governs retrieval/context assembly, not a
  separate memory partition. The dashboard states the separation
  honestly (chat deletion ≠ memory deletion).
- Physical-browser verification of the two new frontend modules was not
  run (shared ports; coordinator runs Playwright at merge).
- The docs drift test will fail until the coordinator adds the 18 new
  project routes + 1 dashboard route to ARCHITECTURE.md §13.2.
