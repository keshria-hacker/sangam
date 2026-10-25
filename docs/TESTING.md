# Sangam — Testing (perfect-flow program)

## The rule

Never trust a green suite alone. Every merge in this program was
verified with: pytest after the merge, the frontend module check,
live endpoints where the claim needed them, and Playwright paths
for anything the user can see. Test totals below come from actual
runs on `integration/full-program` at the commits listed, not from
specialist reports.

## Final totals (this program, coordinator runs)

- **Full pytest suite: 1613 passed, 101 skipped, 0 failed**
  (380s). Previous baseline at `740306f`: 1521 passed, 101 skipped,
  0 failed. The suite grew by 92 tests across the six merges and
  stayed green. One stale expectation was fixed by the coordinator
  during the gate (`test_pack_extensions_registered`: 6 → 7, the
  seventh pack is A6's creative-design pack — see `FIX_LOG.md`).
- **Frontend module check: 70/70 parse + link**
  (`node --experimental-vm-modules scripts/check_frontend_modules.mjs`).
- **Smoke gate: 3/3** (`bash tests/e2e/run_smoke.sh` — the required
  gate; the execute bit is missing, always run via `bash`).
- **Playwright specs, one at a time, ~5s settle between runs
  (shared ports :8001/:5500): 25/25 green**
  - shell 5/5, smoke 3/3 (counted above as the gate, listed here
    for the spec total), runs 2/2, workflows 1/1, security 1/1,
    devices 1/1, fit 2/2, diagrams 2/2, media 1/1, knowledge 1/1,
    notebooks 1/1, skills 4/4.
  - Spec runners are throwaway scripts in `/tmp` built by
    sed-rewriting `run_smoke.sh` (replace the spec name AND the
    `REPO=` line); they are never committed.
- **Auto routing golden set: 50/50 intent+mode agreement** (bar
  ≥90%); the deterministic keyword scorer was used on 1/50 prompts
  (98% rule coverage). Test-covered by A2's suite.
- **Drift + auth checks** ran green after every merge (route table
  in `ARCHITECTURE.md` §13.2 enforced against the live router).

## Retire-or-keep: the live-network websearch test

**Decision: RETIRED from default runs, KEPT as an opt-in live test
(explicit and honest).** `tests/test_websearch.py::
test_live_web_search_returns_real_results` is skipped unless
`SANGAM_LIVE_NETWORK=1` (and skips again if the network is
unavailable). Rationale: it hits the real internet, so it flakes on
SSL/network conditions no code change controls — it previously
failed as a "pre-existing websearch live-network flake" while the
rest of the suite was green. It is NOT deleted: with the flag set it
still exercises the real search path. The 1613-passed total above
does not include it (it counts among the 101 skipped without the
flag). No other test is gated this way.

## How the browser gate caught real bugs (this program)

- Shell spec first run: 4 failed / 1 skipped → 3 real bugs
  (stale `.rail-nav{display:none}`, shell blocked behind the ~13s
  `/models` Ollama probe, `showTool()` rendering without pushState)
  + 1 test correction (palette create lands on
  `/studio?section=create`). After fixes: 5/5.
- Runs spec: screenshot baseline regenerated only after inspecting
  actual vs expected (old strip vs new rail — the diff WAS the
  intended IA change); mobile test needed the hamburger-first flow
  + drawer-close-on-navigate app fix; both tests then green.
- Smoke spec: two stale pre-A1 assertions (rail count 0, deleted
  'Research & Web' label) corrected to the new IA.
- Devices/fit specs: old settings-category ids (`devices`,
  `voice_output`) replaced with current ones per the legacy map
  (`security`, `voice`).
- Diagrams spec: Flowchart button selected by exact
  `data-diag-type` (catalogue growth made name matching ambiguous).
- Runs/fit/diagrams/skills/shell specs: shared `ctx.loggedIn`
  reset at `register()` start, so a later test's expected pre-login
  401 (usage meter) is not mis-flagged as post-login.

## What was NOT verified live (honest limits)

- Physical phone QR scan; real-LAN banner render; real two-device
  mDNS; Docker isolation live (no Docker on this machine);
  real-driver browser-agent end-to-end; live pipeline/council runs
  with a real model (tests use fake completers); real Fooocus
  diffusion; lesson-player TTS not wired; Knowledge Export still
  memories-JSON only; legacy pipeline finish still accepts
  pasted-text reviews (compat); `agents_routes` automatic→[]
  bypass closed downstream only; provider tool path has no guard
  hooks; `cost_known=False` until a caller passes
  `price_per_1k_usd`.
- New partials from this program: Harper word list flags some
  correct rare words (never autocorrects); per-message overrides
  steer the normal stream path, not the separate agent path;
  `/council` is a prompt starter, not a Council launch; QA replay
  for cookie/CSRF flows not verified; diagram PNG export 422s;
  blind-compare label map in-memory; registry source is a labelled
  stub; no real image/audio bytes generated in this environment;
  resumed workflows re-run from input; scheduler cron keeps
  simplified next-hour semantics; no live LLM/passive-recon runs;
  `.env`-only settings read-only in Advanced; `/code/:repo` and
  `/research/:notebook` show no fake detail view; first-run with a
  real key/Ollama unverified (mock provider in the gate).

## Specs NOT run in this gate

`ux-refine.spec.ts`, `e2e_tests.spec.ts`, `golden_paths.spec.ts`
were not in this program's gate list (they predate the IA swap and
were not re-homed in the coordinator's 3e3e9ab pass) — they are
neither green nor red here, simply not run. If they are wanted,
they need the same re-homing pass first (rail nav, category ids,
guard resets) before anyone quotes their results.
