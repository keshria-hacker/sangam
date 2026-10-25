# A6 — Studio, Skills & Integrations — MANIFEST

Branch: `spec/a6-studio-skills` (based on `integration/full-program` @ 740306f).
Worktree: `~/workspace/projects/sangam-worktrees/a6`. NEVER pushed (per task).
Main checkout, other specialists' areas, and `docs/ARCHITECTURE.md` /
`README.md` / `FIX_LOG.md` were NOT touched.

## What this branch does (and what it deliberately does NOT do)

It finishes Partial features and fills gaps; it rewrites nothing that
worked. All 11 providers stay supported. Voice cloning and video
production have NO endpoint here (user-skipped). No fake outputs:
image/voice go through the pre-existing real engines; PNG diagram
export is refused with 422 (no raster renderer here) instead of faked;
the marketplace registry source is a labelled STUB, never presented
as working.

## New / changed routes (all on the shared router; one import block in api.py)

| Method | Path | Notes |
|---|---|---|
| GET | /api/providers/capability-registry | 11 providers, 16 curated models, per-model flags; unknown = `capabilities_known: false`, never guessed |
| GET | /api/providers/contract-check | All 11 adapters report `contract_ok: true` for the 7 contract methods |
| POST | /api/providers/preflight | `{provider, model, wanted[]}` → "This model can't do X" warnings + `blocked[]` |
| POST | /api/providers/cost-ranked | Cheapest-first; unknown price last with `cost_known: false` |
| GET | /api/studio/catalog | 7 families + real engine status; video `available: false` |
| POST | /api/studio/documents/proof | Generates docx/pdf/pptx/xlsx AND parses it back (python-docx / python-pptx / openpyxl / %PDF), returns sha256 |
| POST | /api/diagrams/export | Node/edge spec → self-contained SVG or HTML; PNG → 422 |
| POST | /api/studio/classroom/generate | Topic/source → slides + quiz + interactive HTML + PBL; skeleton path labelled `source_based: false`; MP4/slide-editor NOT offered |
| GET | /api/marketplace/sources | local (working), git (working-via-local-clone), registry (**stub**) |
| POST | /api/marketplace/packs/{pack}/dry-run | Files + SHA-256 preview, writes nothing |
| POST | /api/marketplace/packs/{pack}/install | Hash-verified install + supply-chain scan + lockfile verification |
| GET | /api/connectors/{name}/health | configured/connected; token field always null |
| GET | /api/connectors/{name}/permissions | Requested vs granted scopes, encrypted-at-rest note, revoke path; no token value ever |
| POST | /api/compare/blind | Same prompt, outputs labelled A/B only (mock-tested, no model) |
| POST | /api/compare/blind/vote | Reveals winner, records an ArenaResult row; existing /arena/leaderboard then shows it |

Pre-existing routes reused unchanged: `/api/diagrams/catalogue|lint|brands|import`
(now 44 types), `/api/skills/*` (install/dry-run/verify/scan/checks/pin/
recommend/documents/generate), `/api/connectors` (list/authorize/callback/
DELETE revoke), `/api/compare` + `/api/compare/stream` + arena vote/
leaderboard, `/api/models/*` fit advisor, `/api/voice/*`, `/api/image/*`.

### api.py change (exactly one block)

`mainfiles/backend/api.py`: one import — `from .api_routes import
a6_studio_routes` — next to the other route-module imports. No other
api.py edits.

## New / changed frontend modules

- NEW `mainfiles/frontend/js/features/studio/a6-studio.js` — dependency-free
  hooks for the shell agent (A1) to mount under Studio: `a6PreflightWarnings`
  (mirrors server warning wording), `a6CostRanked` (mirrors server ranking),
  `A6_STUDIO_FAMILIES`. NOT wired into index.html/sidebar — A1 owns the shell.
- Frontend check: `node --experimental-vm-modules scripts/check_frontend_modules.mjs`
  → ALL 64 MODULES PARSE + LINK (was 63; +1 is this file).

## New settings keys (for the coordinator's Settings center — not yet wired to storage)

| Key | Label | Description | Default | Section |
|---|---|---|---|---|
| studio.diagrams.default_accent | Default diagram accent | Single accent colour applied to new diagrams and SVG exports | #3A7BD5 | Studio |
| studio.diagrams.default_font | Default diagram font | Font family for diagram text | Inter, system-ui, sans-serif | Studio |
| providers.preflight_warnings | Model capability warnings | Show "this model can't do X" before sending when the model lacks a requested capability | true | Models & Providers |
| providers.cost_ranked_routing | Cost-ranked fallback | Order fallback candidates cheapest-first; unknown prices sort last, never as cheap | true | Models & Providers |
| marketplace.registry_status | Skill registry status | Read-only: remote registry is a stub in this build; local/git sources only | stub | Skills & Library |
| studio.classroom.mp4_export | Classroom MP4 export | NOT OFFERED — no MP4 export service in this build | off (unavailable) | Studio |

## DB / model changes

NONE. No new tables, no migrations. Blind-compare mappings are in-memory
only (restart drops them — documented on the vote endpoint); brands,
ArenaResult, ProviderKey, and skill lockfiles are all pre-existing.

## Code changes (files)

- NEW `mainfiles/backend/providers/contract.py` — adapter contract checker,
  capability registry (compat PROVIDERS + CURATED_MODELS + static configs),
  `preflight()`, `cost_ranked_route()`, `check_adapters()`.
- EDIT `mainfiles/backend/providers/base.py` — BaseProvider gains the six
  contract methods: `capabilities()`, `stream()` (alias), `tools()`,
  `reasoning()`, `citations()`, `normalize_error()` (delegates to the
  existing `response_events.normalize_error`; 429 → rate_limit/retryable,
  401/403 → authentication_error). Per-model flags come from ModelInfo;
  no model → streaming-only default, never invented support.
- EDIT `mainfiles/backend/diagrams.py` — catalogue 13 → **44 unique types**
  (Mermaid starters, same convention as the original 13; `heatmap`,
  `comparison`, `matrix` starters were cut to land exactly on 44).
- NEW `mainfiles/backend/studio_svg.py` — deterministic stdlib SVG/HTML
  renderer for node/edge specs (4px-grid layout, one accent, unknown
  edge endpoints dropped and counted, never invented).
- NEW `mainfiles/backend/studio_classroom.py` — classroom template
  generator (slides grounded in the caller's source sentences, quiz with
  valid answer index, interactive HTML, PBL milestones).
- NEW `mainfiles/backend/api_routes/a6_studio_routes.py` — all routes above.
- EDIT `mainfiles/backend/api.py` — one import block (see above).
- NEW `mainfiles/backend/skills/packs/creative-design/` — the third approved
  pack: `pack.yaml` (v1.0.0) + skills `editorial-diagrams`,
  `art-direction`, `ui-craft` (SKILL.md frontmatter passes the authoring
  contract: 6 checks passed, 0 failed each; 3 skipped = no evals/scripts).
- EDIT `mainfiles/backend/skills/packs/science-essentials/pack.yaml` —
  description only: now states explicitly it is a CURATED SLICE of 5
  skills, not an import of all 177 scientific-agent-skills, and cites the
  authoring contract.
- NEW `mainfiles/frontend/js/features/studio/a6-studio.js` (above).
- NEW `tests/test_a6_studio_skills.py` — 23 tests (see below).

## Verified by actual runs (proxies unset, venv `~/workspace/.venvs/sangam-full`)

- `pytest tests/test_a6_studio_skills.py` → **23 passed** (includes:
  docx/pptx/xlsx parse-back with real libraries, SVG parsed as XML,
  44-type catalogue, pack dry-run writing nothing, pack install +
  lockfile verify OK for engineering / science-essentials /
  creative-design, blind vote → Arena leaderboard row, connector
  health/permissions with no token value).
- Touched-area regression → **75 passed**:
  `test_batch5_skills`, `test_batch7_writing_diagrams_images`,
  `test_batch7_fit`, `test_compare_arena`, `test_deep_skills`.
- Frontend modules → **64/64 parse + link**.
- Skill authoring checks for the 3 new Creative/Design skills → 6 passed,
  0 failed each. Pack list shows `creative-design` v1.0.0 (disabled by
  default, like other packs; enable via existing `/skills/packs/{name}/enable`).

## Known drift for the coordinator (intentional, boundary-owned)

`test_docs_routes_drift` fails ONLY on the 15 new routes above (all
"live routes missing from §13.2", zero stale rows). I did not edit
`ARCHITECTURE.md` per the task boundary — the coordinator's §13.2
update at merge time must add exactly these 15 rows (method + path as
listed in the routes table above, with `{}` path params as the test
normalises them).

## Partial / blocked / not verified (honest list)

- **Diagrams PNG export — NOT offered.** No raster renderer (cairosvg /
  headless browser) in this environment. SVG/HTML export is real;
  browser-side Mermaid PNG remains the existing path. Not faked.
- **Catalogue templates are Mermaid starters**, not pre-rendered
  HTML+SVG per type (same convention as the original 13). Rendered
  self-contained HTML+SVG is provided for node/edge specs via
  `/diagrams/export`; template→SVG conversion still happens in the
  browser via Mermaid (pre-existing UI path, not re-verified here).
- **Blind-compare mappings are in-memory** (restart drops them, same
  precedent as pending LAN pairings). Voting/leaderboard reuse the real
  ArenaResult table; only the label→model map is volatile.
- **Registry source is a stub** (labelled in API + this MANIFEST).
  Local + git-via-local-clone sources work.
- **Model fit advisor extended, not rewritten**: hardware-aware
  `fit_score`/`recommend` verified (fits vs does-not-fit incl.
  weights/kv-cache bottleneck); VRAM math already existed in
  `model_fit.py` and was left as-is.
- **Image/voice "work through a real engine"** rests on the pre-existing
  engines + 503-when-absent behaviour: no engine was installed in this
  environment, so no real image/audio bytes were generated here.
  `/studio/catalog` reports their live status honestly instead.
- **Physical / browser verification NOT done by A6** (shared ports):
  no smoke/Playwright runs. Coordinator, please run at merge time:
  `tests/e2e/` specs for library (skill packs install), diagrams
  (catalogue + export), image, voice, compare/arena, and the new
  Studio mounting (once A1 mounts `a6-studio.js`), plus the full
  pytest suite after the §13.2 update.
- **Science pack is a 5-skill curated slice**, documented as such;
  importing all 177 science skills / 100+ templates as tabs was
  explicitly out of scope and not done.
- **Design**: no new deliverable types were built; the existing Design
  Studio module + DESIGN.md are referenced from `/studio/catalog`.
  The 11+ deliverable types claim rests on the pre-existing studio and
  was not re-audited here.
