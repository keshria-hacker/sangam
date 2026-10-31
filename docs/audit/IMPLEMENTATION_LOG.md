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

## 2026-10-28 — T4 / F4: workflows canvas mobile handling (P2)

- Problem (code evidence): `.wf-canvas` used `overflow: hidden` with
  140px absolute nodes laid out 220px apart, so the 3rd+ columns were
  clipped and unreachable on a phone; the edge SVG was sized to the
  visible viewport only, so edges to those nodes were clipped too;
  nodes had no `touch-action` control, so a touch drag could be
  hijacked by page scrolling; nodes are divs with `role=button` but
  had no keyboard activation.
- Change: `mainfiles/frontend/css/style.css` — canvas `overflow: auto`,
  nodes `touch-action: none`; `workflows.js` — `drawEdges()` sizes the
  SVG to the full node extent (max viewport vs. max node x+160 /
  y+80), canvas header notes scrolling on small screens, nodes gain
  Enter/Space activation with focus restored to the re-rendered node.
  No backend, node model, or drag math change (drag is delta-based,
  so it stays correct under scroll).
- Verification: `node --check` OK, frontend modules 65/65. Live
  Playwright check at 390px (temporary spec, deleted after the run):
  a 5-node workflow with the 5th node at x=900 — scrollWidth exceeds
  clientWidth, the edge layer covers x>=900, node touch-action is
  `none`, the far node becomes visible after scrolling, Enter on n1
  selects it with focus restored — 1/1 passed. Two earlier failures
  of that temporary spec were navigation errors in the spec itself
  (workflows is a section inside Work, not a picker tool; re-opening
  Work creates a duplicate tab whose hidden copy breaks the section
  locator), not canvas code; the spec was reordered to create the
  workflow before opening Workflows once.
- Not done: a full canvas rebuild (pinch-zoom, minimap, touch
  multi-select) — out of scope for this fix; desktop drag behaviour
  is unchanged.

## 2026-10-29 — T5 / F5: diagram PNG export hardening + T6 / F6: Knowledge Export (P3)

- F5 problem (code evidence): Create → Diagrams Export PNG drew the SVG
  onto a canvas sized from `img.naturalWidth || 800` (rasterised SVGs
  often report no natural size), on a transparent canvas, and a null
  `toBlob` result silently produced no download and no error.
- F5 change (`mainfiles/frontend/js/features/create/diagrams.js` only):
  explicit canvas dimensions (decoded size → SVG viewBox → width/height
  attrs → 800x600), opaque white background before drawImage, distinct
  error toasts for toBlob-null ("could not encode image"),
  canvas-unavailable, and image-load failure. SVG export untouched.
  No server raster renderer added (headless browser/cairosvg stays a
  follow-up if client rastering ever fails — it did not fail here).
- F6 problem (code evidence): Knowledge tab Export downloaded only
  GET /memory/export as sangam-memories.json; GET /code-graph/export
  existed but was never surfaced, and uploaded documents had no list
  endpoint at all (only POST /files).
- F6 change: Knowledge Export button now downloads
  sangam-knowledge-export.json bundling memories + code-graph dump +
  notebook references + uploaded-document references; each section is
  fetched independently, so one failing/unavailable section degrades to
  a note in the toast instead of failing the export. New backend
  GET /api/files (`files_routes.py`) returns references only
  (id/filename/extension/size_bytes/created_at — never stored_path or
  extracted_text); ARCHITECTURE.md §13.2 gained the matching row so
  the drift test stays green. New `tests/test_knowledge_export_files.py`
  (auth-gated, empty shape, upload-then-list, no-leak assertions).
- Test-infra note: the conftest async `auth_headers` fixture never
  creates tables ("no such table: users") and no existing test uses
  it; the new test follows the established TestClient + create_app
  pattern instead. That fixture gap is pre-existing, not fixed here.
- Verification actually exercised: frontend module check 65/65 parse+link
  (with `--experimental-vm-modules`; bare `node` fails every module
  on vm.SourceTextModule, a flag issue, not a code issue). Targeted
  tests 4/4 (3 new + drift). Permanent smoke gate 3/3 live. Live
  Playwright checks (temporary spec, deleted after the run) 2/2: PNG
  download is a real PNG with IHDR 400x300 (the stub SVG's size),
  and the Knowledge export download parses as JSON with
  memories/code_graph/notebooks/documents/exported_at keys.
- Honest limits: the real Mermaid CDN script does not load in this
  sandbox (the app itself renders "Mermaid is not loaded yet (CDN)"),
  so the live PNG check used a stubbed `window.mermaid` returning a
  real SVG — the export handler code (dimensions, background, toBlob,
  download) is what was exercised, not Mermaid itself. The CDN-load
  gap is pre-existing and out of this batch's scope.
- Full suite (29:00 run): 1628 passed, 101 skipped, 3 failed —
  test_crawl_bfs_fixture_site, test_crawl_endpoint_approval_and_pages
  (0 pages fetched, expected >= 24), test_fetch_models_from_provider_
  against_fake_server (fake server disconnects, ids == []). All three
  fail identically on the clean baseline tree (changes stashed,
  a47d06c) and have zero code-path overlap with this batch; they
  are test-harness network failures in this sandbox, not regressions.
  Per the batch rule (no push unless verification is green) the
  commit is local-only and NOT pushed; the push decision on these
  3 pre-existing failures is left to the parent.
- Not done: server-side raster renderer; fixing the 3 pre-existing
  suite failures; fixing the conftest auth fixture; palette mousemove
  re-render (F3 minor, still open).

## 2026-10-29 — Push-blocker resolution + T7 / F3: palette mousemove (P2 minor)

- Push blocker, resolved by evidence, not by waiving it: the 3
  failures from the F5/F6 full-suite run (crawl x2, omniroute
  fake-server) were re-run independently — 3/3 in isolation, 18/18
  with their two files together — then a clean full-suite rerun
  (proxy vars including NO_PROXY/no_proxy unset, TMPDIR on the main
  disk, repo `.venv`) gave **1631 passed, 101 skipped, 0 failed**
  in 24m40s (1628 + 3 new F6 tests = 1631, exact). The earlier 3
  failures were therefore full-suite flake / load interaction in
  this sandbox, not F5/F6 regressions. Commit `f2d8a04` was pushed
  on that green rerun; the earlier "push held" note is superseded.
- F3 change (`palette.js` only): the mousemove handler used to call
  `renderList()`, rebuilding the whole list DOM on every item
  crossed — the hovered button was destroyed mid-hover. It now
  updates only the selected class / aria-selected in place; the
  focus-trap comment was corrected (list re-renders on filter only).
  A grep for other mousemove/mouseenter handlers found no sibling
  re-render pattern (knowledge.js mouseenter only shows a tooltip).
- Verification: `node --check` OK, frontend modules 65/65. A live
  hover check was attempted with a temporary spec but never got
  past opening the palette in this harness (real Ctrl+P is
  swallowed by headless Chromium's print handling, and a
  dispatched keydown also did not open it in that run — the
  opening step, not the hover code, is what failed; the diagnostic
  run confirmed palette.js itself loads). The spec was deleted and
  the live check is recorded as NOT done, not claimed. The
  conftest `auth_headers` fixture gap was deliberately left alone:
  fixing it means changing how the app fixture runs lifespan/table
  creation, a test-infra refactor with regression risk for a
  fixture no existing test uses.
- Not done: server-side raster renderer; live palette hover check;
  conftest fixture refactor.

## 2026-10-29 — T8: agent CostMeter pricing (P2 correctness)

- Problem (code evidence): `run_agent` accepted `price_per_1k_usd`
  and `max_cost_usd`, but no production caller passed a price
  (`run_custom_agent` passes the saved `cost_budget` only), so the
  budget check always hit the `budget_exceeded is None` branch —
  logged as unenforceable, never enforced — and every run reported
  `cost_known: False` despite real token usage being recorded.
- Change: new `backend/providers/pricing.py` — `model_prices()` reads
  LiteLLM's bundled `model_cost` table offline (728 entries in the
  installed version), trying the id as given then with a provider
  prefix stripped (`openai/gpt-4o-mini` -> `gpt-4o-mini`); any
  failure returns None, never a made-up rate. `CostMeter` gained
  optional per-token input/output prices (precedence over the legacy
  flat rate, which still works unchanged when explicitly given) and
  reports them in its snapshot. `run_agent` resolves the run's model
  via the existing `_resolve_model` and prices the meter when no
  explicit flat rate was given; a failed lookup leaves the meter
  unpriced, exactly as before. No new dependency, no UI change, no
  route change — so the saved agent budget becomes enforceable and
  `on_usage_detail` snapshots now carry a real cost for priced
  models, while unpriced models keep reporting unknown.
- Verification: new `tests/test_cost_meter_pricing.py` 8/8
  (lookup + prefix strip, unknown-model never fabricates, per-token
  math 1000/1000 -> $0.00075, legacy flat rate unchanged,
  per-token precedence, run_agent snapshot cost $0.00045 for
  1000/500 tokens on gpt-4o-mini, budget $0.01 stops a run after a
  $0.015 first iteration, unknown model stays unknown).
  `test_deep_agent_core.py` + `test_agents.py` with the new tests:
  38/38. Drift 1/1. Frontend 65/65 (unchanged).
  Two test-authoring mistakes corrected during the run, not code:
  a single-shot answer returns before any second budget check
  (the loop's existing per-iteration semantics), and `_execute_tool`
  is async, so the fake must be async too.
- Not done: surfacing the cost snapshot in the agent SSE stream /
  UI (routes do not forward `on_usage_detail` today) and a
  per-model price override in agent config — both follow-ups, not
  part of making the existing budget enforceable.

## 2026-10-30 — T9: agent 'usage' SSE event + RunLog rendering

- Problem (code evidence): T8 made the CostMeter price runs, but
  no route forwarded `on_usage_detail`, so the snapshot never left
  the backend — the UI could show steps and answers but never a
  run's tokens or cost.
- Change: all three streaming agent routes (`/agents/{id}/run`,
  `/code-agent/run`, `/agent/run`) capture the latest cumulative
  snapshot via `on_usage_detail` and emit it as a final `usage`
  event before `end`; when no model response happened, no `usage`
  event is emitted (an absent event is honest, a zero-cost event
  would not be). `run_code_agent` gained an `on_usage_detail`
  parameter and forwards it to `run_agent`. Frontend: the shared
  `RunLog.appendStep` (used by Agents hub, Code Agent, and chat
  Agent mode, so all three surfaces get it from one change) renders
  `usage` as a tokens line — prompt/completion/total — plus the
  cost when `cost_known`, else the literal text "cost unknown
  (unpriced model)"; a `.rl-usage` style was added. No change to
  existing step kinds, so older clients ignore the new event.
- Verification: new `tests/test_agent_usage_sse.py` 3/3 via
  TestClient + create_app with the route's engine monkeypatched
  (usage before end with the exact snapshot on `/agent/run`,
  no usage event when the run fails before any response, usage on
  `/code-agent/run`); pricing + drift with the new tests 12/12;
  frontend modules 65/65. One test-authoring correction: the
  routes are auth-gated (401 without a token), so the test
  registers/logs in first, following the F6 pattern.
  Live browser rendering of the usage line was not click-checked
  here — the route tests prove the event, the module check proves
  the render code parses, the visual line itself is code-reviewed.
- Not done: per-model price override in agent config; lesson-player
  TTS wiring.

## 2026-10-31 — T10: lesson-player TTS wiring

- Problem (code evidence): `lesson_player_create` in
  `mainfiles/backend/api_routes/deep_routes.py` constructed
  `LessonPlayer` with no `narrate` argument, so the TTS hook was
  never wired in production; `play_step` returned `audio: None`
  for every speech step while still recording the text.
- Design point, resolved first: `voice.synthesize` returns raw
  bytes while `play_step` returns an audio ref, so the bytes are
  stored via the media-job precedent — `save_media_file` +
  `GET /media/{id}` — instead of a third serving mechanism.
  No in-memory store, no new engine, no new dependency.
- Change: player creation now passes
  `narrate=lambda text: _lesson_narrate(pid, text)`. The helper
  calls the already-configured voice engine, stores the bytes
  (extension picked from the mime: wav/mp3/ogg/webm/m4a), and
  returns `{media_id, url, mime_type}`. Any failure — no engine,
  empty text, engine error, empty bytes — is caught, logged, and
  degrades to `None`, so the lesson continues on text and audio
  is never fabricated. `LessonPlayer` itself is untouched and
  stays engine-agnostic.
- Verification: new `tests/test_lesson_player_tts.py` 3/3 via
  TestClient + create_app with `voice.synthesize` monkeypatched
  (audio-backed speech step serves the exact stored bytes over
  its media url; engine-failure step returns `audio: None` with
  the lesson finishing on text; mp3 mime stored and served as
  audio/mpeg). One test-authoring correction: `play_step`
  reports `done: True` only when stepping an already-finished
  lesson — the final action itself reports `done: False` with a
  finished snapshot (`mode: idle`, `finished: True`), so the
  fail-soft test asserts the snapshot, not `done`.
  Deep-knowledge + voice + drift suites 26/26 with the new
  tests; frontend modules 65/65; Playwright smoke 3/3 live
  (register/rail/popovers/settings/chat/knowledge, mobile 390px).
  No backend files beyond `deep_routes.py` changed, no frontend
  files changed.
- Not done: per-model price override in agent config (queued
  after this batch). No frontend lesson-player UI exists yet —
  nothing in `mainfiles/frontend/js/` calls the player routes —
  so the audio ref is API-available but has no playback UI
  consumer; that UI is a follow-up, not part of this wiring.
