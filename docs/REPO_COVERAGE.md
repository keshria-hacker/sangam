# REPO_COVERAGE.md — Honest Integration Assessment

**Date:** 2026-10-09 (Phase 7)
**Branch:** `integration/full-program`
**Method:** Code inspection + test verification + UI reachability. A feature counts as **Done** only if it is reachable from the UI AND covered by a test or screenshot.

## Status Key
- **Done**: Reachable from UI, tested (pytest or Playwright), verified working
- **Partial**: Core exists but gaps remain (listed)
- **Missing**: Not built
- **Skip**: Intentionally deprioritized (reason given)

---

## 22-Repo Coverage

| # | Repo | Status | Evidence |
|---|------|--------|----------|
| 1 | ayghri/i-have-adhd | Done | `QUALITY_ADHD_FRIENDLY` in output postprocessor; 15 tests; Settings UI toggle |
| 2 | petergyang/no-ai-slop | Done | `QUALITY_NO_SLOP` removes 20+ slop patterns; tested; Settings UI toggle |
| 3 | MemPalace/mempalace | Done | Typed memories (episodic/semantic/procedural), importance-ranked recall, consolidation; Knowledge tab Rooms/List browser; 17 tests; Playwright golden-3 |
| 4 | OpenHands/OpenHands | Done | Code agent with write_file/edit_file/run_bash, SSE streaming, TDD mode, approval gate; Code tab UI; `test_agent_engine.py` |
| 5 | nexu-io/open-design | Done | Design Studio tab with prototype gen + sandboxed iframe preview + refine; `renderDesignTab` |
| 6 | stablyai/orca | Done | Agent teams with fan-out/fan-in, **SSE per-specialist streaming** (`/teams/run/stream`), **per-agent Stop** (`/teams/stop-agent`) and Retry; Teams tab with live cards; `test_teams_streaming.py` (4 tests) |
| 7 | K-Dense-AI/scientific-agent-skills | Done | `science-essentials` skill pack bundled; pack system with enable/disable; Library UI |
| 8 | THU-MAIC/OpenMAIC | Done | Learning mode: teacher lessons, Socratic tutor, **editable outline** (`/learn/outline`), **quiz + grading** (`/learn/quiz`, `/learn/grade`); Learn tab UI; 7 tests |
| 9 | DeusData/codebase-memory-mcp | Done | MCP client; `code_graph.py` builds AST graph (918 symbols); Code map UI in Code tab |
| 10 | earendil-works/pi | Done | Agent loop patterns; `agent-loop` skill pack; Library UI |
| 11 | debpalash/VoiceStudio | Done | Local TTS/STT (kokoro, faster-whisper, OpenAI-compatible); `/api/voice/*`; **Voice Studio tab** (TTS/STT playground); 9 tests. Note: VoiceStudio server is separate (per license) |
| 12 | diegosouzapw/OmniRoute | Done | `omniroute_config.py`, `/api/omniroute/*`, Settings UI with sync; Sangam-native |
| 13 | open-webui/open-webui | Done | Chat Markdown export, command palette (Ctrl+P); chat UI |
| 14 | github/spec-kit | Done | Spec wizard (`spec_wizard.py`), `/api/spec/build`, `/api/spec/to-task`; Create Hub |
| 15 | Graphify-Labs/graphify | Done | Knowledge graph with **provenance labels** (EXTRACTED/INFERRED/AMBIGUOUS), **memory wings**, **rooms/drawers hierarchy**; click edge for detail; `test_graph_provenance.py`, `test_build_knowledge_graph` |
| 16 | ChrisTitusTech/winutil | Skip | Windows-only utility, weak fit for AI studio |
| 17 | affaan-m/ECC | Done | Instincts (confidence-scored patterns); **prompt_injection wired** into `/chat/stream` (warn-only); `test_prompt_injection_new.py` |
| 18 | ultraworkers/claw-code | Skip | Reference only; autonomous maintenance exhibit |
| 19 | tt-a1i/archify | Done | Diagramming skill pack; custom SVG renderer in Create Hub |
| 20 | Openpanel-dev/openpanel | Done | Opt-in local-first analytics; **Arena leaderboard** in Insights; 9 tests |
| 21 | HarnessMD/munder-difflin | Done | Multi-agent Teams (see #6); no pixel art reused (per license) |
| 22 | lllyasviel/Fooocus | Done | Style presets + prompt enhancement; **Image Studio tab**; OpenAI-compatible engine. Note: Local Fooocus driver experimental; Fooocus is separate service (per license) |

---

## Phase 7 Additions (not in original 22)

| Feature | Status | Evidence |
|---------|--------|----------|
| Model Compare (side-by-side streaming) | Done | Compare tab; `POST /compare/stream`; Pick winner → `/arena/vote` |
| Arena voting + leaderboard | Done | `ArenaResult` model; leaderboard in Compare tab + Insights |
| Provenance ("Used in this answer") | Done | `mark_used` in chat for RAG/memory; `provenance` SSE event; Inspector panel |
| Fallback chain in completion path | Done | `llm.stream_completion` wrapped; circuit breaker + quota; UI badges |
| Backend routing evaluation | Done | `POST /api/routing/evaluate`; frontend calls backend |
| Memory rooms/drawers | Done | `room`/`drawer` fields; `/memory/rooms` hierarchy; Knowledge UI |
| DESIGN.md design systems | Done | `design` artifact type; DESIGN.md template in Create Hub |
| Learn outline + quiz grading | Done | `/learn/outline`, `/learn/quiz`, `/learn/grade`; Learn tab UI |
| Library SKILL.md preview | Done | Preview + risk scan + version pin; `/skills/{id}/pin` |

---

## Test Evidence

- **Pytest:** 1148 passed, 1 flaky, 100 skipped (2026-10-09)
- **Playwright:** 6/6 golden paths passed (2026-10-09, 30.7s)
  - golden-1-first-run.png — app loads, rail nav (Home/Chat/Agents/Knowledge/Create/Code/Learn/Library/Insights/Images/Voice/Settings), composer
  - golden-2-ask-refine.png — input + send
  - golden-3-knowledge.png — Knowledge tab (note: graph showed "Could not load" in test env)
  - golden-4-create.png — Create Hub
  - golden-5-agents.png — 4 built-in agents (Researcher, Coder, Writer, Analyst)
  - golden-6-settings.png — Settings page with all categories
- **Frontend:** 49 modules parse + link (`scripts/check_frontend_modules.mjs`)

## Known Issues
- Knowledge graph "Could not load" in Playwright test env (builder works standalone; likely auth/session in test)
- Composer shows "NaN" for maxTokens in screenshot (cosmetic, settings type coercion)
- Old Settings modal retained (has provider key management not yet in new Settings page)

---

## Summary
- **Done:** 20/22 (repos) + 9/9 (Phase 7 additions)
- **Partial:** 0/22
- **Skip:** 2/22 (winutil, claw-code — weak fit, documented)
- **Missing:** 0/22

---

## Phase 8 Update (2026-10-10) — "STOP ADDING, START FIXING"

**Branch:** `integration/full-program`  
**Method:** Real-browser smoke test (Playwright) + pytest + code inspection. "Done" = clickable.

### Smoke Gate: 3/3 PASS

- CSS variables defined, no console errors, no bad text
- Register → rail → popovers → Settings → chat send → Knowledge graph
- Mobile 390px rail via menu button

### What Changed

**Fixed (A1-A9):** Knowledge graph 500, NaN token label, undefined CSS vars, OmniRoute sync signature, rail "Turn on", tray overlap, duplicate titles, mobile rail, late feature state.

**Deleted (B1-B8):** ~1,800 lines. Legacy settings modal, duplicate pills, tab picker, footer Settings, `/user/preferences` API. Rail now 7+1.

**Settings (C):** 7 deleted, 9 wired, 14 categories → 7.

**Backend wiring (D):** Spec wizard, run history, quality preview, memory move all reachable in UI. Fallback chain in chat path.

### Known Issue

Chat streaming DOM detachment — backend works, frontend render fragile. Documented in STUDIO_AUDIT.md.

## Current Snapshot (2026-10-15)

The current branch has moved beyond the Phase 8 sidebar layout described above:

- The sidebar is intentionally chat-focused: history, Search, New Chat, profile,
  and collapse controls. The legacy tool rail arrays remain empty by design.
- Studio tools are opened through browser-style tabs, the tab picker, or the
  command palette rather than duplicated as sidebar buttons.
- Profile → Preferences opens the schema-driven Settings page.
- Settings → Research & Web owns persistent Web Search enablement and the
  configurable result limit, with a live search test panel.
- Frontend validation currently covers 49 JavaScript modules.
- The repository contains 71 test source files. Historical test totals above are
  retained as dated evidence and are not a current pass guarantee.
- The full quality gate is not clean: the existing codebase still reports broad
  Ruff, MyPy, and Bandit-command issues. Targeted frontend syntax, module-link,
  backend compilation, and whitespace checks pass.

### Agent Hub — approval policy + cost budget (2026-10-14, this branch)

- Custom agents now carry `approval_policy` (default / automatic / always_ask)
  and `cost_budget` (USD per run).
- Backend: validated on create + update; policy mapped to the engine's
  `require_approval` via `_policy_to_require_approval`; `max_cost_usd`
  forwarded to `run_agent`.
- Existing local SQLite DBs are migrated in place by an idempotent
  `post_create_columns` pass in `database.py` (no Alembic required).
- Frontend: the new-agent form renders immediately and fills the model select
  asynchronously; the agent card shows the policy + budget.
- Verified: `test_agent_approval_policy_and_budget`,
  `test_policy_mapping`, 9/9 targeted tests, all 49 frontend modules parse + link,
  backend imports.

### Totals

- Pytest: 1165 passed, 100 skipped, 0 failed (2026-10-14, targeted re-run after commit; the one historical flaky settings test is fixed — mock-safe /api/v1 prefix)
- Frontend modules: 49/49 parse + link
- Backend: imports cleanly
- Smoke: 3/3 (still valid; not re-run this session)
- Deletions: ~1,800 lines + 7 settings + 7 categories + 12 integration-program design docs (Phase 0-8 program complete, nothing references them)

---

## Batch 9 — Unified Memory + Research (2026-10-26, branch `integration/full-program`)

Deep-read batch for 15 repos (memory-research brief) + the iwe
memory-as-markdown note from the agents-skills brief §4. All landed
inside the existing Knowledge destination (plus chat recall and the
Runs centre) — no new destination, no perfect-flow/tabs-on-top
restoration. Tests: `tests/test_batch9_memory_research.py` (14 tests).

| # | Repo | Status | Evidence |
|---|------|--------|----------|
| 1 | mem0ai/mem0 | Partial→deeper | mem0-style ADD/UPDATE/DELETE/NONE op loop (`backend/memory/ops.py`, preview never writes, apply needs `confirm=true` + known ids only); additive extraction + small-int remap already existed |
| 2 | MemPalace/mempalace | Partial→deeper | Rooms/drawers browsing already existed; this batch adds the browsable Memory-notes + Observations surfaces in Knowledge and graph-edge confidence decay (`memory/graph.py:decayed_confidence`, 90-day half-life, 0.05 floor) |
| 3 | DeusData/codebase-memory-mcp | Partial→deeper | `backend/research/code_memory.py`: refresh-if-stale (fingerprint diff, rebuild only on change), `change_impact` (callers + tests + layers), no watcher daemon (single-user, on-demand) |
| 4 | Graphify-Labs/graphify | Partial→deeper | `detect_hubs` (god-nodes by incoming calls) + `surprising_links` (cross-layer call edges, both endpoints cited) over the existing code graph; full cross-source unified graph NOT built (knowledge_graph owned by another batch) |
| 5 | vectorize-io/hindsight | Partial→deeper | Observation ledger (`backend/memory/observations.py`): claim + verbatim quote evidence + proof count + strengthen/weaken refinement history + expiry/supersede; chat recall injects top observations ahead of raw memories; mental-model standing pages NOT built (scoped out — observations are the import) |
| 6 | lfnovo/open-notebook | Partial→deeper | Notebook source timeline (`GET /notebooks/{id}/timeline`) + notebook-scoped deep-research jobs; multi-speaker podcast NOT built (TTS composition only, no voice cloning) |
| 7 | THU-MAIC/OpenMAIC | Narrow | Guarded slide/lesson outline transform (`POST /research/jobs/{id}/slides`) through a schema over the cited report — citations outside the report are dropped, never invented; no slide editor, no video |
| 8 | assafelovic/gpt-researcher | Partial→deeper | Research job state machine (`backend/research/deep_research.py`): plan → breadth → depth recursion (capped, deduped) → curate → word-budget compress → cited report writer that 422s on uncited claims; planner is deterministic templates + keyword follow-ups, honestly labelled — no LLM in this path |
| 9 | paperclipai/paperclip | Narrow | Research jobs mirrored into the Runs centre (`kind=research`) on completion — governance only; no task-board / multi-user shape |
| 10 | reconurge/flowsint | Narrow, re-scoped | Source graph (`GET /research/jobs/{id}/source-graph`) over the job's OWN retrieved sources only (same-domain + mention edges); no person/IP/breach enrichers, no third-party targeting |
| 11 | yamadashy/repomix | Done (Sangam-native) | `backend/research/pack.py` + `POST /knowledge/packs`: workspace-gated tree + contents + chars/4 token estimates + chunk splits; credential filenames and secret-like content are filtered (listed, never included); binary skipped |
| 12 | Egonex-AI/Understand-Anything | Partial→deeper | Staleness surfaced as a `stale`/`rebuilt` flag on code-map refresh; embedding search over code symbols and job-specific explain/diff/domain/onboard modes NOT built |
| 13 | KeygraphHQ/shannon | Principle only | "No evidence, no claim" adopted for research reports (422 on uncited claims); no recon/exploit/validation pipeline imported |
| 14 | punkpeye/awesome-mcp-servers | Done (as data) | `GET /knowledge/catalogue`: 10 curated MCP server entries with official/community flag, install route (user/manual), risk note, Sangam equivalent; nothing auto-installs or executes |
| 15 | Shubhamsaboo/awesome-llm-apps | Done (as data) | Same catalogue: 8 named LLM patterns (corrective RAG, hybrid search, graph RAG, agentic RAG, critique loop, deep research, observation ledger, Markdown memory) each mapped to its Sangam operation |
| — | iwe-org/iwe (agents-skills §4) | Done | Memory-as-Markdown contract (`backend/memory/markdown_notes.py`): dated, typed frontmatter notes under one browsable directory (`<workspace>/sangam-memory-notes`, overridable via `SANGAM_MEMORY_NOTES_DIR`), `normalize` merges duplicates with a report; secret-bearing writes refused |
| — | Retain-time defense (hindsight Memory Defense pattern) | Done | `backend/memory/defense.py`: block on private keys / token-like credentials, redact e-mails; applied to observation minting and note writes; findings never echo secret values |

### Batch 9 honest limits
- Research planner/follow-ups are deterministic (templates + keywords), not LLM-planned; curator scores are heuristic (retrieved text + URL + length).
- Pack token counts are chars/4 estimates, not tokenizer counts.
- Catalogue is a curated snapshot dated 2026-10-26, not a live index; install routes are documentation.
- Chat observation injection is code-wired but NOT live-verified with a real model (no model configured in this environment); the identical context block is endpoint-tested via `GET /memory/observations-context`.
- Knowledge frontend section is added and module-link-checked, not browser-verified here (subagent has no live browser); Playwright verification is left to the coordinator.
- Unified cross-source graph merge (code + notes + memories + research into one graph) and mental-model standing pages were scoped out, not silently approximated.

## Batch 10 — Agent Runtime + Skills (2026-10-26, branch `integration/full-program`)

Deep-read batch for the 23 repos in the agents-skills brief. Landed
inside the existing 7 destinations (Work → Agents/Approvals, Library
packs) — no new destination, no perfect-flow/tabs-on-top restoration,
no second agent/team/skill system. `run_agent` in `code_agent.py` is
untouched as the API-compatible loop; the new `backend/agent_runtime/`
package (previously only `__pycache__`) is the missing glue. Tests:
`tests/test_batch10_agent_skills.py` (28 tests).

| # | Repo | Status | Evidence |
|---|------|--------|----------|
| 1 | OpenHands/OpenHands | Portable ideas only | Per-run sandbox/worktree as DEFAULT code-agent context + verify-style exit gate (`agent_runtime/sandbox.py`, `POST /agent/runtime/sandbox[/verify]`); Docker runtime NOT ported, Docker isolation NOT claimed verified live — workspace fallback + warning via existing `security_guardrails.run_isolated_command` |
| 2 | earendil-works/pi | Done | Steering queue + abort at step boundaries, parallel-by-default / sequential-on-`reads` tool planning, structured compaction (summary + read/modified files) with branch resume (`agent_runtime/loop.py`) |
| 3 | ultraworkers/claw-code | Done (async shape) | Async approval channel (`agent_runtime/approval.py`): risky call waits in the tray while the run continues with independent calls only; decisions from chat or a paired LAN device via the tray; existing per-run policy + DB audit rows unchanged |
| 4 | iwe-org/iwe | Already covered (Batch 9) | Memory-as-Markdown contract landed in Batch 9 (`backend/memory/markdown_notes.py`); not rebuilt here |
| 5 | msitarzewski/agency-agents | Done (contract) | Severity-tier review schema blocker/suggestion/nit (`backend/teams/review_schema.py`, parses 🔴/🟡/💭 and Must/Should/Nice); roster-consistency is the existing `persona_registry.validate_roster`, now regression-tested with zero errors |
| 6 | overmind-core/overmind | Narrow | `propose_from_eval` (`agent_runtime/orchestration.py`): propose (never silently apply) a model/prompt change with the eval delta as evidence |
| 7 | citrolabs/ego-lite | Done | `bootstrap_command` skill support (`backend/skills/bootstrap.py`): approval-gated, argv-only, 4000-char cap, banned-pattern scan; shell metacharacters rejected |
| 8 | PersonalJarvis/PersonalJarvis (dodaios) | Done (protocol) | `RuntimeDriver` protocol + `LocalCommandDriver` (detect/start/health/kill/log-tail, `agent_runtime/drivers.py`); API exposes detection only — spawning is host-operator initiated, never an API request (would be unrestricted execution) |
| 9 | Louis-CFM/coucou | Done (UX pattern) | Persistent "Needs you" tray in Work → Agents → Approvals (`hub.js`), fed by the async tray; no new approval backend |
| 10 | stablyai/orca | Done (primitives) | Typed `ask` (blocking question + timeout) and `gate` (pass/block) nodes + worktree ownership handoff to a fresh worktree + fresh context (`agent_runtime/orchestration.py`); worktree/SSH/mobile companion pieces were already in `worktrees.py` |
| 11 | HarnessMD/munder-difflin | Done (mode) | Hive mode: inbox-drain before finish, critical-only escalation (destructive/spend/scope/conflict/secret/production), single-committer path stated in the new coordinator persona; hive module itself unchanged |
| 12 | obra/superpowers | Done (run shape) | Subagent-per-task `TaskGraph` (blocking edges, ready frontier, per-task review gate, branch review) + four-stop-rule contract; skill evals now require a failing baseline before publish (`creator.publish_skill(require_failing_baseline=...)`) |
| 13 | anthropics/skills | Done (enforcement) | Description word-budget check (warning over ~100 words, not a failure) + trigger-accuracy evals (`creator.trigger_eval`) as part of the publish path; format itself was already implemented |
| 14 | mattpocock/skills | Done (same engine) | Ticket-graph flow is the same `TaskGraph` engine as superpowers §12; skill-to-skill invocation rule was already in `registry.check_skill_call` |
| 15 | multica-ai/andrej-karpathy-skills | Done (native skill) | `coding-guidelines` (original Sangam wording, not copied text) added to the engineering pack; injected by default for code runs via the existing auto-fire path |
| 16 | midudev/autoskills | Already covered | Stack-detection + verified install already in `recommend.py`/`importer.py`/`verify.py`; no new installer built |
| 17 | K-Dense-AI/scientific-agent-skills | Done (contract + loop) | Validated frontmatter fields `allowed_tools`/`compatibility`/`version`/`last_reviewed` in registry + verify; user-triggered "propose from my runs" job (`skills/reverse.py`, Runs titles only — no screen capture, Sangam has no screenpipe); 177-skill breadth NOT curated (content, not code) |
| 18 | Leonxlnx/taste-skill | Done (pattern) | Declared `scripts.json` manifest (`skills/bootstrap.py`) + blind A/B gate (`creator.evaluate_blind`: with-skill must strictly beat without-skill) + original `design-taste` skill in the new `taste-quality` pack; gallery content NOT copied |
| 19 | Yeachan-Heo/oh-my-claudecode | Excluded — clone absent | Deep-read brief §19: never arrived; nothing claimed or built from it |
| 20 | odysseus-dev/odysseus | Done | Frozen `TurnContract` (`required <= offered <= executable`, schema snapshot) with no-substitution rule: unavailable → stop and say so (`agent_runtime/loop.py`); slow-tool promotion rule (60s budget → background job in Runs feed) |
| 21 | Dodaios/Dodaios (standalone) | Excluded — clone absent | Deep-read brief §21: distinct from PersonalJarvis's `dodaios` package (§8, read); nothing further claimed |
| 22 | zhaoxuya520/reverse-skill | Done (Sangam-native mechanism) | Deep-read brief §22: clone absent, so nothing is claimed from it; the mechanism itself — propose a draft skill from a transcript, user reviews before saving — is implemented in `skills/reverse.py` + `POST /skills/propose-from-transcript`, `POST /skills/drafts/save` (drafts live outside the skills root, never auto-loaded) |
| — | Agent catalog (agency/ego-lite/overmind/coucou/PersonalJarvis/odysseus/Dodaios/oh-my-claudecode) | Converged, not duplicated | No new agent system: one new persona only (`teams/personas/engineering/coordinator.md`, the god-orchestrator escalation contract — genuinely missing); the rest map to the runtime/skill mechanisms above or are excluded with reason in this table |
| — | Orca/munder-difflin gap check | Already-covered + gap filled | Teams/hive/worktrees already covered most of both; the genuine gaps (ask/gate nodes, worktree ownership handoff, inbox-drain mode, single-committer contract) are the Batch 10 items above, not a duplicate system |

### Batch 10 honest limits
- `run_agent` was NOT refactored into the new package: steering, async approval, and the turn contract are runtime primitives + API, wired into new run shapes; the existing loop still blocks on its own approval gate for in-loop calls. Full loop adoption is follow-up work, not claimed here.
- No live model run exercised the new primitives (no model configured here); steering/approval/flow are unit- + endpoint-tested with deterministic fakes, not live agent runs.
- Paired-device approval is exercised via the tray endpoint with `source: "paired-device"` under the same authenticated `/api` session; a real phone-over-LAN round-trip was not verified here (standing unverified item).
- Docker isolation, real-driver browser runs, and physical phone QR scan remain unverified live, as before; the verify gate reports `workspace-fallback` + warning on this machine rather than claiming container isolation.
- Blind A/B scoring in the API is scored from caller-supplied run outputs and labelled as such — it is not a live model run.
- Frontend additions (run-mode/flow preview, tray) are module-link-checked (63/63), not browser-verified here (subagent has no live browser); Playwright verification is left to the coordinator.
- `ARCHITECTURE.md` §13.2 was already drifting at base 93eb40a (Batch 9 routes undocumented, drift test failing); this batch documents all missing rows (Batch 9 + Batch 10) and the drift test passes again.

### Batch 11 — Unified Media + Design (2026-10-26, branch integration/full-program)

One unified pipeline, not one button per repo: `backend/media_pipeline/` (stages, audio,
graph, design, overlay, storyboard) extending the existing MediaJob, image_gen, voice,
diagrams and media-jobs routes; frontend is a Studio *section inside Create* (no new
destination). All 14 media/design repos below were read from source in
`~/workspace/projects/research-repos/` for this batch, including the 7 the earlier
deep-read brief could not read (their clones were absent then).

| # | Repo | Status | Evidence |
|---|------|--------|----------|
| 1 | lllyasviel/Fooocus | Done (honestly gated) | Performance presets as engine-parameter bundles (quality 36 / speed 18 / extreme 8 / lightning+hyper 4 steps); prompt expansion as an explicit shown step (deterministic wildcard+style expansion — NOT Fooocus's LLM expansion, labelled as such); generation metadata sidecar on `/image/generate` (`performance`/`expand_prompt`/`metadata`); PNG mask in/out + feathering at `/image/mask` (server never invents a mask; no brush editor — client supplies the PNG). Style library expanded 8 -> 20 with ORIGINAL suffixes only: Fooocus's six `sdxl_styles/*.json` (277 styles) were NOT imported because that repo is GPL-3.0. FaceSwap / IP-Adapter-face NOT added (excluded). AI upscale still NOT claimed: Lanczos stays labelled "local resize, not AI upscaling". Tests: `test_batch11_media_design.py` (presets, expansion, mask) |
| 2 | Comfy-Org/ComfyUI | Done (small node set) | Read from source: `comfy_execution/graph.py` (typed links, topological `ExecutionList`, cycle detection) + `comfy/comfy_types/node_typing.py` (INPUT_TYPES/RETURN_TYPES). Sangam-native graph in `media_pipeline/graph.py`: fixed node registry (prompt, style_apply, image_generate, text_chunk, tts, diagram_validate, subtitle_export, design_critique, overlay), typed sockets, missing-input/type-mismatch/double-link/cycle validation, topological execution — executed ONLY through handler callables wired to Sangam's existing engines. Custom-node code execution NOT ported (rejected as unknown-node). Routes: `POST /media/graph/validate`, `POST /media/graph/run` (missing engine -> 503, never a fake output) |
| 3 | calesthio/OpenMontage | Done (non-video salvage) | Staged pipeline model in `media_pipeline/stages.py` + MediaJob extension: stages with `produces`/`checkpoint_required`/`max_revisions`/`budget_cap`, checkpoint pause (`awaiting_approval`) + `POST /media-jobs/{id}/approve` with revision-cap abort, per-stage artifacts, cost record that is honestly `known: false` (no Sangam engine reports cost, so budgets never trip on invented numbers). Subtitle/cue generation (SRT/VTT/ASS) and shot-prompt building (storyboard still prompts) ported. VIDEO output, Remotion composition, talking-head, clip-factory NOT ported (excluded) |
| 4 | debpalash/VoiceStudio | Done (cloning-free) | Chunked long-form TTS (sentence/clause/word-boundary splits, never mid-word, WAV join with silence gaps) at `POST /voice/tts/chunked`; audiobook plan (chapters/spans/deterministic per-span seeds, chapter-gap rules, chaptered manifest) at `POST /voice/audiobook` + media-jobs `audiobook` kind (plan + rendered chapters); TRUE dubbing at `POST /voice/dub` (timed segments -> fitted script -> SRT/VTT/word-level ASS, timings summing exactly); diarization labels carried from supplied segments/turns only; WAV peak normalisation (stdlib, 16-bit PCM); content-hash dedup helper. Old media-jobs `dub` kind renamed in docs/UI to "voice a script". VOICE CLONING excluded: no clone endpoint, no reference-audio field, no speaker-embedding extraction; STT engines return plain text only, so `/voice/dub` without supplied segments is 422 (timings never invented) |
| 5 | academa-labs/manimgx | Excluded (video) + salvage | Read from source: a Rust/wgpu 3D animation engine with a Manim-CE-compatible API whose output is MP4 video — video generation, excluded. Salvage only: scene-plan validation + still-image prompts per scene (`media_pipeline/storyboard.py`, `POST /media/storyboard`). No renderer, no motion, durations labelled plan estimates only |
| 6 | Brandon-Collins7/sketchvlm | Done (mechanism) | Read from source: a research repo whose portable mechanism is non-destructive, editable SVG overlays on an input image (point/label/arrow/rect/circle/path in normalised coordinates) so a model can show its reasoning. Ported as `media_pipeline/overlay.py` + `POST /media/overlay`: validated annotations, standalone SVG render, source image untouched. No VLM is run here — the overlay is the contract a model or user fills in |
| 7 | mohit67890/imajev | Catalog entry only | Read from source: small open decision models (2B/4B/9B) that answer in caller-set options with per-option probabilities and an explicit can't-tell. No portable mechanism beyond model weights + prompting, and the weights are not Sangam's to run — nothing built from it. Its decision shape (options + probabilities + abstain threshold) is noted as a future pattern for critique/decision outputs, not implemented as a fake model call |
| 8 | feder-cr/invisible_dots | Excluded with reason | Read from source: a self-hosted VM-agent platform ("Dots") whose headline property is being undetectable by anti-bot systems, running its own VM desktop/browser identities. Not portable to Sangam (different product: VM agent fleet) and its undetectability goal conflicts with Sangam's guardrails — nothing built from it |
| 9 | nexu-io/open-design | Done (contract + critique loop) | Design-system contract object (tokens + source evidence + version, rebuild from CSS with per-token evidence) at `POST /design-systems` (file-backed under uploads/design-systems, no migration); prototype generation stays on the existing Code Agent path constrained by the contract; critique/audit pass with MEASURED findings (see impeccable row). Stock search/staging NOT ported (no stock provider in Sangam) |
| 10 | cathrynlavery/diagram-design | Done (verifier layer) | Layout verifier (`diagram_ir.verify_layout` + `POST /diagrams/verify`): 4px-grid divisibility, single-accent check, label/node budgets, rectangle overlap on computed geometry — so lint stops being Mermaid-text-only for the SVG path. Standalone HTML+SVG export (`POST /diagrams/export`). Mermaid lint itself is unchanged (text-only claim kept). The full 45-type catalogue and per-type verifiers were NOT ported (scope: one verifier layer + export, not 45 grammars) |
| 11 | tt-a1i/archify | Done (typed family) | `diagram_ir.py` generalised from architecture-only to a typed IR family: erd (table-first, junction pk/fk + `references: "table.column"` with resolution checks), sequence, workflow, timeline — each with strict validation + fixable diagnostics + measured/illustrative evidence flags (measured without a pinned 40-hex revision fails). `POST /diagrams/validate` returns junction tables for ERD. Browser-check evidence, position-only layout repair and the other archify renderers were NOT ported |
| 12 | pbakaus/impeccable | Done (audit + transforms) | Measured critique (`media_pipeline/design.py` + `POST /design-systems/{id}/critique`): WCAG contrast ratios computed from real colour pairs, gold-small-text rule (Kinpaku: gold for large display only), hairline (<1px), hard-offset shadows, tiny type, fixed-width overflow risk, off-contract colours — each with a measured value + fix. bolder/quieter/distill as parameterised token operations (`POST /design-systems/{id}/transform`), not free-text re-prompts. The Rust raster/component metrics and full 24-command set were NOT ported |
| 13 | Anil-matcha/Open-Generative-AI | Catalog entry + excluded parts | Read from source: an Electron studio fronting 600+ models via MuAPI across image/video/audio/lip-sync studios, marketed as unrestricted. Its portable idea (a model catalogue with per-model input schemas) already exists in Sangam as the provider/engine registries — no new catalogue built. Its video, lip-sync and unrestricted-generation studios are excluded (video + no content-filter bypass) |
| 14 | ItzCrazyKns/Vane | Converged, not duplicated | Read from source: a privacy-focused AI answering engine (SearxNG + local/cloud LLMs, cited sources, speed/balanced/quality search modes, source picking). That is search/research, not media: Sangam's existing websearch/research (Batch 9) already covers the shape. No media code built from it; its search-mode/source-picking pattern is noted for research, not re-implemented here |

### Batch 11 honest limits
- No live model run exercised the new pipeline stages end to end here (no TTS/image engine configured on this machine): stage execution, checkpoint/approve, audiobook rendering and graph image/tts handlers are endpoint- + unit-tested with deterministic fakes and pure stages, not live engine runs. Fooocus's Gradio driver path was not live-tested either (no Fooocus server here); its 422 honesty rests on code, as before.
- Fooocus style JSON was deliberately NOT imported (GPL-3.0); the 20-style library is original wording, not Fooocus's 277.
- True dubbing needs timed segments the current STT engines do not produce; until an STT engine exposes segments, `/voice/dub` requires caller-supplied segments and returns 422 otherwise — that is the honest boundary, not a gap to paper over.
- Pipeline cost is `known: false` because no Sangam media engine reports cost; budget caps therefore cannot trip today. If an engine reports cost later, `CostRecord` enforces caps without code changes to the job model.
- Design systems are file-backed JSON under uploads/design-systems (per-user filename prefix), not DB rows — no migration, but also no DB querying; acceptable for single-user.
- Frontend Studio section is module-link-checked (64/64 modules), not browser-verified here (subagent has no live browser); Playwright verification is left to the coordinator.
- Physical phone QR scan, real-LAN/mDNS, Docker isolation and real-driver browser runs remain unverified live, as before.

### Batch 12 — Dev / QA / Security / Platform (2026-10-26, branch integration/full-program)

One QA system, one workflow-depth layer, one guarded security layer, one
platform/health layer, one chat-parity layer — not 23 buttons. Backend:
`backend/qa/devqa.py` (pure helpers) + `backend/api_routes/devqa_routes.py`
(all `/api/devqa/*` endpoints, authenticated) + a real `human_input` node
in `workflows.py` (pause with status `awaiting_input`, exactly-once resume
that replays from the original input). Persistence for services / health
history / notifications / folders / presets is a SQLite sidecar
(`uploads/devqa.db`, `SANGAM_DEVQA_DB` override for tests) — deliberately
kept out of shared `models.py` so parallel batches sharing that file are
untouched. Frontend: a "Dev & QA" section inside the existing Work
destination (`features/work/devqa.js`, wired into `work.js`); no new
destination, no perfect-flow/tabs restoration. Writing-lint gains are wired
into the existing `/quality/lint` route, not a second linter. All 23 repos
below were read from source in `~/workspace/projects/research-repos/` for
this batch, including the 5 the earlier deep-read brief could not read
(their clones were absent then; they exist now and were spot-checked).

| # | Repo | Status | Evidence |
|---|------|--------|----------|
| 1 | github/spec-kit | Done | Constitution parsing + plan gate (`POST /devqa/spec/constitution/check`, keyword-overlap heuristic labelled as such, not semantic proof) and P1-only MVP ordering with dependency/cycle errors (`POST /devqa/spec/mvp-order`). Existing spec_chain (spec/plan/tasks/coverage) unchanged. Clarify-before-spec gate and checklist artifacts NOT built |
| 2 | unclecode/crawl4ai | Partial (helpers + API) | Frontier ordering bfs/dfs/best_first, composite scorer (keyword + depth + freshness + caller-supplied authority, never invented), FilterChain (content_type/domain/keyword), markdown chunking (paragraph/heading/fixed), link-graph output — all as `/devqa/crawl/*` helpers. NOT yet threaded into `crawl_job.run_crawl` or the workflow `crawl` node, which remain BFS-only; that threading is future work, not claimed |
| 3 | langflow-ai/langflow | Done (catalogue) | Typed node catalogue (`GET /devqa/node-catalogue`) covering exactly the engine's closed node set (15 existing + `human_input`) with declared inputs/outputs. No new executable types invented: fan-out is DAG edges, sub-flow is a workflow run by id — both documented in the catalogue, not fake nodes. No React rewrite, no multi-tenancy |
| 4 | langgenius/dify | Done | `human_input` node (validation + pause + exactly-once resume endpoint, replay-from-start limitation stated), variable-pool validation (`POST /devqa/workflows/validate`: input/nodes.<known>/system/env scopes, unknown node references rejected), and 3 starter graphs (chatbot/agent/workflow) as Work templates. Trigger-as-node and workflow-as-chat-app publish mode NOT built |
| 5 | browser-use/browser-use | Not built in this batch | DOM snapshot action, judge verification step, and session/watchdog recovery were NOT added here; the existing two-mode browser agent (automation vs security-test, allowlisted, per-mode approval) is unchanged. Snapshot/judge belong to a browser-focused batch; no claim of browser-use parity |
| 6 | ChrisTitusTech/winutil | Done (safe half) | Health-action catalogue (`GET /devqa/platform/health-actions`: every action declares risk + reversibility) + Windows check/tweak catalogue (`GET /devqa/platform/winutil-catalog`: read-only checks + documented-only tweaks). NOTHING is executed by the server; the user runs checks on their own Windows machine. Registry/debloat/AppX/winget execution excluded |
| 7 | affaan-m/ECC | Not built in this batch | Hook matchers with allow/deny/annotate outcomes, the reviewer-agent library, and skill-health scoring were NOT wired into `permission_policy.py` or the skills system here. No claim; the QA lint rules in this batch are JS/writing rules, not ECC's hook semantics |
| 8 | H-mmer/pentest-agents | Done (guardrail half) | Scope-file import + hard check (wildcard domains, CIDR, excluded-wins), finding fingerprinting + dedup, CVSS-version guard, guided phase checklists (recon/hunt/triage/report). WAF-bypass protocol excluded in its entirety; bounty/third-party targeting excluded (own-systems-only) |
| 9 | Z4nzu/hackingtool | Partial | Tool availability probing (binary + install hint, Sangam never installs) and wholesale rejection of excluded categories (`POST /devqa/security/categories/reject`). Install/update lifecycle and per-tool output parsers NOT built. Excluded categories: ddos, phishing, remote-admin, post-exploitation, exploit-frameworks, anonsurf, wireless, payload-creator-as-weaponizer |
| 10 | usestrix/strix | Partial | Sandbox pre-flight gates failing closed (`docker_unavailable` when Docker is off and fallback disallowed) and a computed coverage ledger (undefined, never 100%, on zero discovered). Reusable labelled sandbox sessions with caps + guaranteed cleanup, proxy integration, and a scheduled CI passive-scan mode NOT built; existing Docker-or-workspace-fallback behaviour is unchanged |
| 11 | keploy/keploy | Done (review-only) | Cassette → pytest generation (`POST /devqa/qa/cassette-to-test`) and replay diff with noise stripping (`POST /devqa/qa/replay-diff`). Generated code is RETURNED, never written to `tests/`; cassettes carrying auth/cookie/API-key headers are rejected at generation time. Live-traffic recording from Sangam sessions NOT built (cassettes are caller-supplied) |
| 12 | tester-army/e2e | Partial | Budget/tag discipline via test tags + suite report (quarantined passes are not green) and the JS lint ruleset. The agent-driven "explore this destination" mode, budgeted QA runs with screenshots, and self-healing locators were NOT built (they need Playwright-harness work); existing Playwright specs are untouched |
| 13 | goldbergyoni/javascript-testing-best-practices | Partial | Test tags (cold/live/quarantined), suite-report verdict, and a JS ruleset (no-console-in-prod, no-bare-specifier, testid-for-interactive) as findings-only checks. Per-route API contract (response-shape) tests NOT added; the drift test covers route presence, not schemas |
| 14 | Automattic/harper | Done | Three Harper-shaped deterministic rules wired into the existing `writing_lint.lint_text` and `/quality/lint` route: a/an agreement (with hour/honest-type exceptions), double comparatives, common typos — each with span + suggestion, never auto-rewrite. User dictionary persistence and dialect (US/UK) setting NOT built |
| 15 | quickemu-project/quickemu | Done (gates + profiles) | Pre-flight gates (see strix row) plus VM launch profiles (`GET /devqa/platform/vm-profiles`) as documented external-tool configs only. Sangam never launches a VM, never claims a hypervisor, never downloads or licenses an OS image. QEMU guest support excluded as a new product + attack surface |
| 16 | coollabsio/coolify | Partial (hygiene only) | Service-health dashboard data (registered URLs, live probes with `trust_env=False`, SQLite uptime history), health-action catalogue, and analytics taxonomy/funnels. NOT a Coolify clone: no deployment engine, no deployment queue, no scheduled backup execution, no restore dry-run execution (verify_backup is a catalogue entry, not an executed restore) |
| 17 | Openpanel-dev/openpanel | Partial | Declared event taxonomy with 422 on unknown events (`POST /devqa/platform/analytics/event`) and session funnels over supplied events (`POST /devqa/platform/analytics/funnel`). Events are validated, not persisted, by this endpoint; aggregate stats remain on the existing `/analytics/*` routes. No second tracker, no ClickHouse |
| 18 | open-webui/open-webui | Partial | Pipe shape already existed as `prompt_transform`; this batch adds the typed catalogue entry and the starter-graph surface around it. An eval harness (eval sets runnable against any model) was NOT built. Multi-user RBAC, groups, shared chats, OAuth/SCIM excluded |
| 19 | gotify/gotify | Done (native equivalent) | Webhook-in + in-app inbox (`/devqa/platform/notifications/*`): a secret must be configured (`SANGAM_DEVQA_WEBHOOK_SECRET`) and matched, otherwise webhooks are refused — no open inbox. No external push service (FCM/APNs/WebPush) is claimed, and no websocket stream is offered |
| 20 | anything-llm | Partial (generic shapes) | Prompt-template library, chat folders, and shareable model presets (settings only — share payload states `shares_keys: false, shares_history: false`). Multi-user workspaces, invites, agent flows, and embed chats excluded; nothing here claims anything-llm parity beyond these generic chat shapes |
| 21 | librechat | Partial (generic shapes) | Same generic shapes as row 20 (folders, prompt templates, model presets). Multi-user accounts, SSO/2FA, plugins, code environments, and shared conversations excluded |
| 22 | pentagi/pentagi | Excluded (autonomous part) | PentAGI is autonomous multi-agent pentesting (including Metasploit-class tooling) — autonomous exploitation is excluded by the standing guardrail. Only the already-existing Sangam engagement shape (runs/phases/findings/report) plus this batch's guided checklists are used, always per-run-approved and own-systems-only |
| 23 | heretic/heretic | Excluded entirely | Model censorship removal (directional ablation / abliteration) — a safety-bypass tool. Nothing built from it, no endpoint, no flag, no mention in any catalogue |

### Batch 12 honest limits
- Crawl strategy/filter/chunk/graph helpers are API-level; `crawl_job.run_crawl` and the workflow `crawl` node still run BFS with raw HTML→text only. Do not claim crawl4ai parity until those helpers are threaded into the fetcher.
- Workflow resume replays from the original input: an `llm` node before the pause re-runs (and re-costs) on resume. Resume is exactly-once per paused run (a second resume is 422), but the paused run row itself stays `awaiting_input`.
- Coverage is computed from caller-supplied discovered/probed counts; it is not yet wired into SecurityRun reports, so a security report does not yet show coverage automatically.
- The notification inbox is in-app only; webhook-in needs the env secret, and there is no push to any device.
- Health-action catalogue entries are declarations (risk + undo text); `verify_backup` and `prune_runs` are not executed by any Batch 12 endpoint — execution stays with the existing system routes.
- Frontend Dev & QA section is module-link-checked (65/65 modules), not browser-verified here (subagent has no live browser); Playwright verification is left to the coordinator.
- Docker isolation, real-driver browser runs, and physical phone QR scan remain unverified live, as before.

### Batch 13 — Writing / Quality / Council / Code-Graph / Model-Fit (2026-10-26, branch integration/full-program)

One writing-quality pipeline, one council/debate mode, one code-graph
evidence layer, one fit+routing surface — all landed in the existing
7 destinations, primarily Chat. No new destination, no perfect-flow /
tabs-on-top restoration, no Batch 1–4 files touched, `writing_lint.py`
untouched (Batch 12's Harper rules already cover it — verified, not
duplicated). Backend: `response_quality/structure.py` (detect-only
structural patterns), `eval.py` (no-ai-slop eval checklist as code),
`humanizer.py` (natural rewrite), `adhd.py` pre-send check +
state restatement; `council_mode.py` panels/Chairman/re-prompts;
`teams/debate.py` ledger/branches/closing report; `code_graph.py`
Python `extends` edges; `code_graph_queries.py` BM25/IDF + test
de-rank + evidence + orphans + impact + explain-change + layering;
`model_fit.py` weighted scores + bandwidth estimate + measured
override; `providers/fallback_chain.py` named strategies + session
pinning. Routes extend existing modules only: `/quality/check`,
`/quality/humanize`, `/quality/report`, preview `structure`+`eval`;
`/models/route`; council `profile/members/chairman` fields;
`/code-graph/impact`, `/code-graph/orphans`,
`/code-graph/explain-change`, `/teams/debate/scenarios`,
`/teams/debate/jobs/{id}/report`. Frontend (Chat): per-message
"Check writing" / "Natural rewrite" buttons with inline panels
(nothing auto-applied), Council composer mode + `/council` slash
command (verdict + tally + minority report + ledger id rendered
and persisted as a chat turn), stale ADHD settings copy fixed.
Settings keeps the toggles as the single place for defaults.
Library gains the original Sangam-authored `smallest-change-review`
skill (taste-quality pack). All 11 brief repos below were verified
against the tree first; genuinely-missing depth only.

| # | Repo | Status | Evidence |
|---|------|--------|----------|
| 1 | ayghri/i-have-adhd | Done (Chat-wired) | `pre_send_check()` (first-line action, last-line next step, tangent count, list runs over 5) + `restate_state()` (step x of y, clamped) + per-message report in Chat; prompt block was already chat-wired, post-hoc transform unchanged. Stale settings copy fixed (no longer claims "not yet wired into chat") |
| 2 | petergyang/no-ai-slop | Done (Chat-wired) | `structure.py`: binary-contrast, colon-reveal, faux-insight, importance-puffery, weasel-attribution, recap/kicker endings, formatting slop, em-dash clusters, robotic rhythm — detect-only (pattern + line + quote + fix, never rewrite); `eval.py` checklist (numbers preserved, no new sentences, length bounded, change list matches, no opener left, no slop left); `POST /quality/preview` gains `structure` + `eval` |
| 3 | 0xNyk/council-of-high-intelligence | Done (Chat-wired) | Panel selection (`classic` / `exploration-orthogonal` / `execution-lean` / duo pairs / manual members), domain-seat locking before analysis, restate gate, distinct Chairman synthesis step (opt-in), enforcement re-prompts (dissent quota, novelty, missing stance — max one per member), session metadata, verdict-specific kill criteria (replaces generic "See verdict text"). Tally arithmetic untouched and still exact. Chat: Council composer mode + `/council` renders verdict + tally + minority report + ledger id |
| 4 | trailhq/Graft | Done | BM25 (k1=1.2, b=0.75) + IDF over symbol text + test-path de-rank 0.35x in `find_code()`; `extends` edges for Python classes (unique resolution only, ambiguous dropped + counted). NOT built: concept/module layer and ask-index sidecar cache — symbol bodies are not stored (only body_hash), so a body-text index and a concept layer would need a new store; recorded as future work, not claimed |
| 5 | garrytan/gstack | Partial (checklists, not engine) | Design-QA checklist and shared-code dedup finder are NOT separate engines; their portable discipline lands as: Ponytail-shaped `/quality/check` findings and code-graph `orphans` (dead-code candidates) + `layering_check` (caller-supplied layer order). gstack's `deslop-shared-libs` (code dedup) is kept distinct from prose de-slopping in naming and docs |
| 6 | DietrichGebert/ponytail | Done (report shape + Library skill) | Ponytail report contract in `/quality/check` (ranked must-fix first, concrete case + fix + if-skipped, not-checked/risks footer) and original Sangam-authored `smallest-change-review` SKILL.md in the taste-quality pack (reuse-first order, no case no finding, footer convention). The Claude-Code "band" cost/reuse meter is NOT ported (harness-dependent) |
| 7 | 666ghj/MiroFish | Native equivalent (capped, never the swarm) | `position_ledger()` (per-persona statements side by side, contradiction judged by the reader, never keyword-inferred), `scenario_branches()` (1–3 injected variables, over-cap refused), `closing_report()` (ledger + quoted disagreements + what-would-change-it) + `/teams/debate/scenarios` and `/teams/debate/jobs/{id}/report`. OASIS/Zep thousand-agent simulation explicitly NOT built |
| 8 | AlexsJones/llmfit | Done | Per-use-case weights (chat/general 0.45/0.30/0.15/0.10, code 0.50/0.20/0.15/0.15, reasoning 0.55/0.15/0.15/0.15) shown in every row, weighted scores, bandwidth roofline speed estimate (labelled estimated, 50 GB/s DDR default), measured-benchmark override (plausible ≤10000 tok/s replaces the estimate and is marked measured; implausible ignored with a note), MoE total-vs-active note, AWQ/GPTQ kernel-fallback flag, estimation-cap honesty note. Role-rubric routing matrix NOT built (would need real rubric runs, not invented scores) |
| 9 | diegosouzapw/OmniRoute | Done (strategy layer, not gateway) | `POST /models/route` + `fallback_chain.choose_provider()` / `choose()`: priority, cost-optimized, headroom, quota-weighted, round-robin, fail-closed (never falls back to a billable provider), each returning reasons; session pinning (`pin_session` / pinned-first in `execute_with_fallback`, failure falls through). The 375-provider gateway itself, quota-share pooling, and token compression are NOT built |
| 10 | morluto/rea | Done (evidence discipline only) | Every code-graph answer gains an `evidence` block: sources (file:line + body_hash), dropped ambiguous/unresolved/extends counts, skipped dirs, file-cap flag, freshness pointer to `/knowledge/graph/check`. Binary/JS-app reverse engineering and disassembly are NOT ported (out of scope by the standing guardrails; only the user's own workspace code is graphed) |
| 11 | AhmadHassan-BTed/Turnitout-Humanizer | Done as natural rewrite ONLY; evasion EXCLUDED | `POST /quality/humanize` + per-message "Natural rewrite" button: slop removal, filler deletion, >45-word sentence splits — labelled readability only. No AI-detection evasion, no detector-bypass guarantee, no authorship concealment, no invisible-character handling, no auto-citation fabrication — stated in code, UI panel, route response note, and here. The upstream repo's detector-defeating purpose is explicitly not ported |

### Batch 13 honest limits
- Council Chat mode needs a configured model (same as normal chat); the deliberate route itself was unit-tested with fake completers, not live-hit with a real model here (no model is running in this environment).
- Code-graph BM25 runs over symbol text (name/qualname/signature/file), not full function bodies — bodies are not stored, only body_hash — so length normalisation applies to symbol text, not body length. Stated in the module header.
- `extends` edges cover Python classes only; the JS scanner does not record class bases.
- Fit speed estimates use a conservative DDR bandwidth default unless the caller supplies one; measured override only applies where a stored local benchmark exists for that exact catalogue id.
- Routing strategies score on chain state (circuit + quota); cost/latency inputs are caller-supplied or absent (absent cost falls back to priority and says so) — there is no live provider cost/latency feed.
- Frontend Chat wiring is module-link-checked (65/65 modules), not browser-verified here (subagent has no live browser); Playwright verification is left to the coordinator.
- Physical phone QR scan, real-LAN/mDNS, Docker isolation and real-driver browser runs remain unverified live, as before.

## Coverage audit — final batch (2026-10-26, branch `integration/full-program`)

Definitive table: `docs/ALL_IN_ONE_COVERAGE.md`. All 85 deduplicated repos
from the user's list were verified against files in this tree, not against
the batch write-ups. Counts: **shipped 58, native-equivalent 22, excluded 5,
unaccounted 0.**

Excluded (with reasons, full text in the definitive table): Dodaios
(standalone — clone absent, brief never arrived), oh-my-claudecode (clone
absent, brief never arrived), invisible_dots (VM-agent undetectability
conflicts with guardrails, different product), pentagi (autonomous
exploitation excluded; only the pre-existing engagement shape + checklists
used, per-run-approved and own-systems-only), heretic (safety-bypass tool,
excluded entirely).

Filled in this audit (smallest honest surface, no new large system, no new
destination, no new route): imajev / Vane / Open-Generative-AI catalogue
reference rows (`ref-imajev`, `ref-vane`, `ref-open-generative-ai` in
`mainfiles/backend/research/catalogue.py`, searchable via
`GET /knowledge/catalogue`). Batch 11 had described these as catalogue
entries, but no such rows existed in code — the audit found the gap and
closed it with documented rows only (no model run, no install, no code
port invented). Also corrected in this audit: `spec_wizard.py` is retired
(coverage now cites `spec_chain.py` + devqa constitution/mvp-order;
`ARCHITECTURE.md` tree line corrected); claw-code upgraded from the old
"Skip / reference only" note to shipped-as-async-approval-shape (Batch 10);
browser-use / ECC "not built in Batch 12" clarified as "not built in that
batch" — both have pre-existing implementations that stand.

### Batch 6 verification (this run, venv `~/workspace/.b9venv`, proxies unset)

- Full suite: **1624 passed, 101 skipped, 0 failed** (baseline at 5f20b62:
  1521 passed / 101 skipped / 0 failed; +103 passed from Batches 9–13 tests
  plus the 5 new Batch 6 tests, skips unchanged). First full run in this
  batch showed 1 failure — `test_new_packs_and_skills_pass_checks` — which
  the audit traced to Batch 13, not Batch 6: Batch 13 added
  `smallest-change-review` to the taste-quality pack without updating
  Batch 10's exact-list assertion. Fixed by updating that assertion to
  the intended 3-skill list and adding the new skill to the checks loop
  (exact list kept, not weakened); re-run is the 1624/101/0 above.
- Frontend modules: **65/65 parse + link**
  (`node --experimental-vm-modules scripts/check_frontend_modules.mjs`).
- Drift test: passes (`tests/test_docs_routes_drift.py`, in the targeted
  34-test run with the Batch 10 + Batch 6 files); §13.2 is exact against
  live routes. No new route was added in Batch 6, so §13.2 needed no rows.
- Auth: catalogue endpoint correctly refuses unauthenticated requests
  (live boot check: `GET /knowledge/catalogue` → "Sign in is required");
  `/api/health` → `{"status":"ok","app":"UniversalAI"}` on a fresh temp DB.
- Playwright / smoke script: NOT run by this subagent — subagents have no
  live-browser access, and `tests/e2e/run_smoke.sh` is Playwright-based
  (`npx playwright test tests/e2e/smoke.spec.ts`). No browser check is
  claimed here; the smoke spec is the coordinator's step.

### Batch 6 honest limits

- The audit verified file/route existence and batch-test coverage; it did
  not re-exercise every batch feature live with a real model (none is
  running in this environment) — live-model, physical-phone, real-LAN/mDNS,
  Docker-isolation and real-driver browser verifications remain open, as
  in every prior batch section.
- "Native-equivalent" rows are deliberately smaller than upstream; the
  definitive table states each gap in its row rather than implying parity.
