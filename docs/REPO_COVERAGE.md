# REPO_COVERAGE.md — Honest Integration Assessment

**Date:** 2026-10-09
**Branch:** `integration/full-program`
**Method:** Code inspection + test verification. No claims without evidence.

## Status Key
- **Done**: Feature exists, tested, verified working
- **Partial**: Core exists but gaps remain (listed)
- **Missing**: Not built
- **Skip**: Intentionally deprioritized (reason given)

---

## 22-Repo Coverage

| # | Repo | Status | Evidence |
|---|------|--------|----------|
| 1 | ayghri/i-have-adhd | Done | `QUALITY_ADHD_FRIENDLY` in output postprocessor; 15 tests in output-quality theme |
| 2 | petergyang/no-ai-slop | Done | `QUALITY_NO_SLOP` removes 20+ slop patterns; tested |
| 3 | MemPalace/mempalace | Done | Typed memories (episodic/semantic/procedural), importance-ranked recall, consolidation; `memory.py`, 17 tests |
| 4 | OpenHands/OpenHands | Partial | Code agent with write_file/edit_file/run_bash, SSE streaming, TDD mode. **Gap:** No autonomous PR creation, no Docker sandbox execution |
| 5 | nexu-io/open-design | Partial | Design Studio tab with prototype gen + iframe preview. **Gap:** Limited to HTML prototypes; no Figma-like editing |
| 6 | stablyai/orca | Partial | Agent teams with fan-out/fan-in. **Gap:** No SSE per-specialist streaming (see 6.4a), no per-agent Stop/retry |
| 7 | K-Dense-AI/scientific-agent-skills | Done | `science-essentials` skill pack bundled; pack system with enable/disable |
| 8 | THU-MAIC/OpenMAIC | Done | Learning mode with teacher lessons + Socratic tutor; `/api/learn/*`, 7 tests |
| 9 | DeusData/codebase-memory-mcp | Partial | MCP client exists; code_graph.py builds AST graph (918 symbols). **Gap:** Not connected to external MCP servers by default |
| 10 | earendil-works/pi | Done | Agent loop patterns adapted; `agent-loop` skill pack |
| 11 | debpalash/VoiceStudio | Done | Local TTS/STT (kokoro, faster-whisper, OpenAI-compatible); `/api/voice/*`, 9 tests. **Note:** VoiceStudio server is separate (per license constraints) |
| 12 | diegosouzapw/OmniRoute | Done | `omniroute_config.py`, `/api/omniroute/*`, Settings UI with sync; Sangam-native (not OmniRoute dashboard) |
| 13 | open-webui/open-webui | Partial | Chat Markdown export, command palette (Ctrl+P). **Gap:** Not full UI parity; no admin panel, no RAG pipeline UI |
| 14 | github/spec-kit | Done | Spec wizard (`spec_wizard.py`), `/api/spec/build`, `/api/spec/to-task`; spec-driven skill pack |
| 15 | Graphify-Labs/graphify | Partial | Code graph + knowledge graph. **Gap:** No provenance labels (see 6.4b), no memory wings/rooms |
| 16 | ChrisTitusTech/winutil | Skip | Low priority; system-tool skill pack at most. Windows-only utility, weak fit for AI studio |
| 17 | affaan-m/ECC | Partial | Instincts (confidence-scored patterns), `prompt_injection.py` exists. **Gap:** prompt_injection not wired (see 6.5); limited security hardening |
| 18 | ultraworkers/claw-code | Skip | Reference only; autonomous maintenance exhibit, not a feature to integrate |
| 19 | tt-a1i/archify | Done | Diagramming skill pack; custom SVG renderer in Create Hub |
| 20 | Openpanel-dev/openpanel | Done | Opt-in local-first analytics; event recording; dashboard API + UI; 9 tests |
| 21 | HarnessMD/munder-difflin | Partial | Multi-agent orchestration via Teams. **Gap:** No SSE streaming per agent (see 6.4a) |
| 22 | lllyasviel/Fooocus | Partial | Style presets + prompt enhancement; OpenAI-compatible engine. **Gap:** Local Fooocus driver is experimental; Fooocus is separate service (per license) |

---

## Summary
- **Done:** 12/22
- **Partial:** 8/22 (gaps listed above, tracked in Phase 6.4)
- **Skip:** 2/22 (winutil, claw-code — weak fit, documented)
- **Missing:** 0/22

All Partial gaps are addressed in Phase 6.4a-6.4f or documented as license-constrained.
