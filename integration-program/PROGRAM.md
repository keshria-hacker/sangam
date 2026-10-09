# Sangam Integration Program — 22-repo survey & roadmap

Date: 2026-10-08. Owner: Abhishek. Goal: make Sangam flexible/reliable for incoming
integrations, then implement capabilities drawn from 22 reference repos.

## Repo survey (what each repo is)

| # | Repo | One-line | Relevance to Sangam |
|---|------|----------|---------------------|
| 1 | ayghri/i-have-adhd | Skill: ADHD-friendly, no-fluff agent output | Output-style skill (concise answers) |
| 2 | petergyang/no-ai-slop | Removes 20+ AI writing-slop patterns | Response postprocessor upgrade |
| 3 | MemPalace/mempalace | Benchmarked open-source AI memory (ChromaDB, MCP) | Memory system upgrade (Sangam memory.py is thin) |
| 4 | OpenHands/OpenHands | AI-driven software development agents | Agentic coding workflows |
| 5 | nexu-io/open-design | Agent becomes design engine (pages, prototypes, images) | Design-generation skill |
| 6 | stablyai/orca | ADE: fleet of parallel agents, desktop/mobile/remote | Parallel multi-agent execution |
| 7 | K-Dense-AI/scientific-agent-skills | 177 validated science skills + 100+ science DBs | Skill-pack import (biology/chem/med) |
| 8 | THU-MAIC/OpenMAIC | Multi-agent interactive classroom | Multi-agent personas / learning mode |
| 9 | DeusData/codebase-memory-mcp | Codebase → knowledge graph MCP server, 158 langs | MCP client + code intelligence |
| 10 | earendil-works/pi | Unified LLM API + agent loop + TUI + coding CLI | Agent-loop patterns |
| 11 | debpalash/VoiceStudio | Fully-local ElevenLabs alternative (TTS/STT/clone, 646 langs) | Voice chat in/out |
| 12 | diegosouzapw/OmniRoute | Free MIT AI gateway: 1 endpoint, 359 providers, 1200+ models | Meta-provider (Sangam README already names omniroute) |
| 13 | open-webui/open-webui | Reference self-hosted AI UI | UX/feature parity reference |
| 14 | github/spec-kit | Spec-Driven Development toolkit | Spec→plan→tasks workflow inside Sangam |
| 15 | Graphify-Labs/graphify | Codebase+docs → queryable knowledge graph skill | Code intelligence skill |
| 16 | ChrisTitusTech/winutil | Windows tweaks/fixes/installer utility | Low priority (system-tool skill pack at most) |
| 17 | affaan-m/ECC | Agent harness optimization: skills, instincts, memory, security | Harness hardening patterns |
| 18 | ultraworkers/claw-code | Agent-maintained Rust exhibit | Reference only (autonomous maintenance) |
| 19 | tt-a1i/archify | Idea/codebase → interactive diagrams (agent skill) | Diagram-generation skill (like the map I just made) |
| 20 | Openpanel-dev/openpanel | Open-source product analytics (Mixpanel alt) | Privacy-friendly usage analytics |
| 21 | HarnessMD/munder-difflin | "Office" of Claude-Code-like agents, BYO subscription | Multi-agent orchestration |
| 22 | lllyasviel/Fooocus | Stable Diffusion image-gen UI | Local image generation |

## Theme map (integration order)

1. **Foundation** — plugin/capability system, Agent-Skills standard (SKILL.md), MCP client,
   media pipeline (voice/image message types), /api/v1 versioning, feature flags,
   reliability (retries, circuit breakers, health), coverage gate stays green.
2. **Memory+** — MemPalace patterns, codebase-memory-mcp/graphify via MCP, ECC instincts.
3. **Voice** — VoiceStudio local TTS/STT (new voice message type + mic UI).
4. **Image** — Fooocus local image gen (new image message type + gallery).
5. **Skills packs** — scientific-agent-skills, i-have-adhd, no-ai-slop (postprocessor),
   archify (diagram skill), spec-kit (SDD workflow).
6. **Multi-agent** — munder-difflin/orca/OpenHands patterns: agent teams, parallel runs.
7. **Gateway** — OmniRoute as meta-provider (359 providers, one endpoint).
8. **Design** — open-design generation workflows.
9. **Analytics** — openpanel self-hosted analytics (opt-in).
10. **Learning mode** — OpenMAIC multi-agent classroom.

## Foundation work (do FIRST — "flexible & reliable")

- F1: Unified extension registry (merge tools/ + skills/ registries; manifest, semver, enable/disable).
- F2: Agent Skills standard loader (SKILL.md drop-in from any repo).
- F3: MCP client in backend (consume codebase-memory-mcp, mempalace, etc.).
- F4: Media message types (audio/image) end-to-end: schema → SSE events → frontend renderers.
- F5: Provider hardening — OmniRoute meta-provider, retries/backoff, circuit breaker, key rotation.
- F6: API versioning (/api/v1) + feature flags in config + UI toggles.
- F7: Reliability: structured errors, health endpoint, e2e for new paths, keep coverage gate green.

## Status
- [x] F1–F7 foundation — DONE on branch `foundation/phase-0` (see integration-program/FOUNDATION.md)
- [x] Theme 2 — Memory++ (2026-10-08, branch `memory-plus`): typed memories
  (episodic/semantic/procedural), importance-ranked recall, auto-extraction,
  consolidation, memory management API, Settings UI. See MEMORY_UPGRADE.md.
- [x] Theme 3 — Voice (2026-10-08, branch `voice`): local-first TTS/STT with
  pluggable engines (kokoro, faster-whisper, OpenAI-compatible incl.
  VoiceStudio server); /api/voice/* endpoints gated by FEATURE_VOICE; mic
  dictation, per-message speak button, auto-speak setting, browser TTS
  fallback. See VOICE.md.
- [x] Theme 4 — Image generation (2026-10-08, branch `image-gen`):
  Fooocus-inspired style presets + prompt enhancement, pluggable engines
  (OpenAI-compatible, experimental local Fooocus driver), /api/image/*
  endpoints gated by FEATURE_IMAGE_GEN, generate_image agent tool, composer
  image button with media_ids attachment. See IMAGE_GEN.md.
- [x] Theme 5 — Skill packs (2026-10-08, branch `skill-packs`): pack system
  (pack.yaml manifests, enable/disable without file copying, registry
  extra_roots); 4 bundled packs — spec-driven (spec-kit), diagramming
  (archify), science-essentials (scientific-agent-skills), agent-loop (pi);
  pack API + Skills modal pack strip; skill-pack:* extensions. See
  SKILL_PACKS.md.
- [x] Theme 6 — Multi-agent (2026-10-08, branch `multi-agent`): agent teams
  with fan-out/fan-in (research, code, writing), per-agent failure
  isolation, /api/teams/* gated by FEATURE_MULTI_AGENT, Teams modal UI,
  capability:multi_agent extension. See MULTI_AGENT.md.
- [ ] Theme 7–10 integrations (scoped per theme before build)
