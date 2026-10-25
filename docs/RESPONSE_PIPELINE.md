# Sangam — Response Pipeline (perfect-flow program)

## The pipeline

`backend/response_intelligence/` wires into the chat stream
(`chat_stream_routes.py`). Stages, in order:

intake → intent → context → complexity → capability → mode →
routing → execution → events → validation → post-actions.

Auto is the default mode. The mode selector offers: Auto (default),
Answer only, Research, Code, Create, Agent. Legacy mode ids map onto
these; per-message tool overrides (web search, deep crawl, code
execution, browser, image, memory recall, artifact generation) steer
the normal stream path, not the separate agent path.

## Intent: rule-first, honestly labelled

Intent classes are resolved by rules first. The deterministic keyword
scorer is the only "classifier" and is labelled as such in code — it
is never a model call, and the LLM classifier runs only when the rules
are genuinely ambiguous. Golden set (50 prompts, test-covered):
**50/50 intent+mode agreement** (bar ≥90%); the scorer was used on
1/50 prompts (98% rule coverage). Follow-ups ("why?", "continue",
"fix it") resolve without re-stating context.

## Routing matrix (§4.3 of the spec)

- Auto web-searches when the query carries date/news/price/version
  signals, otherwise answers directly (user-approved default 1).
- Research mode: web + deep crawl + notebooks, with citations.
- Code mode: code graph + spec pipeline + TDD evidence.
- Create mode: Studio artifact generation.
- Agent mode: the agent runtime (see `AGENT_RUNTIME.md`).

## Capability pre-flight

The per-model capability registry warns before execution when a
model cannot do what was asked ("this model can't do X"), instead of
failing mid-stream. Fallback chains and cost-ranked routing apply
after pre-flight. No provider capability is claimed that its adapter
does not support; all 11 previously supported providers are retained.

## Quality passes (never corrupting names or code)

- **ADHD-friendly style**: verified against current Settings text
  (a stale description was corrected in this program).
- **No-AI-slop Detect/Edit**: Detect audits without rewriting; Edit
  rewrites flagged clichés only. Slop now skips fenced and inline code
  (a real bug fixed in this program — slop previously rewrote words
  inside code fences).
- **Harper lint**: suggestions-only, never autocorrects. Its ~1,370
  word list still flags some correct rare words; that is a known
  limit, not a silent rewrite.
- **Stable streaming Markdown**: unclosed fences and partial table
  rows render stably mid-stream instead of flickering.

## Events and validation

Runs mirror to the Runs centre (`kind` preserved per source: chat,
agent-task, workflow, media job), so every response has a "View run"
action that opens Agents → Run History. Validation failures surface
as evidence in the Inspector, not as silent retries.

## What is NOT in this pipeline

- Video production and voice cloning: user-confirmed skips.
- A model-based intent classifier as the default path: rules first,
  by design (deterministic, testable, no model cost on routing).
- Per-message overrides on the separate agent path: overrides steer
  the normal stream path only (documented limit).
- `/council` as a launch: in the composer it is a prompt starter,
  not a Council launch (documented limit).
