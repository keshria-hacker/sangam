# ALL_IN_ONE_COVERAGE.md — Definitive coverage table (85 repos)

**Date:** 2026-10-26 · **Branch:** `integration/full-program` · **Base audited:** `11b08ed`
(Batches 9–13 in this file's earlier numbering; Batches 1–5 in the coordinator's
numbering for this run) plus the Batch 6 audit corrections below.

**Method — not blind trust:** every row's cited file was checked for existence
in this tree on 2026-10-26. Where a prior batch section claimed a file or a
catalogue entry that did not exist, this audit says so under "Corrections"
and fixes it instead of repeating the claim. "Shipped" never means upstream
parity: it means Sangam's own implementation of the portable mechanism exists,
is reachable, and is covered by a batch test or an older test. Partial ports
state exactly what was NOT ported in the same row.

**Classifications (exactly one per repo):**
- **shipped** — Sangam-native implementation of the portable mechanism exists.
- **native-equivalent** — the user-visible shape is covered by a different
  Sangam-native mechanism, a catalogue/documented row, or a deliberately
  smaller safe subset; the row states what is missing.
- **excluded** — deliberately not built, with the reason in the row. An
  exclusion is an honest outcome, not a gap left unaccounted for.

**Counts: shipped 58 · native-equivalent 22 · excluded 5 · total 85 · unaccounted 0.**

**Destinations:** unchanged — Chat / Home / Work / Create / Knowledge /
Library / Settings with sidebar navigation. No new destination, no
perfect-flow / tabs-on-top / 8-destination restoration, no Projects surface.

**Standing exclusions (apply to every row):** voice cloning, video
generation, unrestricted exploitation, CAPTCHA/WAF bypass, DDoS, RAT,
phishing, third-party targeting, Coolify clone, arbitrary code execution,
multi-user RBAC, React, Postgres. Single-user, vanilla JS, SQLite,
modular monolith throughout.

## Definitive table

| # | Repo | Class | Evidence (file / route) + what is NOT ported |
|---|------|-------|----------------------------------------------|
| 1 | i-have-adhd | shipped | `mainfiles/backend/response_quality/adhd.py` (`pre_send_check`, `restate_state`) + Chat wiring; post-hoc transform unchanged |
| 2 | no-ai-slop | shipped | `mainfiles/backend/response_quality/structure.py` (detect-only) + `eval.py` checklist; `POST /quality/preview` gains `structure` + `eval` |
| 3 | mempalace | shipped | Typed memories, rooms/drawers browser, `mainfiles/backend/memory/observations.py`, `markdown_notes.py`, graph-edge confidence decay (90-day half-life, 0.05 floor) |
| 4 | OpenHands | shipped | `mainfiles/backend/code_agent.py` (write/edit/run, SSE, TDD, approval gate) + `agent_runtime/sandbox.py` as default code-agent context; Docker runtime NOT ported, Docker isolation NOT claimed verified live |
| 5 | open-design | shipped | `mainfiles/backend/media_pipeline/design.py` + `POST /design-systems[/{id}/critique\|/transform]` contract/critique/transform; prototype generation stays on the Code Agent path; stock search/staging NOT ported |
| 6 | orca | shipped | Teams fan-out/fan-in + SSE per-specialist + per-agent Stop/Retry + `agent_runtime/orchestration.py` typed `ask`/`gate` nodes + worktree handoff; worktrees/SSH in `worktrees.py` |
| 7 | scientific-agent-skills | shipped | Science skill pack + validated frontmatter (`allowed_tools`/`compatibility`/`version`/`last_reviewed`) in registry + verify; 177-skill breadth NOT curated (content, not code) |
| 8 | OpenMAIC | shipped | `mainfiles/backend/api_routes/learn_routes.py` (`/learn/outline`, `/learn/quiz`, `/learn/grade`) + guarded slide/lesson outline `POST /research/jobs/{id}/slides` (citations outside the report dropped); no slide editor, no video |
| 9 | codebase-memory-mcp | shipped | `mainfiles/backend/research/code_memory.py` (refresh-if-stale, `change_impact`) over `code_graph.py`; no watcher daemon (on-demand, single-user) |
| 10 | pi | shipped | `mainfiles/backend/agent_runtime/loop.py` (steering queue, abort at step boundaries, parallel-by-default planning, structured compaction + branch resume) |
| 11 | VoiceStudio | shipped | `mainfiles/backend/voice/service.py` + `media_pipeline/audio.py`: chunked TTS, audiobook plan, TRUE dubbing (timed segments → SRT/VTT/word-level ASS); VOICE CLONING excluded — no clone endpoint, no reference-audio field; dub without supplied segments is 422 (timings never invented) |
| 12 | OmniRoute | shipped | `mainfiles/backend/omniroute_config.py` + `providers/fallback_chain.py` strategies (priority, cost-optimized, headroom, quota-weighted, round-robin, fail-closed) + session pinning; the 375-provider gateway, quota-share pooling and token compression NOT built |
| 13 | open-webui | native-equivalent | Chat Markdown export (`GET /chats/{id}/export`), command palette (Ctrl+P), `prompt_transform` catalogue entry + starter graphs; eval harness NOT built; multi-user RBAC, groups, shared chats, OAuth/SCIM excluded |
| 14 | spec-kit | shipped | `mainfiles/backend/spec_chain.py` (spec/plan/tasks/coverage) + `POST /devqa/spec/constitution/check` + `POST /devqa/spec/mvp-order`; clarify-before-spec gate and checklist artifacts NOT built — see Corrections: `spec_wizard.py` is retired, not a live file |
| 15 | graphify | shipped | `mainfiles/backend/knowledge_graph.py` + `graph_provenance.py` (EXTRACTED/INFERRED/AMBIGUOUS, memory wings, rooms/drawers) + code-map `detect_hubs`/`surprising_links`; full cross-source unified graph NOT built |
| 16 | winutil | native-equivalent | `GET /devqa/platform/winutil-catalog` (read-only checks + documented-only tweaks) + `GET /devqa/platform/health-actions` (risk + reversibility declared); NOTHING is executed by the server — registry/debloat/AppX/winget execution excluded; the user runs checks on their own Windows machine |
| 17 | ECC | shipped | `mainfiles/backend/instincts.py` + `prompt_injection.py` wired into `/chat/stream` (warn-only); hook matchers (allow/deny/annotate), reviewer-agent library and skill-health scoring were NOT wired in Batch 12 — stated, not claimed |
| 18 | claw-code | shipped | `mainfiles/backend/agent_runtime/approval.py` async approval channel (risky call waits in the tray while the run continues with independent calls only); earlier "reference only" note superseded by Batch 10 |
| 19 | archify | shipped | `mainfiles/backend/diagram_ir.py` typed IR family (architecture, erd, sequence, workflow, timeline) with strict validation + fixable diagnostics; browser-check evidence, position-only layout repair and other archify renderers NOT ported |
| 20 | openpanel | shipped | Opt-in local-first analytics (`/analytics/*`, Arena leaderboard `GET /arena/leaderboard`) + declared event taxonomy (`POST /devqa/platform/analytics/event`, 422 on unknown events) + session funnels over supplied events; no second tracker, no ClickHouse |
| 21 | munder-difflin | shipped | Multi-agent Teams (see orca row) + hive mode (inbox-drain before finish, critical-only escalation, single-committer path); no pixel art reused (per license) |
| 22 | Fooocus | shipped | `mainfiles/backend/image_gen/styles.py` (20 ORIGINAL styles, not the GPL-3.0 style files), performance presets as engine-parameter bundles, deterministic wildcard+style expansion shown as an explicit step (NOT Fooocus's LLM expansion, labelled as such), PNG mask in/out + feathering; FaceSwap / IP-Adapter-face excluded; "upscale" stays labelled local resize, not AI upscaling |
| 23 | OpenMontage | shipped | `mainfiles/backend/media_pipeline/stages.py` (stages, checkpoints, revision cap, `known: false` cost) + SRT/VTT/ASS + storyboard still prompts; VIDEO output, Remotion composition, talking-head, clip-factory NOT ported (excluded) |
| 24 | dify | shipped | `human_input` workflow node (pause + exactly-once resume, replay-from-start limitation stated) + variable-pool validation (`POST /devqa/workflows/validate`) + 3 starter graphs (chatbot/agent/workflow); trigger-as-node and workflow-as-chat-app publish NOT built |
| 25 | crawl4ai | native-equivalent | `/devqa/crawl/*` helpers (frontier ordering bfs/dfs/best_first, composite scorer, FilterChain, chunking, link-graph); NOT threaded into `crawl_job.run_crawl` or the workflow `crawl` node, which remain BFS-only — threading is future work, not claimed |
| 26 | langflow | native-equivalent | Typed node catalogue (`GET /devqa/node-catalogue`) over exactly the engine's closed node set (15 + `human_input`); fan-out is DAG edges, sub-flow is a workflow run by id — documented, not fake nodes; no React rewrite, no multi-tenancy |
| 27 | browser-use | native-equivalent | `mainfiles/backend/browser_agent.py` two separately gated modes (automation vs security-test), allowlisted, per-mode approval, isolated profile, action/screenshot logging; DOM snapshot action, judge verification step and session/watchdog recovery NOT built |
| 28 | impeccable | shipped | `mainfiles/backend/media_pipeline/design.py` measured critique (real WCAG contrast ratios, gold-small-text rule, hairline, hard-offset shadows, tiny type, overflow risk, off-contract colours, each with measured value + fix) + bolder/quieter/distill token operations; Rust raster/component metrics and full 24-command set NOT ported |
| 29 | taste-skill | shipped | `mainfiles/backend/skills/bootstrap.py` declared `scripts.json` manifest + `creator.evaluate_blind` (with-skill must strictly beat without-skill) + original `design-taste` skill in the `taste-quality` pack; gallery content NOT copied |
| 30 | pentest-agents | shipped | `mainfiles/backend/qa/devqa.py` + `/devqa/security/*`: scope-file import + hard check (wildcard domains, CIDR, excluded-wins), finding fingerprinting + dedup, CVSS-version guard, guided phase checklists; WAF-bypass protocol excluded in its entirety; bounty/third-party targeting excluded (own-systems-only) |
| 31 | open-notebook | shipped | `GET /notebooks/{id}/timeline` + notebook-scoped deep-research jobs; multi-speaker podcast NOT built (TTS composition only, no voice cloning) |
| 32 | llmfit | shipped | `mainfiles/backend/model_fit.py`: per-use-case weights shown in every row, weighted scores, bandwidth roofline speed estimate (labelled estimated, 50 GB/s DDR default), measured-benchmark override (plausible ≤10000 tok/s marked measured, implausible ignored with a note), MoE total-vs-active note, AWQ/GPTQ kernel-fallback flag; role-rubric routing matrix NOT built (would need real rubric runs, not invented scores) |
| 33 | iwe | shipped | `mainfiles/backend/memory/markdown_notes.py` (dated typed notes, browsable directory, normalize merge pass) |
| 34 | MiroFish | native-equivalent | `mainfiles/backend/teams/debate.py` `position_ledger()` + `scenario_branches()` + `closing_report()` + `/teams/debate/scenarios` + `/teams/debate/jobs/{id}/report`; OASIS/Zep thousand-agent simulation explicitly NOT built |
| 35 | mem0 | shipped | `mainfiles/backend/memory/ops.py` mem0-style ADD/UPDATE/DELETE/NONE op loop (preview never writes; apply needs `confirm=true` + known ids only) |
| 36 | diagram-design | shipped | `diagram_ir.verify_layout` + `POST /diagrams/verify` (4px grid, single accent, label/node budgets, rectangle overlap on computed geometry) + `POST /diagrams/export` (standalone HTML+SVG); full 45-type catalogue and per-type verifiers NOT ported |
| 37 | awesome-llm-apps | shipped | `mainfiles/backend/research/catalogue.py` as data: 8 named LLM patterns each mapped to its Sangam operation; nothing auto-installs or executes |
| 38 | agency-agents | shipped | `mainfiles/backend/teams/review_schema.py` severity-tier review schema (blocker/suggestion/nit, parses 🔴/🟡/💭 and Must/Should/Nice); roster-consistency is the existing `persona_registry.validate_roster` |
| 39 | Graft | shipped | `mainfiles/backend/code_graph_queries.py` BM25 (k1=1.2, b=0.75) + IDF over symbol text + test-path de-rank 0.35x + Python `extends` edges (unique resolution only); concept/module layer and ask-index sidecar NOT built (symbol bodies are not stored, only body_hash) |
| 40 | gstack | native-equivalent | Portable discipline only: Ponytail-shaped `/quality/check` findings + code-graph `orphans` + `layering_check`; NOT separate engines; `deslop-shared-libs` kept distinct from prose de-slopping in naming and docs |
| 41 | ponytail | shipped | Ponytail report contract in `/quality/check` (ranked must-fix first, concrete case + fix + if-skipped, not-checked/risks footer) + original Sangam-authored `smallest-change-review` SKILL.md in the taste-quality pack; Claude-Code "band" cost/reuse meter NOT ported (harness-dependent) |
| 42 | council-of-high-intelligence | shipped | `mainfiles/backend/council_mode.py` panel selection, domain-seat locking, restate gate, distinct Chairman synthesis (opt-in), enforcement re-prompts (dissent quota, novelty, missing stance — max one per member), session metadata, verdict-specific kill criteria; tally arithmetic untouched and still exact; Chat Council mode renders verdict + tally + minority report + ledger id |
| 43 | quickemu | native-equivalent | Pre-flight gates (fail closed, `docker_unavailable` when Docker is off and fallback disallowed) + `GET /devqa/platform/vm-profiles` as documented external-tool configs only; Sangam never launches a VM, never claims a hypervisor, never downloads or licenses an OS image |
| 44 | paperclip | shipped | Research jobs mirrored into the Runs centre (`kind=research`) on completion — governance only; no task-board / multi-user shape |
| 45 | hindsight | shipped | `mainfiles/backend/memory/observations.py` observation ledger (claim + verbatim quote evidence + proof count + strengthen/weaken history + expiry/supersede); chat recall injects top observations ahead of raw memories; mental-model standing pages NOT built |
| 46 | overmind | shipped | `agent_runtime/orchestration.py` `propose_from_eval`: propose (never silently apply) a model/prompt change with the eval delta as evidence |
| 47 | autoskills | shipped | `mainfiles/backend/skills/recommend.py` (`detect_stack`, stack-aware recommendations) + `importer.py` + `verify.py` (SHA-256 lockfile); no new installer built |
| 48 | harper | shipped | Three Harper-shaped deterministic rules wired into `writing_lint.lint_text` + `/quality/lint` (a/an agreement with hour/honest-type exceptions, double comparatives, common typos — span + suggestion, never auto-rewrite); user dictionary persistence and dialect (US/UK) setting NOT built |
| 49 | e2e | native-equivalent | Test tags (cold/live/quarantined) + suite report (quarantined passes are not green) + JS lint ruleset; agent-driven "explore this destination" mode, budgeted QA runs with screenshots and self-healing locators NOT built (need Playwright-harness work) |
| 50 | keploy | shipped | `POST /devqa/qa/cassette-to-test` (cassette → pytest, returned never written to `tests/`) + `POST /devqa/qa/replay-diff` (noise-stripped diff); cassettes carrying auth/cookie/API-key headers rejected; live-traffic recording from Sangam sessions NOT built (cassettes are caller-supplied) |
| 51 | javascript-testing-best-practices | native-equivalent | Test tags + suite-report verdict + JS ruleset (no-console-in-prod, no-bare-specifier, testid-for-interactive) as findings-only checks; per-route API contract (response-shape) tests NOT added — the drift test covers route presence, not schemas |
| 52 | PersonalJarvis | shipped | `mainfiles/backend/agent_runtime/drivers.py` `RuntimeDriver` protocol + `LocalCommandDriver` (detect/start/health/kill/log-tail); API exposes detection only — spawning is host-operator initiated, never an API request (would be unrestricted execution) |
| 53 | coucou | shipped | Persistent "Needs you" tray in Work → Agents → Approvals (`mainfiles/frontend/js/features/agents/hub.js`), fed by the async approval tray; no new approval backend |
| 54 | rea | shipped | Every code-graph answer gains an `evidence` block (sources file:line + body_hash, dropped ambiguous/unresolved/extends counts, skipped dirs, file-cap flag, freshness pointer to `/knowledge/graph/check`); binary/JS-app reverse engineering and disassembly NOT ported (own workspace code only) |
| 55 | coolify | native-equivalent | Service-health dashboard data (registered URLs, live probes with `trust_env=False`, SQLite uptime history) + health-action catalogue + analytics taxonomy/funnels; NOT a Coolify clone — no deployment engine, queue, scheduled backup execution, or executed restore dry-run |
| 56 | superpowers | shipped | Subagent-per-task `TaskGraph` (blocking edges, ready frontier, per-task review gate, branch review) + four-stop-rule contract; skill evals now require a failing baseline before publish |
| 57 | anthropics/skills | shipped | Description word-budget check (warning over ~100 words, not a failure) + trigger-accuracy evals (`creator.trigger_eval`) in the publish path; format itself was already implemented |
| 58 | mattpocock/skills | shipped | Ticket-graph flow is the same `TaskGraph` engine as superpowers; skill-to-skill invocation rule was already in `registry.check_skill_call` |
| 59 | Dodaios | excluded | Standalone Dodaios repo: deep-read brief never arrived (clone absent) — nothing claimed or built from it. Distinct from PersonalJarvis's `dodaios` package, covered under row 52. |
| 60 | hackingtool | native-equivalent | Tool availability probing (binary + install hint, Sangam never installs) + wholesale rejection of excluded categories (`POST /devqa/security/categories/reject`); install/update lifecycle and per-tool output parsers NOT built; excluded categories: ddos, phishing, remote-admin, post-exploitation, exploit-frameworks, anonsurf, wireless, payload-creator-as-weaponizer |
| 61 | strix | native-equivalent | Sandbox pre-flight gates failing closed + computed coverage ledger (undefined, never 100%, on zero discovered); reusable labelled sandbox sessions with caps + guaranteed cleanup, proxy integration and scheduled CI passive-scan mode NOT built; existing Docker-or-workspace-fallback behaviour unchanged |
| 62 | oh-my-claudecode | excluded | Deep-read brief never arrived (clone absent) — nothing claimed or built from it. |
| 63 | invisible_dots | excluded | Self-hosted VM-agent platform ("Dots") whose headline property is undetectability by anti-bot systems, running its own VM desktop/browser identities. Not portable to Sangam (different product: VM agent fleet) and its undetectability goal conflicts with Sangam's guardrails. |
| 64 | gpt-researcher | shipped | `mainfiles/backend/research/deep_research.py` state machine (plan → breadth → depth recursion capped/deduped → curate → word-budget compress → cited report writer that 422s on uncited claims); planner is deterministic templates + keyword follow-ups, honestly labelled — no LLM in this path |
| 65 | ego-lite | shipped | `mainfiles/backend/skills/bootstrap.py` `bootstrap_command` skill support (approval-gated, argv-only, 4000-char cap, banned-pattern scan; shell metacharacters rejected) |
| 66 | andrej-karpathy-skills | shipped | `coding-guidelines` (original Sangam wording, not copied text) added to the engineering pack; injected by default for code runs via the existing auto-fire path |
| 67 | repomix | shipped | `mainfiles/backend/research/pack.py` + `POST /knowledge/packs` (workspace-gated tree + contents + chars/4 token estimates + chunk splits; credential filenames and secret-like content filtered — listed, never included; binary skipped) |
| 68 | awesome-mcp-servers | shipped | `mainfiles/backend/research/catalogue.py` as data: 10 curated MCP server entries with official/community flag, install route (user/manual), risk note, Sangam equivalent; nothing auto-installs or executes |
| 69 | odysseus | shipped | Frozen `TurnContract` (`required <= offered <= executable`, schema snapshot) with no-substitution rule (unavailable → stop and say so) + slow-tool promotion rule (60s budget → background job in Runs feed), both in `agent_runtime/loop.py` |
| 70 | Turnitout-Humanizer | shipped | `POST /quality/humanize` + per-message "Natural rewrite" button (slop removal, filler deletion, >45-word sentence splits — labelled readability only); AI-detection evasion, detector-bypass guarantees, authorship concealment, invisible-character handling and auto-citation fabrication are EXCLUDED and stated in code, UI, route response and here |
| 71 | Understand-Anything | native-equivalent | Staleness surfaced as a `stale`/`rebuilt` flag on code-map refresh; embedding search over code symbols and job-specific explain/diff/domain/onboard modes NOT built |
| 72 | shannon | native-equivalent | Principle only: "No evidence, no claim" adopted for research reports (422 on uncited claims); no recon/exploit/validation pipeline imported |
| 73 | pentagi | excluded | Autonomous multi-agent pentesting (including Metasploit-class tooling) — autonomous exploitation is excluded by the standing guardrail. Only the already-existing Sangam engagement shape (runs/phases/findings/report) plus guided checklists are used, always per-run-approved and own-systems-only. |
| 74 | manimgx | native-equivalent | Video output EXCLUDED (Rust/wgpu 3D animation engine whose output is MP4). Salvage shipped: scene-plan validation + still-image prompts per scene (`mainfiles/backend/media_pipeline/storyboard.py`, `POST /media/storyboard`); no renderer, no motion, durations labelled plan estimates only |
| 75 | Open-Generative-AI | native-equivalent | Catalogue reference row added in Batch 6 (`ref-open-generative-ai` in `research/catalogue.py`, searchable via `GET /knowledge/catalogue`); model-catalogue shape already exists as provider/engine registries; video, lip-sync and unrestricted-generation studios EXCLUDED |
| 76 | flowsint | shipped | Source graph (`GET /research/jobs/{id}/source-graph`) over the job's OWN retrieved sources only (same-domain + mention edges); no person/IP/breach enrichers, no third-party targeting |
| 77 | reverse-skill | shipped | Sangam-native mechanism in `mainfiles/backend/skills/reverse.py` + `POST /skills/propose-from-transcript` + `POST /skills/drafts/save` (drafts live outside the skills root, never auto-loaded); clone absent, so nothing is claimed from upstream text — the mechanism, not the repo's content, is what shipped |
| 78 | heretic | excluded | Model censorship removal (directional ablation / abliteration) — a safety-bypass tool. Nothing built from it, no endpoint, no flag, no catalogue mention. |
| 79 | ComfyUI | shipped | Sangam-native graph in `mainfiles/backend/media_pipeline/graph.py` (fixed node registry, typed sockets, missing-input/type-mismatch/double-link/cycle validation, topological execution) executed ONLY through handler callables wired to Sangam's existing engines; custom-node code execution NOT ported (rejected as unknown-node); missing engine → 503, never a fake output |
| 80 | anything-llm | native-equivalent | Generic shapes only: prompt-template library, chat folders, shareable model presets (`/devqa/chat/*`, share payload states `shares_keys: false, shares_history: false`); multi-user workspaces, invites, agent flows and embed chats excluded; nothing claims anything-llm parity beyond these shapes |
| 81 | LibreChat | native-equivalent | Same generic shapes as row 80 (folders, prompt templates, model presets); multi-user accounts, SSO/2FA, plugins, code environments and shared conversations excluded |
| 82 | Vane | native-equivalent | Catalogue reference row added in Batch 6 (`ref-vane` in `research/catalogue.py`); search/research shape already covered by websearch + Batch 9 research jobs; no Vane code built (its pattern is search, not media) |
| 83 | gotify | native-equivalent | Webhook-in + in-app inbox (`/devqa/platform/notifications/*`): a secret must be configured (`SANGAM_DEVQA_WEBHOOK_SECRET`) and matched, otherwise webhooks are refused — no open inbox; no external push service (FCM/APNs/WebPush) and no websocket stream claimed |
| 84 | imajev | native-equivalent | Catalogue reference row added in Batch 6 (`ref-imajev` in `research/catalogue.py`): decision shape (options + probabilities + abstain threshold) documented as a future pattern for critique/decision outputs; model weights NOT run, no fake model call |
| 85 | sketchvlm | shipped | `mainfiles/backend/media_pipeline/overlay.py` + `POST /media/overlay`: validated annotations (point/label/arrow/rect/circle/path in normalised coordinates), standalone SVG render, source image untouched; no VLM is run here — the overlay is the contract a model or user fills in |

## Filled in Batch 6 (audit corrections, not new systems)

1. **imajev / Vane / Open-Generative-AI catalogue rows** — Batch 11 described
   these as "catalogue entries", but `research/catalogue.py` contained no such
   rows. Added as `reference_note` rows (`ref-imajev`, `ref-vane`,
   `ref-open-generative-ai`), searchable via `GET /knowledge/catalogue`
   (including `kind=reference_note`), each stating its Sangam equivalent and
   its exclusion. No model, install, or code port was invented to fill them.
   Covered by `tests/test_coverage_audit_batch6.py`.
2. **spec-kit file correction** — the old 22-repo table cited
   `spec_wizard.py`; that file is retired (see `spec_chain.py` header and
   `spec_routes.py` header). Coverage now cites `spec_chain.py` + the devqa
   constitution/mvp-order routes. `ARCHITECTURE.md`'s tree line for
   `spec_wizard.py` is corrected in the same commit.
3. **claw-code status correction** — the old table said "Skip / reference
   only"; Batch 10 shipped the async approval shape, so the row is now
   `shipped` (async shape only), not a full claw-code port.
4. **browser-use / ECC "not built in Batch 12" clarified** — those Batch 12
   notes mean "not built *in that batch*". Both have pre-existing
   implementations (two-mode browser agent; prompt-injection wired into
   chat) that stand, so both rows are `native-equivalent`/`shipped`
   respectively with the Batch 12 gap stated, not hidden.

## Honest limits carried forward (whole run)

- Physical phone QR scan, real two-device LAN/mDNS, Docker isolation live,
  real-driver browser-agent runs, live model pipeline/council runs, and real
  Fooocus diffusion remain unverified in this environment (no device, no
  Docker, no live model here) — stated in every batch section, not re-claimed.
- Benchmark numbers are never presented as measured unless a stored local
  benchmark exists for that exact catalogue id; otherwise they are labelled
  estimates (model_fit).
- Cost is `known: false` wherever no engine reports cost; budgets never trip
  on invented numbers (media stages).
- Frontend wiring is module-link-checked, not browser-verified by subagents
  (no live browser for subagents); Playwright verification is the
  coordinator's step — see the Batch 6 verification section in
  `docs/REPO_COVERAGE.md`.
- Crawl helpers (row 25), ECC hook matchers (row 17), strix reusable sessions
  (row 61), e2e agent exploration (row 49), and the Graft concept layer
  (row 39) remain explicitly unbuilt; they are future work, not coverage.
- Knowledge Export is still memories-JSON only; diagram PNG export is
  client-side canvas rasterisation of the SVG (no server raster renderer);
  lesson-player TTS is not wired; legacy pipeline finish still accepts
  pasted-text reviews (compat).
