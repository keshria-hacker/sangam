# A5 MANIFEST — Code, Spec & QA (perfect-flow program)

Worktree: `~/workspace/projects/sangam-worktrees/a5`, branch
`spec/a5-code-spec-qa`, based on `integration/full-program @ 740306f`.
NEVER pushed (per task). The old spec chain
(`/engineering/*/chain/*`, `backend/spec_chain.py`) is UNTOUCHED for
backward compatibility; the v2 pipeline below reuses its validators
(`validate_spec`, `validate_plan`, `validate_tasks`,
`validate_analysis`, `analyze_coverage`) and adds the stages it lacked.

## 1. New / changed routes (20 new, 0 changed, all on shared router, auth required)

All in `mainfiles/backend/api_routes/spec_qa_routes.py`, registered by
the single api.py import block (§5).

Spec pipeline v2 (`/api/spec-v2/*`) — full enforced order
constitution → spec → clarify → plan → checklist → tasks → analyze →
implement → verify → converge (converge is terminal):

| Method | Route | Notes |
|---|---|---|
| POST | `/api/spec-v2` | Create pipeline |
| GET | `/api/spec-v2` | List pipelines |
| GET | `/api/spec-v2/{pid}` | Pipeline + stage artifacts |
| GET | `/api/spec-v2/{pid}/artifacts` | Artifact store view (DB rows) |
| POST | `/api/spec-v2/{pid}/advance` | Advance one stage; 422 on out-of-order / failed gate. Clarify writes answers back into the stored spec. Implement requires TDD-OK evidence for every task; verify requires a passing `targeted` GreenContract record; converge requires a convergence report addressing every gap. |
| POST | `/api/spec-v2/{pid}/tasks/{task_id}/evidence` | TDD evidence (RED + GREEN outputs for one test command); 422 if RED shows no failure or GREEN shows no clean pass / still fails |
| POST | `/api/spec-v2/{pid}/verify-record` | GreenContract record; graduated: `package` needs `targeted` passed first, etc. |
| POST | `/api/spec-v2/{pid}/review-package` | BASE/HEAD diff package from task evidence diffs; 422 on empty diff |
| POST | `/api/spec-v2/{pid}/review/{axis}` | axis `spec`\|`quality`; artifact must reference its review_package_id (same teeth as old chain) |
| GET | `/api/spec-v2/{pid}/review-pr` | PR-style review artifact: changed files + per-axis verdicts + overall + full diff |
| POST | `/api/spec-v2/{pid}/converge-report` | Computed convergence report + gap list (uncovered FRs, tasks without TDD-OK evidence, empty-diff tasks, failed verifications) with follow-up tasks per gap |

QA (`/api/qa/*`):

| Method | Route | Notes |
|---|---|---|
| GET | `/api/qa/levels` | GreenContract levels + descriptions |
| POST | `/api/qa/normalize` | Noise-normalize a JSON body (timestamps/UUIDs/hex ids + named noise fields) |
| POST | `/api/qa/report` | Report from results + untested list; returns counts, case lists, and markdown |

Code-graph extensions (`/api/code-graph/*`, additive only; existing
code-graph routes file untouched):

| Method | Route | Notes |
|---|---|---|
| GET | `/api/code-graph/cycles` | Circular-import cycles in the file→file import graph |
| GET | `/api/code-graph/architecture` | Languages, directories, hubs (by caller count), entry points (exported, no callers) |
| GET | `/api/code-graph/impact` | `?target=<symbol>` or `?target=file:<relpath>` — transitive callers + importers |
| GET | `/api/code-graph/search-v2` | `?q=&regex=&top_k=` — grep hits + graph results, graph+grep ranked first |

Deploy interface (`/api/deploy/*`, status only — NO deploy endpoint by design):

| Method | Route | Notes |
|---|---|---|
| GET | `/api/deploy/connectors` | Coolify + Quickemu, both `status: "deferred"` |
| GET | `/api/deploy/permissions` | `?role=owner|lan_device` — permission matrix (owner: all, lan_device: none) |

## 2. New / changed frontend modules

| Module | Change |
|---|---|
| `mainfiles/frontend/js/features/code-agent/spec-qa.js` | NEW, unmounted. Exports `SPEC_V2_STAGES`, `specQaPanelHtml(pipeline)`, `fetchSpecPipeline`, `fetchQaLevels`. No imports, so it parses/links standalone. NOT wired into the shell/tabs — A1 (shell) owns mounting it in the Code destination at merge time. |
| (no existing frontend module changed) | — |

Frontend check: `node --experimental-vm-modules scripts/check_frontend_modules.mjs`
→ `ALL 64 MODULES PARSE + LINK` (was 63; +1 is spec-qa.js).

## 3. New settings keys (for the coordinator's Settings center)

Declared here; defaults match current behaviour. No route currently
reads the generic user-settings blob (same pattern as the existing
generic settings store — the coordinator wires these into
settings_schema.js and any future read path).

| Name | Label | Description | Default | Section |
|---|---|---|---|---|
| `spec_tdd_required` | Require TDD evidence | Spec v2 implement stage requires RED + GREEN test evidence for every task; a green-only claim is rejected. | `true` | Code, Spec & QA |
| `spec_greencontract_min_level` | Minimum verification level | Lowest GreenContract level that must pass before the verify stage (`targeted` / `package` / `integration` / `full`); levels are cumulative. | `"targeted"` | Code, Spec & QA |
| `qa_replay_strict` | Strict replay comparison | Replay compares status and noise-normalized body exactly; any drift fails the case instead of warning. | `true` | Code, Spec & QA |
| `code_graph_max_files` | Code graph file cap | Maximum files indexed per graph build (existing `build_graph` default). | `500` | Code, Spec & QA |
| `deploy_coolify_enabled` | Coolify connector | Enable the (deferred) Coolify deploy connector. Off until implemented; enabling it alone deploys nothing. | `false` | Deploy |
| `deploy_coolify_url` | Coolify instance URL | Base URL of the Coolify instance to deploy to, when implemented. Empty = unconfigured. | `""` | Deploy |
| `deploy_quickemu_enabled` | Quickemu VM / sandbox launch | Enable the (deferred) Quickemu VM/sandbox launcher (developer mode only when implemented). | `false` | Deploy |
| `deploy_require_approval` | Require approval per deploy | Every deploy or VM launch must be explicitly approved before it runs, even for the owner. | `true` | Deploy |
| `deploy_sandbox_mode` | Sandbox mode for generated apps | `preview` (sandboxed preview only) or `isolated` (isolated VM/sandbox when available). | `"preview"` | Deploy |

## 4. DB / model changes (new tables only; no existing table altered)

In `mainfiles/backend/spec/models.py` (registered on `Base.metadata` on
import via the routes module; fresh-DB tests call `create_all`):

- `spec_v2_pipelines` (id, title, goal, current_stage, created_at)
- `spec_v2_stages` (id, pipeline_id FK, stage, artifact, position, created_at)
- `spec_v2_task_evidence` (id, pipeline_id FK, task_id, diff, test_command, red_output, green_output, tdd_ok, created_at)
- `spec_v2_review_packages` (id, pipeline_id FK, base_ref, head_ref, diff, created_at)
- `spec_v2_reviews` (id, pipeline_id FK, axis, verdict, review_package_id, artifact, created_at)
- `spec_v2_verifications` (id, pipeline_id FK, level, test_command, output, passed, created_at)

No changes to `engineering_pipelines`, `spec_chain_artifacts`,
`pipeline_task_runs`, or any other existing table.

## 5. Exactly what changed in api.py (one import + register block)

`mainfiles/backend/api.py`, after the engineering_routes import:

```python
# A5 (spec v2 / QA / code-graph extensions / deploy interface):
# importing this module registers its routes on the shared router.
from .api_routes import spec_qa_routes  # noqa: F401
```

No other api.py change. No change to `ARCHITECTURE.md`, `README.md`,
or `FIX_LOG.md` (coordinator-owned, per task).

## 6. Other code changes

- `mainfiles/backend/code_graph.py` — extractor version `codegraph-v2` →
  `codegraph-v3` (cache namespace now includes the extra extractor id,
  so old caches invalidate); discovery + extraction + import resolution
  extended to `.go`, `.rs`, `.java`; language counts per file use the
  new suffix map. Python/JS/TS paths untouched.
- `mainfiles/backend/code_graph_queries.py` — ADDED ONLY (no existing
  function edited): `circular_imports`, `architecture_overview`,
  `change_impact`, `search_code_v2`. Existing `trace_calls`,
  `find_path`, `affected`, freshness gate untouched.
- NEW `mainfiles/backend/code_extract_extra.py` — Go/Rust/Java regex
  extractors (same defs/calls/imports schema as JS extractor).
  Honest language claim: Python, JavaScript/TypeScript, Go, Rust,
  Java — exactly 5 families, each with a test. NO tree-sitter, NO
  160-language claim.
- NEW `mainfiles/backend/spec/` — `checklist.py` (C-ids, FR + method
  required, every FR covered), `tdd.py` (RED/GREEN validation),
  `state_machine.py` (10-stage order + per-stage gates),
  `converge.py` (gap detection + follow-up tasks + report validation),
  `review.py` (PR-style markdown), `store.py` (filesystem artifact
  store: `<root>/<pipeline_id>/{constitution,spec,clarify,plan,
  checklist,tasks,analyze,implement,verify,converge-report,review-pr}.md`,
  atomic writes, id confined under root), `models.py` (§4).
- NEW `mainfiles/backend/qa/` — `noise.py` (timestamps/UUIDs/hex ids +
  named noise fields), `recorder.py` (JSON cassettes, secret redaction,
  `record_response` through a TestClient), `replay.py` (re-issue +
  normalized compare, skipped cases stay skipped), `report.py`
  (passed/failed/skipped/untested with counts + case lists + markdown),
  `greencontract.py` (cumulative levels), `pytest_gen.py` (one test
  per case; skipped cases become `pytest.skip`; cassette JSON sits
  beside the generated file; repo root via `SANGAM_REPO_ROOT` or
  `tests/` placement).
- NEW `mainfiles/backend/deploy_interface.py` — `DeployConnector`
  interface, `AppPackage`/`DeployTarget`/`DeployResult`,
  `DeployPermission` enum + `DEFAULT_GRANTS` (owner: all, lan_device:
  none), `DEPLOY_SETTINGS`, `list_deploy_connectors` (both deferred).
  NO core module imports it; NO live Coolify/Quickemu call exists.
- NEW `tests/test_a5_spec_qa.py` — 14 tests (see §7).

## 7. What was verified (actual runs, proxy env unset)

- `pytest tests/test_a5_spec_qa.py -q` → **14 passed** (incl. the
  sample end-to-end below and a generated pytest file executed green
  in a fresh subprocess: `1 passed`).
- `pytest tests/test_deep_pipeline.py tests/test_deep_codegraph.py -q`
  → **49 passed** (old chain + old graph untouched behaviour).
- Frontend check → **64 modules parse + link** (see §2).
- Sample end-to-end (in `test_spec_v2_sample_end_to_end`): spec for
  `greet` + `add` → checklist → tasks → analyze → REAL pytest RED
  (`FAILED … AssertionError`) on a throwaway sample repo → REAL
  GREEN (`1 passed`) after implementing → TDD evidence accepted via
  API (green-as-red rejected with 422) → implement → GreenContract
  (`package` before `targeted` rejected 422; `targeted` passed) →
  verify → review package → spec+quality passes → PR review artifact
  (`Overall: PASS`, files listed) → converge report with **0 gaps**
  → converge → artifact list shows all 10 stages in order, and the
  filesystem `ArtifactStore` round-trips `converge-report.md`.

## 8. Known gaps / coordinator actions (do NOT silently fix at merge)

1. **Drift test WILL fail at merge until §13.2 is updated.**
   `pytest tests/test_docs_routes_drift.py` currently fails ONLY on
   the 20 new routes in §1 missing from `ARCHITECTURE.md §13.2`
   (coordinator-owned file, not touched here). Add exactly those 20
   rows; no stale rows were introduced.
2. **Frontend module unmounted** (see §2): A1 must mount `spec-qa.js`
   in the Code destination; until then the panel is available but not
   reachable from the UI.
3. **Specs the coordinator should run at merge (shared ports, not run
   here):** no Playwright spec exists for spec-v2/QA yet. Suggested
   browser check at merge time: open the Code destination, mount the
   spec-qa panel, and drive one spec-v2 pipeline through the panel
   (create → advance through checklist → evidence → converge).
   Smoke/Playwright were deliberately NOT run in this worktree (shared
   `:8001`/`:5500`).
4. **Not verified here:** call-path query latency on a medium repo
   (no medium-repo timing run was done — no `<10 ms` claim is made);
   physical deploy to Coolify/Quickemu (deferred by user decision);
   QA replay against an app requiring non-bearer auth flows (replay
   supplies fresh headers at replay time; cookie/CSRF flows are not
   recorded by design).
5. **Language-extractor limits (stated in module docstrings):** Go
   imports parsed from original lines (masking blanks string literals);
   Rust `fn` found anywhere on a line (covers single-line impls);
   Java methods require a visibility/static modifier (package-private
   modifier-less methods are not extracted); calls attributed to the
   nearest preceding definition. No other languages are claimed.
