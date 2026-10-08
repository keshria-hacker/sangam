# Sangam Foundation (Phase 0) — what was built

Date: 2026-10-08. Branch: `foundation/phase-0`.
Goal: make Sangam flexible and reliable enough to absorb the 22-repo
integration program without turning into spaghetti.

## F1 — Unified extension registry
`mainfiles/backend/extensions/`
- `manifest.py`: `ExtensionKind` (TOOL, SKILL, PROVIDER, CAPABILITY, MCP_SERVER),
  `ExtensionManifest` with semver-validated versions.
- `registry.py`: `ExtensionRegistry` — register / enable / disable / list.
  Enable/disable deltas persist to `mainfiles/extensions_state.json` (gitignored).
  Adapters project every existing tool (`tool:<name>`) and skill (`skill:<id>`)
  into the registry; the original registries keep working untouched.
- `initialize_extensions()` — called once from app lifespan (best-effort).
- API: `GET /api/extensions`, `POST /api/extensions/{name}/enable|disable`
  (`api_routes/extensions_routes.py`).

## F2 — SKILL.md standard loader
`mainfiles/backend/skills/registry.py` now also accepts Claude-style
frontmatter (`name`/`description` without Sangam's `id`/`category` keys),
slugifies missing ids, and exposes `reload()` / `reload_registry()` so new
skill packs can be dropped into `mainfiles/config/skills/` without code changes.
Every parsed skill is projected into the extension registry as `skill:<id>`.

## F3 — MCP client
`mainfiles/backend/mcp/` — minimal JSON-RPC 2.0 client with stdio and SSE
transports (`client.py`: connect, list_tools, call_tool, close), plus
`bridge.py`: `register_mcp_server`, `setup_mcp_servers(configs)`,
`shutdown_mcp_servers`. MCP tools are registered into the tool executor as
`mcp_<server>_<tool>`. Servers are configured via `MCP_SERVERS_JSON` env
(JSON list of `{name, command|url, args, env}`), connected at startup
(best-effort, never crashes boot), closed at shutdown.

## F4 — Media message types (image/audio)
End-to-end pipeline for multimodal messages, the prerequisite for the
VoiceStudio (voice) and Fooocus (image-gen) integrations:
- `schemas.py`: `MessageContentPart` (text|image|audio), `MediaAttachment`,
  `ChatMessageIn.parts`, `ChatStreamRequest.media_ids`, `MessageOut.media`
  + `content_type` (hydrated from the DB column via validator).
- `models.py` + migration `d4e5f6a7b8c9`: `messages.media_json` (nullable TEXT).
- `api_routes/media_routes.py`: `POST /api/media/upload` (magic-byte
  validated images/audio), `GET /api/media/{id}`, helpers
  `resolve_media_json` / `media_content_parts` / `load_media_attachment`.
- `chat_stream_routes.py`: `media_ids` validated → persisted on the user
  message; vision-capable models get OpenAI-style `content_parts`
  (translated to wire `content` in `openai_compatible.py`), others get a
  textual note.
- `response_events.py`: `MEDIA_START` / `MEDIA_DELTA` / `MEDIA_END` with
  lifecycle guards in `ResponseEventBuilder`.
- Frontend: `response_controller.js` handles the three media events
  (emits `mediaStart/mediaDelta/mediaEnd`); `message_view.js`
  `showMediaInNode` + `mediaHtml` render `<img>` / `<audio controls>`;
  `chat.js` wires the stream and persists media on the final message.

## F5 — Provider hardening + OmniRoute
`mainfiles/backend/providers/resilience.py`:
- `retry_async` — exponential backoff + jitter, retries only errors
  classified `retryable` by `normalize_error` (429/5xx/timeout/network);
  never retries `CancelledError`.
- `CircuitBreaker` per provider (closed/open/half-open) + `breakers` registry
  with `.states()` for health reporting.
- `providers/__init__.py`: `stream_completion` and `stream_response_events`
  stream through `_stream_with_resilience` (fresh generator per retry);
  public signatures unchanged.
- OmniRoute now reads `OMNIROUTE_BASE_URL` from settings (was hardcoded
  `http://localhost:20128/v1`) — the meta-provider for 359 providers / 1200+
  models via one endpoint.

## F6 — API versioning, feature flags, health
- `config.py`: `FEATURE_VOICE`, `FEATURE_IMAGE_GEN`, `FEATURE_MCP`,
  `FEATURE_MULTI_AGENT`, `FEATURE_ANALYTICS`, `FEATURE_SPEC_KIT`
  (env-overridable), `MCP_SERVERS_JSON`, `API_VERSION="v1"`,
  `feature_flags()` / `mcp_server_configs()` helpers.
- `GET /api/features` → `{version, features}` (`features_routes.py`).
- All routers mounted under `/api/v1/*` in addition to `/api/*`
  (`main.py`) — future breaking changes ship as `/api/v2`.
- `/health` extended: `api_version`, `features`, `extensions`
  (registered/enabled counts), `mcp_servers`, `circuit_breakers`.

## F7 — Tests
- `tests/test_extensions.py` (F1/F2), `tests/test_mcp.py` (F3),
  `tests/test_resilience.py` (F5), `tests/test_foundation_media.py`
  (F4/F6, 15 tests). Existing provider/LLM tests re-run for regressions.

## What's deliberately NOT in Phase 0
Actual voice TTS/STT, image generation, skill-pack imports, multi-agent
orchestration, analytics — those are the themed integrations and now have
clean seams to plug into: extension manifests, MCP servers, media events,
feature flags, and the hardened provider layer.

## Hardening notes (found while integrating)
- `initialize_extensions()` re-syncs on every call instead of one-shot:
  restores builtin tools after `registry.clear()`, prunes stale `tool:` /
  `skill:` manifests. (`ExtensionRegistry.unregister` added.)
- `/health` new fields are mock-safe (degrade to `{}`/`"v1"` when settings
  is a test double).
- `tests/test_extensions.py::TestExtensionsApi` follows the repo's tmp-DB
  pattern (`settings.DATABASE_URL` rebind + `reset_engine_for_testing` +
  per-test extension state path) — module-level env override is not enough
  because `backend.config.settings` is a singleton.
- Full suite: **1022 passed, 100 skipped, 0 failed** (unit; e2e excluded
  per repo layout). Frontend: `node --check` clean, all 16 modules parse+link.
