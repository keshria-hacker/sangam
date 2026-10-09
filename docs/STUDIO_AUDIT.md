# STUDIO AUDIT — Phase 0

Date: 2026-10-09. Scope: full read-only audit of frontend + backend.
Method: two parallel code auditors + doc review + live verification.
No code was changed in this phase.

**Verdict: Section 2 is ~90% confirmed.** One claim was refuted (see §6),
two new P1 bugs were found that the prompt missed (§5).

---

## 1. Screen / control inventory

Format: control — where it lives — works? — where it goes in the studio shell.

### Sidebar (`index.html:88-155`, `js/features/sidebar/sidebar.js`)

| Control | Works? | Goes to |
|---|---|---|
| Brand + collapse | ✅ | Rail top |
| New chat | ✅ | Rail → Chat |
| Search chats | ✅ | Rail → Chat (search) |
| Skills | ✅ opens tab | Rail → Library |
| Agent teams | ✅ opens tab, starts hidden | Rail → Agents |
| Learn | ✅ opens tab, starts hidden | Rail → Learn |
| Analytics | ✅ opens tab, starts hidden | Rail → Insights |
| Image studio | ✅ opens tab, starts hidden | Rail → Create |
| Code agent | ✅ opens tab | Rail → Code |
| Design studio | ✅ opens tab | Rail → Create |
| Chat history list | ✅ | Rail → Chat (folders/pins/search) |
| Settings | ✅ opens modal | Rail bottom → Settings page |
| GitHub Star link | ✅ external | Rail bottom (keep) |
| Profile popup | ✅ | Top bar account menu |

### Tab strip (`index.html:186-196`, `js/features/tabs/tabs.js`)

| Control | Works? | Goes to |
|---|---|---|
| Pinned Chat tab (never closes) | ✅ | Keep |
| Tool tabs open/close/switch | ✅ | Keep, but mount-once (fix §2.5) |
| `+` tool picker | ⚠️ lists all 7 tools, ignores feature flags | "Open in split view", flag-aware |

### Top bar (`index.html:201-240`, `js/features/models/models.js`)

| Control | Works? | Goes to |
|---|---|---|
| Model selector (search, provider filter, real data) | ✅ | Top bar: model/route |
| `#reasoningEffortIndicator` | ❌ dead element, zero JS refs | Remove or wire to Think mode |
| Connection pulse | ✅ provider health | Top bar health |
| Palette button (terminal icon) | ✅ works, icon unclear | Top bar palette (new icon) |
| Theme toggle | ✅ | Appearance settings |

### Composer (`index.html:292-380`, `js/features/chat/chat.js`)

| Control | Works? | Goes to |
|---|---|---|
| Attach | ✅ | Composer: (+) |
| Mic | ⚠️ records, no timer/meter/cancel/push-to-talk; failed STT loses blob | Composer mic + Voice settings |
| Image button | ✅ opens Image Studio tab | Composer (+) / Create |
| Textarea + send/stop | ✅ | Composer (add queue-while-streaming) |
| Temp pill + popover | ✅ sent to backend | Tune popover |
| Max tokens dropdown | ⚠️ works, defaults 1,024, max 8,192 | Tune; default → Auto |
| Reasoning effort dropdown (🧠) | ✅ real, sent as `reasoning_effort` | Mode → Think |
| Web search toggle | ✅ | Tools popover |
| "Reason" toggle (🧠) | ❌ dead — backend 500s/degrades | Rebuild as Mode → Agent (§4.1) |
| Agentic Reasoning panel + tool checkboxes | ⚠️ panel shows; checkboxes ARE read (`chat.js:250-258`) but feed a dead endpoint | Remove; replaced by Tools popover |
| Token counter | ✅ | Context meter (explains itself) |

### Settings modal (`index.html:398-560`, `js/features/settings/settings.js`)

3 tabs, all wired: General (Connection, Appearance, Response style),
Features (5 toggles), Providers (OmniRoute, Providers, API keys, **Memory**,
**Voice**). Memory/Voice misplaced → relocate per §4.4. Becomes full
Settings page with 14 categories (§6).

### Tool tabs (renderers in `app.js:461+`)

Skills, Teams, Learn, Analytics, Image Studio, Code Agent, Design Studio —
all renderers work. All lose state on tab switch (§2.5).

---

## 2. Section 2 findings — verification

### 2.1 Composer — CONFIRMED (with one correction)
- Two reasoning controls, same `fa-brain` icon: **confirmed**
  (`#reasoningSelect` `index.html:341`, `#agenticReasoningToggle`
  `index.html:373`; effort also duplicated in dead `#reasoningEffortIndicator`).
- `/api/agentic-reasoning` **dead**: `chat_stream_routes.py:489` imports
  `agentic_reasoning` from `<repo>/.agents` — **that directory does not
  exist**. ImportError is swallowed; endpoint returns HTTP 200 with
  `{"reasoning_used": false}` — always degraded, never real.
- **Correction:** the "Tools" checkboxes are NOT fake — they ARE read at
  `chat.js:250-258` (label-text matching, fragile but functional). The dead
  part is the backend they feed.
- Max tokens default 1,024 (**confirmed**, `index.html:329`), max 8,192.

### 2.2 Voice — CONFIRMED
- `speakText()` awaits `fetch('/api/voice/tts')` with **no AbortController**
  (`voice.js:130-155`); `stopSpeaking()` only pauses `currentAudio`
  (`voice.js:167-172`). Stop during fetch → audio plays anyway.
- **Zero external callers** of `stopSpeaking` — no stop on Escape, chat
  switch, new message, or mic start.
- Speak button is not a toggle (`message_view.js:454-460`); no speaking indicator.
- Dictation: no timer, meter, cancel, push-to-talk, streaming transcript;
  failed STT discards the blob.
- Voice settings: voice dropdown + auto-speak only. No speed/engine/test/language.

### 2.3 Navigation — CONFIRMED
- Tools open from 3 places (sidebar, `+` menu, palette) with inconsistent
  flag filtering: `+` menu lists all 7 (`tabs.js:140-160`, no flag check).
- 4 of 7 tools start hidden (`teamsBtn`, `learnBtn`, `analyticsBtn`,
  `imagesBtn` have `class="hidden"`).
- Collapsed history: every item gets `fa-regular fa-message` (`sidebar.js:235`).
- **Bonus:** Image toggle OFF leaves sidebar `imagesBtn` visible
  (`refreshFeatureButtons` toggles composer `imageBtn` only).

### 2.4 Settings placement — CONFIRMED
Memory + Voice under Providers; response style under General; quality
passes env-only (`QUALITY_NO_SLOP`, `QUALITY_ADHD_FRIENDLY`, `config.py:113-114`,
no API/UI); MCP env-only (`MCP_SERVERS_JSON`, no management endpoints);
extensions API live (`extensions_routes.py:60-77`) with **zero frontend references**.

### 2.5 Tab state loss — CONFIRMED
`tabs.js:121-122`: `body.innerHTML = ''` + re-render on every switch.
Design Studio also mints a new `projectId` per render (`design-studio.js:46`),
orphaning `designs/proj-*` dirs. `stepNode()` duplicated
(`code-agent.js:11`, `design-studio.js:14`).

### 2.6 Visibility — CONFIRMED
- `/api/teams/run` synchronous (`teams_routes.py:40-62`, `runner.py:114-175`
  `asyncio.gather`, no SSE).
- Code agent streams but: no run history, no diff review, no approvals, no budget.
- No running-jobs view anywhere.
- `code_graph.py` Python-AST only (`import ast`, globs `*.py`), exposed only as
  tool + small "Explore code map" dropdown. No graph view.
- MCP: client exists (`mcp/client.py`, `mcp/bridge.py`), `/health` lists server
  names read-only. No add/test/enable/tools UI.

### 2.7 Smaller issues — CONFIRMED
Welcome suggestions static; file picker excludes images/audio
(`index.html:307`); hint text triplicated (composer `index.html:375`,
welcome `index.html:278`, shortcuts modal `index.html:830+`); Design Studio
has no design system / artifact type / export / versions.

---

## 3. Dead code (remove in Phase 1)

**Frontend**
| Item | Location |
|---|---|
| `getToolDefs()` — exported, never imported | `tabs.js:28` |
| `#reasoningEffortIndicator` — zero JS refs | `index.html:218` |
| `#backendDownState` — never populated, only hidden | `index.html:322` |
| Palette "Open Skills browser" → calls `a.openSkillsModal?.()` which doesn't exist; `app.js:355` exposes only `openSkillsTab` | `palette.js:36` |
| `openSkillsModal()` — only caller is the broken palette action | `skills.js:233` |

**Backend**
| Item | Location |
|---|---|
| `request_builder.py` — fully dead, nothing imports it (only a commented-out test import) | `backend/request_builder.py` |
| `prompt_injection.py` — production-dead; imported only by tests, never by backend modules. The advertised "prompt-injection guard" does not run | `backend/prompt_injection.py` |

---

## 4. License check — CLEAN
Open WebUI / OpenPanel / Fooocus / VoiceStudio: ideas-only, no copied code.
`FooocusEngine` drives a local Fooocus **as a separate service** via its public
API (permitted). VoiceStudio referenced only as an example server URL.
No Open WebUI/OpenPanel code found. **Gap:** no `NOTICE` file exists for
MIT/Apache attributions — create in Phase 1.

---

## 5. NEW — bugs the prompt missed

1. **P1 — Code Agent bypasses the provider stack.** `code_agent.py:111` calls
   `litellm.acompletion(model=model, ...)` directly with no API key and no
   `db`. Sangam keys live encrypted in the DB; litellm only reads env vars.
   The Code Agent fails auth for any provider whose key is DB-only (the normal
   case). `teams/runner.py:69-86` does it right via `llm.stream_completion`.
   **Fix in Phase 1:** route the agent loop through `llm`/`providers`.
2. **P2 — `sys.path` pollution.** `chat_stream_routes.py:485-487` appends a
   nonexistent `.agents/` dir to `sys.path` on every request (latent
   path-injection smell if the dir ever appears). Remove with the dead endpoint.
3. **P2 — No tests for newest backend surface.** Nothing covers `code_agent.py`,
   `code_graph.py`, `instincts.py`, `omniroute_routes.py` — violates the
   "tests for everything new" rule. Add in Phase 1.
4. **Note — routers double-mounted** (`main.py:279-291`): every route under
   both `/api/*` and `/api/v1/*`. Intentional, but auth/rate-limit accounting
   sees each path twice — keep in mind for Phase 5.

---

## 6. Corrections to the master prompt

1. §2.1 "Tools checkboxes not read by chat.js" — **refuted**; they are read
   (`chat.js:250-258`). Fragile label-matching, but functional. Dead part is
   the backend.
2. Test count: prompt says "~1,114 pass" — actual run in this phase:
   **1121 passed, 100 skipped, 1 deselected, 0 failed**.
3. `/api/agentic-reasoning` doesn't 500 visibly — it returns HTTP 200 with
   `reasoning_used: false`; the frontend toast comes from `chat.js:279-283`
   reading that degraded payload.

---

## 7. What's solid (do not break)

Tab system, model selector, palette (minus one dead action), settings toggles
with instant apply, feature-flag plumbing, SSE chat streaming, all 7 tool-tab
renderers, reasoning-effort param, tool sandboxing (path-escape checks verified),
encrypted key storage, migration chain. Breakage is concentrated in: voice stop
UX, dead agentic-reasoning, tab state persistence, provider-stack bypass in the
Code Agent — all fixable without layout changes (Phase 1 scope).

---

## 8. Phase 1 work list (derived from this audit)

1. Delete dead code (§3); create `NOTICE`.
2. Remove `/api/agentic-reasoning` + fake panel + `sys.path` hack; build real
   Agent mode loop on `tools/` executor + `code_agent` engine.
3. Fix Code Agent provider-stack bypass (route through `llm`/`providers`).
4. Think mode: map effort → provider params, collapsible Thinking block.
5. Voice controller state machine + stop everywhere + AbortController.
6. Tab state persistence (mount-once) + shared `RunLog` (dedupe `stepNode`).
7. Max tokens default → Auto; image toggle hides sidebar item too.
8. Tests for `code_agent.py`, `code_graph.py`, `instincts.py`, `omniroute_routes.py`.
9. Settings relocation hooks (no logic loss).

*Gate: tests green; manual checklist for voice stop + Agent mode; no dead button.*
