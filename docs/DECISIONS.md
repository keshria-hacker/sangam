# Sangam — Decisions (perfect-flow program, 2026-10-25)

Decisions taken by the user or the coordinator during the perfect-flow
program (spec: `~/workspace/user/files/prompt.txt`, received 2026-10-25).
Where the spec conflicted with an earlier explicit user decision, the
earlier decision wins unless the user re-decided it here. Standing rules
from before this program (single-user + LAN, vanilla JS, SQLite for
single-user self-hosting, integrations Sangam-native and rebranded, Chat
is the only chat surface, verify beyond green suites) still apply.

## User-approved defaults (2026-10-25, "use recommended defaults, go non-stop")

1. **Auto routing signal.** Auto web-searches when the query carries
   date/news/price/version signals, otherwise answers directly.
   Implemented as a rule-first router (`backend/response_intelligence/`);
   the deterministic keyword scorer is the only "classifier" and is
   labelled as such — never a model call.
2. **First-run providers.** First-run offers a cloud key AND local
   Ollama, pre-selecting Ollama if detected. The look-around path uses
   a clearly labelled SAMPLE panel, never a fake response.
3. **First three skill packs.** Engineering, Science, Creative/Design.
   The Science pack is a 5-skill curated slice, labelled as such — not
   a claim to import all 177 science skills.
4. **Coolify / Quickemu deferred.** The deploy connector interface
   exists and reports `deferred`; the core is not blocked on it.
5. **Browser support.** Chromium + WebKit via Playwright; Firefox
   best-effort and documented as such.
6. **Telemetry.** Default OFF.
7. **Video production SKIPPED this round.** Studio covers
   documents/design/diagrams/image/voice/classroom only. The spec's
   agentic video pipeline is not built (it conflicts with the user's
   2026-10-24 skip, re-confirmed here).
8. **Voice cloning SKIPPED.** TTS/STT/dub/dictation only, no cloning
   (same re-confirmation).
9. **IA swap CONFIRMED.** Chat / Projects / Studio / Code / Research /
   Agents / Library / Settings. Work and Create are flattened into
   first-class destinations, not containers. This supersedes the
   7-destination IA shipped hours earlier (Chat + Home + Work + Create
   + Knowledge + Library + Settings).

## Architecture decisions taken by the coordinator during merges

- **Merge order A3 → A5 → A6 → A2 → A4 → A1.** A1 (shell) went last
  because it re-homes every other specialist's UI; merging it first
  would have forced every specialist to rebase onto a moving shell.
- **Shell-first startup (fix, commit 4f4118f).** The rail and command
  palette initialise before the provider/model probe, because without
  Ollama `/models` burns ~13s on auto-start retries and the shell sat
  unrendered while the app looked booted. The probe cost itself is
  pre-existing backend behaviour (kept, with its 120s cooldown).
- **Rail clicks must pushState (fix, commit 4f4118f).** `showTool()`
  treated `resolveLegacyId()` as legacy-only, but that helper also
  resolves current ids, so rail clicks rendered destinations without
  changing the URL. Current ids now navigate with pushState; old ids
  still redirect.
- **Mobile drawer closes on navigation (fix, runs gate).** Tapping a
  rail destination on a phone closes the off-canvas drawer, matching
  the existing chat-history behaviour; otherwise the drawer covered
  the destination just opened.
- **Screenshot baselines follow the IA, not the reverse.** The
  runs-centre baseline was regenerated because the old image showed
  the deleted Chat/Work tab strip and Work → Activity layout. The new
  baseline was inspected (rail, Agents → Run History, same Runs centre
  content, exactly one guided empty-state action) before regenerating.
- **Spec-guard hygiene.** The shared `ctx.loggedIn` flag in
  runs.spec.ts/shell.spec.ts is reset at `register()` start, so a
  later test's expected pre-login 401 (usage meter) is not mis-flagged
  as post-login. The app behaviour (401 before auth, "Usage
  unavailable" meter) is by design, not a bug.

## Hard out-of-scope (do not build; reasons)

- Video production, voice cloning: user-confirmed skips (above).
- Multi-user RBAC/SSO: single-user + LAN pairing stands.
- Coolify/Quickemu as core: connector interface only (above).
- MiroFish swarm whole: the capped debate substitute already exists.
- REA reimplementation: external MCP only.
- winutil Windows mechanics: pattern only, and only as an opt-in
  clearly-labelled reversible surface if at all (prefer not shipping
  OS tweaks).
- claw-code product + auto-healing: product, not a feature to port.
- Keploy eBPF/time-freeze: kernel-level machinery, out of scope for a
  self-hosted chat app.
- Unrestricted exploitation / bypass / backdoor tooling, third-party
  targeting without proven scope, auto-install-and-run of arbitrary
  tools: excluded by the security guardrails (per-run approval,
  sandboxed execution, audit log, own-systems-only).
- Coucou/Mochi brand assets: never ship another project's branding.
- Importing all 177 science skills or 100+ templates as tabs: tabs
  are not the IA; curated packs with hash verification instead.

## Open decisions (unchanged, awaiting the user's word)

- Merge `integration/full-program` into `main` (branch ~140+ commits
  ahead; main untouched since 2026-10-09). No action without his word.
- Physical phone QR scan, real two-device mDNS, Docker isolation
  live, real-driver browser-agent runs: unverified in this
  environment, carried as honest limits, not claimed.
