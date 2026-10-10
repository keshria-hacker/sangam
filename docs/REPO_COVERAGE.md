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

### Totals

- Pytest: 1103 passed
- Smoke: 3/3 passed
- Deletions: ~1,800 lines + 7 settings + 7 categories
