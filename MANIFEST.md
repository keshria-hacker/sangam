# A2 — Composer & Response Intelligence — MANIFEST

Branch: `spec/a2-composer-intelligence` (based on `integration/full-program` @ 740306f).
Worktree: `~/workspace/projects/sangam-worktrees/a2`. NOT pushed, per task.
Coordinator-owned files untouched: `docs/ARCHITECTURE.md`, `README.md`,
`FIX_LOG.md`, the main checkout at `~/workspace/projects/sangam`.

## New routes (all on the shared router, auth-required like /api/*)

| Route | Purpose |
|---|---|
| POST `/intelligence/route` | Dry-run the Auto pipeline. Body: `{message, history?, file_ids?, composer_mode="auto", tool_overrides?, adaptive_depth?}`. Returns the full `RouteDecision` (intent, resolved mode, Auto tools, complexity, rule trace, classifier flag, needs_search/citations, approval, clarification question, blocked flag, post-actions). No provider call, no DB write, no network. The live chat path runs the same function, so dry-run and live cannot drift. |
| POST `/intelligence/harper` | Offline Harper-class lint suggestions `{suggestions}`. Suggestions only — never rewrites, never autocorrects. |
| GET `/intelligence/modes` | Composer modes + tool vocabulary the pipeline understands. |

Changed route (additive only): POST `/quality/lint` now also returns
`harper: [...]` alongside the unchanged `issues` shape.

## Changed backend behaviour (no new DB tables, no model changes)

- `backend/response_intelligence/pipeline.py` (NEW): the unified Auto
  pipeline — intake → intent → context assembly → complexity →
  capability selection → mode selection → tool/search/file/code/
  artifact routing → execution hints → validation → post-response
  actions. All 16 spec §4.2 intents. RULE-FIRST: deterministic rules
  decide; the "small classifier" runs only on a rule tie and is a
  deterministic weighted keyword scorer — never a model call, never
  network. Golden-set measured rule coverage: 49/50 by rules
  (1 tie → scorer), i.e. 98% rule coverage, above the ≥80% bar.
- `backend/api_routes/chat_stream_routes.py` (owned by A2): runs the
  pipeline before the web-search block. Auto search turns on for
  date/news/price/version signals (user-approved default), unless the
  user globally disabled web search (`webSearchEnabled=false`) or
  overrode web search off for this message. A route system note is
  injected after existing system messages (mode/tools; exactly-one-
  clarification instruction when the older gate did not fire;
  honest not-available note for video). Any routing failure degrades
  to the old behaviour and never breaks the chat.
- `backend/response_quality/harper.py` (NEW): Harper-class lint that
  blanks fenced code, inline code, and code-looking lines line-for-
  line before linting (line numbers still match the original), so
  identifiers, function names, and error strings never produce
  issues. Suggestions only.
- `backend/response_quality/slop.py`: Detect and Edit now skip fenced
  code blocks and inline code spans, and accept an optional
  `protected=[...]` phrase list (e.g. a product name that is also a
  slop word) that is copied through byte-for-byte. Prose-only inputs
  behave exactly as before (all pre-existing slop tests pass).
- `backend/response_quality/common_words.txt`: appended a technical
  supplement (function, variable, server, database, …) so Harper's
  unknown-word candidate does not flag ordinary technical prose.
  Unknown-word remains candidate-only by design — it is not a full
  dictionary, and that limit is stated, not hidden.
- `backend/schemas.py`: `ChatStreamRequest` gains three optional,
  backwards-compatible fields: `composer_mode` (default `"auto"`),
  `tool_overrides` (default `{}`), `adaptive_depth` (default `true`).
  Unknown composer modes are coerced to `"auto"` in the stream path.
- ADHD-friendly mode: already wired (prompt style block when
  `adhdFriendly` is on + post-hoc formatting at persistence). A2 did
  not rewire it; it verified the wiring and fixed the stale Settings
  description that still said "not yet wired into chat" (reworded to
  avoid the exact phrases an existing guard test pins — see below).
- No-AI-slop Detect (unchanged text + named pattern + quote) and Edit
  (minimum edit + "What changed") already existed in `slop.py` and
  `/quality/preview`; A2 added the code/protected-name protection
  above and kept both modes' contracts.

## New/changed frontend modules (vanilla JS, no new destination)

| Module | Change |
|---|---|
| `frontend/index.html` | REMOVED the composer Runs button (`#runsBtn`). ADDED `#continueBtn` (hidden by default) next to Send/Stop. |
| `frontend/js/features/composer/popovers.js` | Mode selector is now the spec set: Auto (default), Answer only, Research, Code, Create, Agent. Legacy mode ids still map through `setMode()` (chat→auto, think→auto, image→create, …). Tools popover is now the spec set (web search, deep crawl, code execution, browser, image, memory recall, artifact generation). In Auto it dry-runs `/intelligence/route` for the current composer text, shows what Auto chose, and checkbox changes are per-message overrides consumed by the next send. In Manual tool mode toggles are persistent. |
| `frontend/js/features/chat/chat.js` | Sends `composer_mode`, `tool_overrides`, `adaptive_depth`, and a web_search value that respects an explicit override, else Research mode, else the global toggle. Stop already replaced Send while streaming (pre-existing, kept). `continueGeneration()` added: after an interrupted generation with a partial response it sends a "Continue" follow-up turn (pipeline continues it without re-stating context); with nothing generated it retries the last user message. Continue is hidden on new send / regenerate / new chat / success. |
| `frontend/js/features/chat/message_view.js` | ADDED "View run" to the assistant response action menu. Until the IA swap re-homes it, it opens the live run-history surface (Work → Activity, the Runs centre) with a toast saying exactly that — it does not pretend an Agents destination exists yet. |
| `frontend/js/features/composer/slash.js` | ADDED `/grill`, `/spec`, `/council`, `/review`, `/plan`, `/diagram`, `/podcast` as prefill starters (editable text in the composer; Auto routes them; nothing is sent by the command itself) and `/video`, which shows a plain "Video production is not available this round" note and does nothing else — never fake output. `/runs` kept (opens run history). Auto never requires any slash command. |
| `frontend/js/shared/markdown.js` | ADDED `stabilizePartialMarkdown()` and applied it inside `renderMarkdownStream()` only (final renders unchanged): unclosed code fences are closed and table rows missing a closing pipe are completed, so partial streams no longer swallow content into a code block or collapse a table mid-stream (the observed flicker/reflow causes). This is a renderer guard, not a claim of zero reflow for every construct. |
| `frontend/js/shared/settings_schema.js` | New keys (below) + the `adhdFriendly` description corrected from "not yet wired into chat" to the wired state. |

## New settings keys (for the coordinator's Settings center)

| Key | Label | Description | Default | Section |
|---|---|---|---|---|
| `composerMode` | Composer mode | Mode for the composer. Auto (default) lets the response-intelligence pipeline decide whether to answer, search, code, create, or run an agent — no user action needed. | `auto` | Chat & Composer (`chat`) |
| `toolMode` | Tool mode | Auto: the Tools popover shows what Auto chose and changes apply to this message only. Manual: Tools toggles stay on for every message. | `auto` | Chat & Composer (`chat`) |
| `adaptiveDepth` | Adaptive depth follow-ups | Offer "explain more" / "short version" follow-ups based on novice vs expert signals in your message. | `true` | Chat & Composer (`chat`) |

All three are consumed: `composerMode` by popovers init + chat send,
`toolMode` by the Tools popover, `adaptiveDepth` by the stream body →
pipeline post-actions. No other new keys were added (deliberately —
no dead settings).

## DB / model changes

None. No new tables, no column changes, no migrations.

## Exactly what changed in `api.py`

One import block only (appended after the existing `routing_routes`
import). Importing the module registers its routes on the shared
router (`api_routes/common.py`), the same pattern other route modules
use — no router mounting change, no facade re-export change:

```python
# A2 (spec §4): Auto response-intelligence dry-run + Harper lint routes.
# Importing registers them on the shared router (api_routes/common.py).
from .api_routes import intelligence_routes  # noqa: F401
```

## Tests

- NEW `tests/test_a2_composer_intelligence.py` (17 tests) +
  NEW `tests/data/auto_routing_golden.json` (50 prompts, all 16
  intents + routing matrix + 4 follow-ups + blocked video).
- Golden score measured by actual run: **50/50 intent+mode agreement
  (100%, bar ≥90%)**; must-include tools 50/50; classifier used on
  1/50 prompts (98% rule coverage, bar ≥80%). Two golden items
  initially missed (non-contiguous phrases "doesn't this code work"
  and "read this answer aloud") and were fixed in the rules, not by
  weakening the expectations.
- Frontend check: `node --experimental-vm-modules
  scripts/check_frontend_modules.mjs` → **63/63 modules parse + link**.

## Known coordinator follow-ups (do NOT silently merge past these)

1. **Docs drift (expected, coordinator-owned):**
   `tests/test_docs_routes_drift.py` fails ONLY on the 3 new routes
   (`GET /api/intelligence/modes`, `POST /api/intelligence/harper`,
   `POST /intelligence/route`) because `ARCHITECTURE.md`'s route
   table — which A2 was told not to touch — does not list them yet.
   Add the 3 rows at merge; nothing else drifts.
2. **Obsolete e2e test (spec-mandated removal):**
   `tests/e2e/runs.spec.ts` contains "Runs centre: mobile 390px via
   composer Runs button", which clicks `#runsBtn`. That button was
   removed by this spec, so that test cannot pass as written. It
   needs updating or deleting at merge (A2 left e2e specs untouched).
   The `/runs` slash command itself still works.
3. **"View run" re-homing:** when A1 lands the 8-destination IA, the
   View-run handler in `message_view.js` (`showToolSection('work',
   'activity')`) should be re-pointed at Agents → Run History.
4. **Existing guard test honoured:** `test_adhd_schema_no_longer_claims_answer_first_or_numbered_steps`
   pins the `adhdFriendly` description wording; A2's description fix
   was worded to stay inside that guard rather than editing the test.

## What A2 could NOT verify (coordinator: please run at merge)

- No Playwright/browser runs (shared ports :8001/:5500; per task,
  the coordinator runs browser checks at merge). Suggested specs:
  `tests/e2e/ux-refine.spec.ts` (composer + slash), `tests/e2e/runs.spec.ts`
  (see obsolete-test note above), `tests/e2e/smoke.spec.ts`.
- No live provider stream with the new route note (no provider key
  exercised here); the stream wiring is covered by the existing
  `test_deep_evidence.py` stream test (passed) plus the new
  `/intelligence/*` endpoint tests, not by a live model call.
- Physical UX of the Tools popover Auto-chosen display and the
  Continue button needs a real browser pass (see specs above).

## Honest limits (not hidden)

- The "small classifier" is a deterministic keyword scorer, not an
  ML model — labelled as such in code, API output, and this manifest.
- Harper's unknown-word rule is candidate-only (bundled word list,
  ~1,370 words after the technical supplement); it will still flag
  some correct rare words. It never autocorrects, so a false
  candidate costs a glance, not a corruption.
- Slop protection for prose product names requires the caller to pass
  the name in `protected`; automatic name detection is not claimed.
  Code spans and fences are protected automatically.
- Streaming stability: the fence/table guard fixes the two observed
  reflow causes; exotic partial constructs (e.g. half-written links)
  can still shift layout until the chunk completes — not claimed
  otherwise.
- Agent-mode sends use the separate agent path (`agent_mode.js`);
  per-message tool overrides are consumed but do not steer that path
  (they steer the normal stream path). Code mode keeps the legacy
  code-agent path, as before.
- `/council` is a prompt starter, not a direct Council launch; the
  council runtime itself is A4/A6 territory.
