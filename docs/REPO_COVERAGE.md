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
