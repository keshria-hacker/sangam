# Sangam — Attributions (perfect-flow program)

Every reference project that shaped this program, and what was
actually borrowed. Nothing here is a rebrand of another product: all
integrations are Sangam-native, and no reference project's name,
dashboard, or brand assets appear in the UI.

## Chat / agents / orchestration

- **pi (pi-mono)** — hooks, durable approvals, real cost meter.
  Borrowed: the hook points and the approval durability shape.
- **spec-kit** — the spec chain (constitution → spec → clarify →
  plan → checklist → tasks → analyze → implement → verify →
  converge) with real per-task agents and package-gated review.
- **council / hive patterns** — Deliberate mode + ledger; Teams v2
  with capped debate as the MiroFish-swarm substitute (the swarm
  itself was not ported).
- **dify / langflow** — visual workflow canvas shape; the workflow
  runtime itself is Sangam's DAG engine (typed nodes, cycle
  detection, timeouts/retries, dead letters, idempotency, replay).
- **mem0 / MemPalace** — typed memory + importance-ranked recall
  shape (Memory V2); the implementation is Sangam's.
- **crawl4ai** — BFS crawl + URL ingest shape for notebooks.
- **browser-use** — two-mode browser agent, behind the same
  per-run-approval + sandbox + audit guardrails as the security
  tools. Real-driver runs were not exercised end to end here.

## Code / QA / dev workflow

- **keploy** — pattern only (record → replay → generate tests).
  eBPF/time-freeze machinery was NOT ported.
- **harper** — the lint word-list approach for the suggestions-only
  Harper module (never autocorrects; ~1,370 words; flags some correct
  rare words).
- **code-graph / graft tools** — code-map correctness + freshness
  shape, JS/TS support added honestly alongside Python/Go/Rust/Java
  (no 160-language claim).

## Media / design / classroom

- **fooocus** — prompt controls shape (weights/wildcards/LoRA/
  embeddings/sampler controls). Real diffusion was not run here.
- **diagram catalogue** — 44 types, SVG/HTML export; the catalogue
  is Sangam's, PNG export is honestly 422 without a raster renderer.

## Platform / system

- **coolify / quickemu** — connector interface only, deferred as
  core (user-approved default 4). No clone was built.
- **openpanel** — analytics-shape inspiration for the local-first
  usage ledger (telemetry default OFF).
- **superpowers / skills repos** — the SKILL.md contract shape and
  the curated-pack model (Engineering / Science / Creative-Design).
- **pentest-agents / hackingtool / strix** — the security workspace
  shape (Recon → Vuln-hunter → Validator → Reporter) under
  per-run approval, sandboxed execution, audit log, own-systems-only
  guardrails. Exploitation, bypass, and backdoor tooling were
  explicitly NOT built.
- **orca** — worktree + diff-annotation shape for the Code
  companion (worktrees, diff annotation, mobile companion shape).

## Explicitly NOT borrowed

- **winutil** Windows mechanics (pattern only, no OS tweaks shipped).
- **claw-code** product + auto-healing (not ported).
- **REA** (external MCP only, no reimplementation).
- **Coucou / Mochi** brand assets (never shipped).
- **Video production / voice cloning** (user-confirmed skips).
