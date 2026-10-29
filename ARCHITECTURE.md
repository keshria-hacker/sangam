# Sangam — Architecture & Implementation Guide

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Directory Structure](#2-directory-structure)
3. [Backend Architecture](#3-backend-architecture)
4. [Frontend Architecture](#4-frontend-architecture)
5. [Data Flow](#5-data-flow)
6. [Authentication System](#6-authentication-system)
7. [Provider & Model System](#7-provider--model-system)
8. [Chat Streaming](#8-chat-streaming)
9. [Skills System](#9-skills-system)
10. [Web Search](#10-web-search)
11. [Document Processing](#11-document-processing)
12. [Testing](#12-testing)
13. [Configuration Reference](#13-configuration-reference)
14. [Data Flow Diagram](#data-flow-diagram-complete)
15. [Recent Additions (Phase 6)](#15-recent-additions-phase-6-2026-10-09)

---

## 1. Project Overview

**Sangam** is a privacy-first, universal AI chat platform that unifies multiple Large Language Models (LLMs) into a single interface. It connects to cloud provider APIs (OpenAI, Anthropic, Gemini, etc.) and local models (Ollama) simultaneously, allowing users to switch between providers mid-conversation.

**Core Philosophy:** One interface, any model. No lock-in, no simulated responses — every chat is a real API call to a real provider.

### Key Features
- Multi-provider chat with live model discovery
- Real-time streaming responses (Server-Sent Events, canonical `response_event` protocol)
- Document upload + text extraction (PDF, DOCX, XLSX, code, etc.)
- Web search augmentation (DuckDuckGo out of the box, Tavily/Brave optional)
- In-app API key management (no server restarts)
- Conversation history with bucketed date grouping + rolling cross-session summaries
- Response Intelligence: intent/style classification, clarification gate, uncertainty hedging
- Paper / Ink theme system (light / dark / system) — monochrome design tokens
- Extensible Skills system + skill packs
- Local authentication (scrypt password hashing, login lockout, forgot/reset flow)
- Ollama auto-detection and auto-start (Sangam launches `ollama serve` in the background if installed but not running)
- **Studio shell**: chat-focused sidebar, browser-style tabs, Inspector panel, Activity Tray
- **Knowledge graph**: unified graph of memories, docs, code, chats with provenance
- **Agent Hub**: custom agents with tools, approval policies, cost budgets, run history
- **Multi-agent Teams**: fan-out/fan-in with SSE streaming per specialist
- **Create Hub**: typed artifacts (docs, diagrams, code, HTML) with version history
- **Code Agent**: agentic coding (write_file/edit_file/run_bash) with approvals
- **Design Studio**: UI prototype generation with sandboxed preview
- **Learning Mode**: teacher lessons + Socratic tutor
- **Automations**: scheduled agent tasks and chat messages
- **Routes & Combos**: keyword model routing, model chains, quotas
- **Model Compare & Arena**: parallel comparison, voting, leaderboard
- **Voice**: local-first TTS/STT with pluggable engines
- **Image Generation**: style presets with pluggable engines

---

## 2. Directory Structure

```
<repo root>/
├── Dockerfile / Dockerfile.all         # Docker builds
├── docker-compose.yml / docker-compose.all.yml
├── mainfiles/                  # Application code
│   ├── backend/                # FastAPI Python backend (imported as `backend.*`)
│   │   ├── main.py             # App entrypoint, lifespan, CORS, security headers, router mounts
│   │   ├── config.py           # Typed settings from .env (pydantic-settings)
│   │   ├── database.py         # Async SQLAlchemy engine + session factory (SQLite)
│   │   ├── models.py           # SQLAlchemy ORM tables
│   │   ├── schemas.py          # Pydantic request/response models
│   │   ├── api.py              # API facade — mounts handlers from api_routes/
│   │   ├── api_routes/         # 26 route modules
│   │   │   ├── chat_stream_routes.py   # /chat/stream SSE pipeline
│   │   │   ├── code_agent_routes.py    # /agent/*, /code-agent/*
│   │   │   ├── agents_routes.py        # /agents CRUD + run
│   │   │   ├── teams_routes.py         # /teams, /teams/run/stream SSE
│   │   │   ├── knowledge_routes.py     # /knowledge/graph, /knowledge/search, /knowledge/retrieve, /knowledge/ingest-url
│   │   │   ├── artifacts_routes.py     # /artifacts + versions
│   │   │   ├── automations_routes.py   # /automations CRUD + run-now
│   │   │   ├── compare_routes.py       # /compare, /arena/*
│   │   │   ├── voice_routes.py         # /voice/*
│   │   │   ├── image_routes.py         # /image/*
│   │   │   ├── learn_routes.py         # /learn/*
│   │   │   ├── quality_routes.py       # /quality/preview
│   │   │   ├── spec_routes.py          # /spec/build, /spec/to-task
│   │   │   ├── runs_routes.py          # /runs history
│   │   │   ├── settings_routes.py      # /user/settings
│   │   │   ├── memory_routes.py        # /memory*
│   │   │   ├── omniroute_routes.py     # /omniroute/*
│   │   │   ├── features_routes.py      # /features flags
│   │   │   ├── extensions_routes.py    # /extensions
│   │   │   ├── media_routes.py         # /media/*
│   │   │   ├── analytics_routes.py     # /analytics/*
│   │   │   ├── chats_routes.py         # chat CRUD, summary, feedback
│   │   │   ├── models_routes.py        # model catalogue
│   │   │   ├── providers_routes.py     # keys, refresh, /providers/status
│   │   │   ├── files_routes.py         # document upload
│   │   │   └── common.py               # SSE framing helpers
│   │   ├── auth.py             # Local auth (register, login, logout, sessions, CSRF, lockout)
│   │   ├── llm.py              # Provider facade — model resolution, streaming
│   │   ├── code_agent.py       # Agentic coding loop (write_file/edit_file/run_bash, approvals)
│   │   ├── code_graph.py       # AST code graph
│   │   ├── knowledge_graph.py  # Unified knowledge graph builder
│   │   ├── graph_provenance.py # Edge provenance (EXTRACTED/INFERRED/AMBIGUOUS)
│   │   ├── automations.py      # Automation scheduler
│   │   ├── spec_chain.py       # Spec → plan → tasks → coverage chain (spec_wizard.py retired)
│   │   ├── instincts.py        # Learned coding patterns (confidence-scored)
│   │   ├── omniroute_config.py # OmniRoute gateway config
│   │   ├── feature_flags.py    # Runtime feature flags (persisted)
│   │   ├── domain.py / response_policy.py  # Response policy rules
│   │   ├── capability_orchestration.py  # Clarification gate
│   │   ├── response_events.py  # Canonical SSE event model
│   │   ├── response_intelligence/  # Intent/style classification
│   │   ├── response_quality/   # AI-slop cleanup + ADHD formatting
│   │   ├── response_postprocessor.py   # Uncertainty hedging
│   │   ├── context_manager.py  # Context truncation / token budgeting
│   │   ├── memory/             # Typed memory store (episodic/semantic/procedural)
│   │   ├── summarizer.py       # Rolling chat summarization
│   │   ├── security.py         # Fernet encryption (MASTER_KEY) + CSRF
│   │   ├── prompt_injection.py # Prompt-injection detection
│   │   ├── document.py         # File text extraction
│   │   ├── rag.py              # Document chunking + vector retrieval
│   │   ├── websearch.py        # Web search (DuckDuckGo/Tavily/Brave)
│   │   ├── analytics/          # Local-first analytics
│   │   ├── learn/              # Learning mode (lessons, tutor)
│   │   ├── image_gen/          # Image generation engines
│   │   ├── voice/              # TTS/STT engines
│   │   ├── mcp/                # MCP client
│   │   ├── extensions/         # Extension registry
│   │   ├── skills/             # Skills registry, executor, packs
│   │   ├── teams/              # Multi-agent teams (streaming.py)
│   │   ├── tools/              # Tool-calling registry + executor
│   │   ├── ratelimit.py        # Rate limiting (+ ratelimit_redis.py)
│   │   ├── middleware/         # ASGI middleware
│   │   ├── migrations/         # Alembic migration scripts
│   │   └── providers/          # Provider adapters + registry
│   │       ├── __init__.py / base.py / registry.py
│   │       ├── model_discovery.py / key_resolver.py
│   │       ├── fallback_chain.py   # Circuit breakers + quotas + fallback
│   │       ├── ollama.py / openai_compatible.py
│   │       ├── anthropic.py / gemini.py / nvidia.py
│   │       ├── litellm_fallback.py / compat.py / inaccessible.py
│   │       └── enhanced/       # Intelligent routing layer
│   ├── frontend/               # Static frontend (served via Python http.server)
│   │   ├── index.html          # Single-page application HTML
│   │   ├── css/style.css       # Complete design system
│   │   ├── js/
│   │   │   ├── app.js          # Main bootstrap
│   │   │   ├── core/           # state.js, nav.js, jobs.js
│   │   │   ├── shared/         # 10 modules (http, markdown, settings_store, i18n, …)
│   │   │   └── features/       # 26 feature modules (agents, knowledge, create, …)
│   │   ├── assets/logo.png     # Sangam brand logo
│   │   └── package.json        # {"type": "module"} for node --check
│   ├── config/
│   │   ├── providers.yaml      # Reference provider registry (docs only)
│   │   └── skills/             # Skill definitions (SKILL.md files)
│   ├── history/                # SQLite database (sangam.db)
│   ├── uploads/                # Uploaded file storage
│   └── logs/                   # Rotating application logs (loguru)
├── tests/                      # Unified test tree (71 source files: unit, integration/, e2e/, manual/)
│   ├── conftest.py             # Shared fixtures
│   ├── integration/            # HTTP-level API tests
│   ├── e2e/                    # Playwright golden paths
│   └── test_*.py               # Unit tests per module
├── scripts/                    # check_frontend_modules.mjs, quality.sh, e2e_walkthrough.py, …
├── start.py                    # Launcher: venv, deps, env, then both servers
├── start.bat / start.sh        # One-command start (Windows / Unix)
├── .env / .env.example         # Environment configuration
├── pyproject.toml              # Ruff, mypy, pytest, coverage, bandit config
├── requirements.txt            # Python dependencies
├── README.md                   # Project README
└── ARCHITECTURE.md             # This file
```

## 3. Backend Architecture

### 3.1 Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Web Framework | **FastAPI** (0.141) | Async REST API with auto-docs |
| ASGI Server | **Uvicorn** (0.34) | Production-grade Python ASGI server |
| Database | **SQLite + aiosqlite** | Local persistence, zero config |
| ORM | **SQLAlchemy 2.0** (async) | Type-safe database access |
| Validation | **Pydantic v2** | Request/response validation |
| LLM Client | **LiteLLM** (1.56) | Unified API for 100+ LLM providers |
| HTTP Client | **httpx** (0.27) | Async HTTP for model APIs + web search |
| Logging | **loguru** | Structured logs to stdout + rotating file (`mainfiles/logs/app.log`) |

### 3.2 Application Lifespan (`main.py`)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "history").mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "logs").mkdir(parents=True, exist_ok=True)
    await init_db()       # Create all SQLAlchemy tables
    yield
    _cleanup_ollama()                  # Terminate auto-started Ollama, if any
    await close_rate_limit_store()     # Close Redis connection, if any
```

The lifespan handler runs on startup:
1. Creates the `uploads/`, `history/`, and `logs/` directories if missing
2. Runs `Base.metadata.create_all` to create all database tables

On shutdown it terminates an auto-started Ollama child process and closes the rate-limit store.

### 3.3 CORS Configuration

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,  # ["http://localhost:5500", "http://127.0.0.1:5500", "http://localhost:3000"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

The CORS middleware allows the frontend (running on port 5500) to call the backend (port 8001). Additional middleware stacks on top of CORS (request order): `RequestIDMiddleware` → `RequestLoggingMiddleware` → `SecurityHeadersMiddleware` (CSP, `X-Frame-Options`, HSTS in production) → `RateLimitMiddleware` → CORS → CSRF validation.

### 3.4 Router Mounting

```python
app.include_router(public_router, prefix=settings.API_PREFIX)                # /api/health
app.include_router(auth_router, prefix=settings.API_PREFIX)                  # /api/auth/*
app.include_router(api_router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])  # /api/*
app.include_router(skills_router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])  # /api/skills/*
```

- **Health** is public (`/api/health`)
- **Auth routes** are unprotected (registration/login/forgot-password)
- **API routes** require a valid bearer token via `get_current_user` dependency
- **Skills routes** also require authentication

**Route handlers** live in `api_routes/`, split by resource (mounted through the `api.py` facade):

| Module | Endpoints |
|--------|-----------|
| `common.py` | SSE framing helpers, upload MIME validation, shared routers |
| `providers_routes.py` | Provider key CRUD, live model refresh, websearch, `/health`, provider status |
| `files_routes.py` | Document upload (validation → storage → extraction → RAG index) |
| `chats_routes.py` | Chat CRUD, user preferences, rolling summary, message feedback |
| `models_routes.py` | Model catalogue (`/models`, `/models/{provider}`) |
| `chat_stream_routes.py` | The streaming pipeline (`/chat/stream`) |
| `code_agent_routes.py` | Agent execution (`/agent/run` SSE, `/agent/approve`) + code agent (`/code-agent/*`) |
| `agents_routes.py` | Custom agents CRUD (`/agents`) + run (`/agents/{id}/run` SSE) |
| `teams_routes.py` | Multi-agent teams (`/teams`, `/teams/run`, `/teams/run/stream` SSE, `/teams/retry-agent`) |
| `knowledge_routes.py` | Knowledge graph (`/knowledge/graph`, `/knowledge/search`, `/knowledge/retrieve`, `/knowledge/ingest-url`) |
| `artifacts_routes.py` | Typed artifacts CRUD (`/artifacts`) + versions |
| `automations_routes.py` | Scheduled tasks (`/automations`) |
| `compare_routes.py` | Model compare (`/compare`) + Arena (`/arena/vote`, `/arena/leaderboard`) |
| `voice_routes.py` | Voice TTS/STT (`/voice/*`) |
| `image_routes.py` | Image generation (`/image/*`) |
| `learn_routes.py` | Learning mode (`/learn/*`) |

`api.py` re-exports every handler so `backend.main` mounts `router`/`public_router` from one stable import surface, and tests can patch `backend.api.*` as before.

---

## 4. Frontend Architecture

### 4.1 Single-Page Application

The frontend is a vanilla JS SPA served as static files. There is no build step, no framework — just HTML, CSS, and JS loaded directly.

**Libraries (loaded from CDN, pinned with SRI hashes where supported):**
| Library | Version | Purpose |
|---------|---------|---------|
| Font Awesome | 6.5.1 | Icons (free tier) |
| Google Fonts | — | Sora (display), Inter (body), JetBrains Mono (code) |
| Highlight.js | 11.11.0 | Code syntax highlighting |
| Marked | 15.0.7 | Markdown → HTML rendering |
| DOMPurify | 3.2.4 | HTML sanitization |
| KaTeX | 0.16.9 | LaTeX math rendering (with SRI integrity hashes) |

### 4.2 Layout Structure

```
┌──────┬───────────────────────────────────────────────────┐
│ RAIL │  TAB STRIP                                         │
│      │  [Main Chat*] [Knowledge] [Create] ... [+]         │
│ Home ├───────────────────────────────────────────────────┤
│ Chat │                                                    │
│Agents│  ACTIVE TAB CONTENT                                │
│ Know │  (chat, knowledge graph, create hub, etc.)         │
│Create│                                                    │
│ Code ├───────────────────────────────────────────────────┤
│ Learn│  COMPOSER (chat tab only)                          │
│ Lib  │  [Attach] [Textarea] [Send] [Mode] [Tools] [Tune] │
│ ...  └───────────────────────────────────────────────────┘
│      │  INSPECTOR (right, Ctrl+Shift+I) │ ACTIVITY TRAY   │
└──────┴───────────────────────────────────────────────────┘
```

The **chat-focused sidebar** (left) provides searchable history, New Chat, profile
actions, and compact collapsed behavior. The main chat tab is pinned and never
closes. Tool tabs open side-by-side for stateful work. The Inspector (right panel)
shows contextual details. The Activity Tray (bottom) tracks background jobs.

### 4.3 Module Organization

The frontend uses a **feature-based module structure** under `frontend/js/` — each
feature owns its own DOM, state, and logic. 50 modules total (verified by
`scripts/check_frontend_modules.mjs`).

**Core** (`js/core/`):
| Module | Responsibility |
|--------|----------------|
| `state.js` | Central signal store — `[get, set]` pairs for providers, models, chats, messages, selectedModel, temperature, maxTokens, reasoningEffort, webSearchEnabled, settings, etc. Also `createComputed` / `createSyncedSignal` helpers |
| `nav.js` | Compatibility hook for future tool navigation; the current UI keeps the sidebar focused on chat history |
| `jobs.js` | Background job tracking for the Activity Tray |

**Shared** (`js/shared/`):
| Module | Responsibility |
|--------|----------------|
| `constants.js` | `DEFAULT_SETTINGS`, `CHAT_BUCKETS`, `STORAGE_KEYS`, provider color/label maps |
| `http.js` | `apiFetch`, `apiGet/apiPost/apiPut/apiDelete`, `streamChatCompletion`, `parseSSE` |
| `markdown.js` | Streaming-safe markdown → HTML (marked + highlight.js + KaTeX) |
| `toast.js` | Toast notifications |
| `utils.js` | `escapeHtml`, `formatDate`, `debounce`, etc. |
| `settings_schema.js` | Typed settings schema (14 categories, 30+ settings) |
| `settings_store.js` | Settings persistence (server-backed via `/api/user/settings`) |
| `runlog.js` | Shared live execution log (agent steps, tool calls) |
| `focus_trap.js` | Focus trap utility for modals (a11y) |
| `i18n.js` | `t()` + `setLang()` — English + Hindi UI strings |

**Features** (`js/features/`):
| Module | Responsibility |
|--------|----------------|
| `auth/` | Login, register, forgot/reset password, session check, logout |
| `chat/` | SSE streaming orchestration, send/regenerate, file attachments, clarification cards, agent mode |
| `models/` | Model selector dropdown, provider status badges |
| `settings/` | `settings.js` (legacy modal: theme, API keys) + `settings_page.js` (schema-driven full page) |
| `sidebar/` | Chat history list (bucketed by date), new chat, delete chat |
| `tabs/` | Mount-once persistent tab manager (main chat pinned) |
| `agents/` | Agent Hub: custom agent CRUD, run with streaming, approval cards |
| `teams/` | Multi-agent team UI |
| `knowledge/` | Knowledge graph (SVG), search, MCP manager, memory browser |
| `create/` | Artifact hub: docs, diagrams, code, HTML + version history |
| `code-agent/` | Agentic coding UI with RunLog |
| `design/` | Design Studio: prototype gen + iframe preview |
| `learn/` | Learning mode: lessons, skill importer |
| `library/` | Skills, MCP servers, extensions, templates browser |
| `automations/` | Scheduled task CRUD + run-now |
| `routing/` | Model routing rules, combos, quota display |
| `inspector/` | Right-panel contextual inspector (Ctrl+Shift+I) |
| `tray/` | Activity Tray for background jobs |
| `home/` | Home dashboard |
| `analytics/` | Insights dashboard |
| `image/` | Image generation UI |
| `voice/` | Voice controls (TTS/STT) |
| `composer/` | Composer popovers (Mode, Tools, Tune) |
| `palette/` | Command palette (Ctrl+P) |
| `presets/` | UI presets (Minimal, Standard, Studio, etc.) |
| `skills/` | Legacy skills browser (see Library) |

**Boot sequence (`app.js` `init()`):**
1. Initialize DOM references
2. Initialize global state — settings loaded from server (`/api/user/settings`)
3. Initialize core: auth → nav → tabs → jobs
4. Initialize feature modules
5. `initializeAuth()` — validates session, then `startApplication()` on success
6. Register service worker (PWA), apply i18n language

### 4.4 State Management

The frontend uses a central **signal-based reactive store** (`core/state.js`):

```javascript
// state.js — createSignal returns a [get, set, subscribe] tuple
export function createSignal(initialValue) {
  let value = initialValue;
  const subscribers = new Set();

  const get = () => value;

  const set = (newValue) => {
    const nextValue = typeof newValue === 'function' ? newValue(value) : newValue;
    if (Object.is(nextValue, value)) return;
    value = nextValue;
    subscribers.forEach((fn) => fn(value));
  };

  const subscribe = (fn) => {
    subscribers.add(fn);
    return () => subscribers.delete(fn);
  };

  return [get, set, subscribe];
}

// State is exported as destructured [get, set] pairs
export const [getProviders, setProviders] = createSignal([]);
export const [getChats, setChats] = createSignal([]);
export const [getMessages, setMessages] = createSignal([]);
export const [getActiveChatId, setActiveChatId] = createSignal(null);
export const [getSelectedModel, setSelectedModel] = createSignal(null);
export const [getIsGenerating, setIsGenerating] = createSignal(false);
export const [getTemperature, setTemperature] = createSignal(0.7);
export const [getMaxTokens, setMaxTokens] = createSignal('1024');
export const [getReasoningEffort, setReasoningEffort] = createSignal('medium');
export const [getWebSearchEnabled, setWebSearchEnabled] = createSignal(false);
export const [getSidebarCollapsed, setSidebarCollapsed] = createSignal(false);
export const [getBackendReachable, setBackendReachable] = createSignal(null);
```

Components subscribe to signals they care about — when state changes, only dependent UI updates.

### 4.5 Design System

Sangam uses a **Paper / Ink** design language — a monochrome "premium electronic paper" chrome for a high-end desktop productivity tool. Two themes are applied via the `data-theme` attribute on `<html>` (`light` / `dark`, or `system` resolved at runtime). The chrome is intentionally monochrome: `--accent` is *ink*, not a brand hue, and there are **no user-selectable accent swatches**.

| Token | INK (dark) | PAPER (light) |
|-------|------------|---------------|
| `--bg-base` (page ground) | `#121315` | `#F4F2ED` |
| `--bg-surface` (chrome) | `#191A1D` | `#FBFAF7` |
| `--bg-elevated` (raised cards) | `#202125` | `#FEFDF9` |
| `--bg-elevated-2` (wells/insets) | `#28292E` | `#EDEAE3` |
| `--accent` (ink) | `#E6E4DE` | `#3A342B` |
| `--text-primary` | `#EAE9E4` | `#201D17` |
| `--font-display` | Sora | Sora |
| `--font-body` | Inter | Inter |
| `--font-mono` | JetBrains Mono | JetBrains Mono |

Semantic surface aliases keep raised/sunken layering consistent across the chrome, cards, popovers and dialogs:

| Alias | Maps to | Used for |
|-------|---------|----------|
| `--surface-page` | `--bg-base` | page ground |
| `--surface-panel` | `--bg-surface` | sidebar, topbar, suggestion cards |
| `--surface-raised` | `--bg-elevated` | modals, popovers, dialogs, dropdowns |
| `--surface-sunken` | `--bg-elevated-2` | active rows, wells, inset fields |

Design rules:

- **No pure `#FFF` / `#000`** — surfaces are warm off-whites (`#FEFDF9`) and deep charcoals; white/black are never used as surface fills.
- **Color is rare and semantic** — `--success` / `--warning` / `--danger` / `--info` / `--reasoning` exist only for status/state, never for chrome.
- **Typography** — Sora (display), Inter (body), JetBrains Mono (code); the Settings font-size maps to a `--font-scale` multiplier (`sm .92` / `md 1` / `lg 1.1`) applied to messages, composer, suggestion cards and welcome copy.
- **Interaction states** — every control defines default / hover / focus-visible / active / disabled; micro-interactions run at 120 ms (fast) / 200 ms (medium) on `cubic-bezier(.4,0,.2,1)`.
- **Motion & contrast** — `prefers-reduced-motion` collapses animation; `forced-colors` keeps focus rings visible under Windows High Contrast.

The full token reference lives in the design tokens section at the top of `frontend/css/style.css`.

---

## 5. Data Flow

### 5.1 Chat Flow (Complete Request Lifecycle)

```
USER                   FRONTEND                         BACKEND                       PROVIDER API
 │                        │                                │                              │
 │  Type message          │                                │                              │
 │───────────────────────>│                                │                              │
 │                        │  POST /api/chat/stream         │                              │
 │                        │───────────────────────────────>│                              │
 │                        │                                │  Validate auth token         │
 │                        │                                │  Validate message schema     │
 │                        │                                │  Resolve model (400 if unknown) │
 │                        │                                │                              │
 │                        │                                │  [Optional] Web search       │
 │                        │                                │  [Optional] File RAG context │
 │                        │                                │  [Optional] Response Intel:  │
 │                        │                                │   intent/style guidance,     │
 │                        │                                │   clarification gate,        │
 │                        │                                │   cross-session memory,      │
 │                        │                                │   context truncation         │
 │                        │                                │                              │
 │                        │                                │  If new chat:                │
 │                        │                                │    - Create Chat row in DB   │
 │                        │                                │                              │
 │                        │   SSE: chat_id frame           │                              │
 │                        │<───────────────────────────────│   Call LLM provider          │
 │                        │   SSE: response_event          │──────────────────────────────>│
 │                        │<───────────────────────────────│   (message_start, text_delta, │
 │                        │   SSE: response_event          │    reasoning_delta, …)        │
 │                        │<───────────────────────────────│<──────────────────────────────│
 │                        │   ...                         │                              │
 │                        │   SSE: response_event          │                              │
 │                        │   (message_end + usage)         │                              │
 │                        │<───────────────────────────────│                              │
 │                        │   SSE: data=[DONE]            │   Persist user+assistant      │
 │                        │<───────────────────────────────│   messages atomically         │
 │                        │                                │                              │
 │  See streaming text    │                                │                              │
 │<───────────────────────│                                │                              │
```

### 5.2 SSE Event Protocol

The backend uses Server-Sent Events (text/event-stream) with two frame categories:

**1. Legacy/plain frames** (compatibility + lifecycle):

```
event: chat_id
data: abc123def456

event: error
data: Provider API key not linked

: heartbeat 1728153600        (SSE comment — sent during long silent stretches)

data: [DONE]
```

- `chat_id` (sent once): The database ID of the chat (useful when creating a new chat)
- `error`: Fatal error — streaming terminated (also emitted alongside the canonical error event)
- `[DONE]` data: Signal that streaming completed successfully
- Heartbeat comments (`: heartbeat <ts>`) keep the connection alive during long provider stalls

**2. Canonical `response_event` frames** (the primary protocol, built by `ResponseEventBuilder` in `response_events.py`):

```
event: response_event
data: {"type": "message_start", "sequence": 0, "message_id": "…", "request_id": "…", "provider": "ollama", "model": "…"}

event: response_event
data: {"type": "text_delta", "sequence": 1, "message_id": "…", "content": "Hello"}

event: response_event
data: {"type": "message_end", "sequence": 9, "finish_reason": "stop", "usage": {…}}
```

Every frame carries a monotonic `sequence` number plus `message_id`/`request_id` correlation IDs. Event types (`ResponseEventType`): `message_start`, `text_start`, `text_delta`, `text_end`, `reasoning_start/delta/end`, `tool_start/input_delta/end/result`, `citation`, `clarification_request`, `artifact_start/delta/end`, `usage`, `message_end`, `error`. The builder enforces lifecycle invariants (e.g. `message_start` must be first; the client controller enforces the same rule).

### 5.3 SSE Parsing in Frontend

The frontend parses frames with an async generator (`parseSSE()` in `shared/http.js`) that normalizes CRLF line endings, splits frames on blank lines, and yields `{ event, data }` objects. `features/chat/response_controller.js` consumes them: `response_event` payloads drive a client-side state machine (message/text/reasoning/tool/clarification/artifact lifecycle), while legacy `chat_id`/`error`/`[DONE]` frames are handled for compatibility.

---

## 6. Authentication System

### 6.1 Design

Single-user, local-only authentication. No OAuth, no third-party identity providers. The first user to register creates the account (`registration_open` is true only while the `users` table is empty); subsequent visitors are prompted to sign in. Includes brute-force login lockout (sliding-window rate limit after consecutive failures) and a forgot-password / reset-token flow (single-use tokens, 30-minute expiry).

### 6.2 Password Hashing

```python
def _hash_password(password: str, salt: str) -> str:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=bytes.fromhex(salt),
        n=2**14, r=8, p=1
    ).hex()  # 64 bytes → 128 hex chars
```

Uses **scrypt** with N=16384, r=8, p=1 — memory-hard, resistant to GPU/ASIC attacks.

### 6.3 Session Tokens

```python
def _issue_token() -> str:
    return secrets.token_urlsafe(32)  # 43 chars, cryptographically random

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
```

- Token is issued to the client once (stored in `localStorage`)
- Only the SHA-256 hash is stored in the database
- Sessions expire after 30 days
- CSRF protection via double-submit cookie (`sangam_csrf` cookie + `X-CSRF-Token` header) — enforced for cookie-based sessions; Bearer-token clients skip CSRF (they are not cookie-exposed)

### 6.4 Auth Flow

```
┌─────────────────┐          ┌─────────────────┐          ┌──────────┐
│                 │  GET      │                 │          │          │
│   Frontend      │ ─────────>│   /auth/status  │ ───────> │  SQLite  │
│                 │           │                 │          │          │
│                 │<──────────│  registration   │<──────── │          │
│                 │    open?  │                 │  count   │          │
│                 │           │                 │          │          │
│                 │  POST     │                 │          │          │
│                 │ ─────────>│  /auth/register │ ───────> │  Create  │
│                 │           │   or /login     │          │  user +  │
│                 │<──────────│                 │<──────── │ session  │
│                 │  token    │                 │  token   │          │
│                 │           │                 │          │          │
│                 │  GET      │                 │          │          │
│                 │ ─────────>│  /auth/me       │ ───────> │  Verify  │
│                 │           │                 │          │  token   │
│                 │<──────────│  {username}     │<──────── │          │
│                 │           │                 │          │          │
└─────────────────┘          └─────────────────┘          └──────────┘
```

---

## 7. Provider & Model System

### 7.1 Supported Providers

| Provider | ID | Cloud/Local | Key Required | LiteLLM Prefix |
|----------|-----|-------------|--------------|-----------------|
| Anthropic | `anthropic` | Cloud | Yes | `anthropic/` |
| OpenAI | `openai` | Cloud | Yes | `openai/` |
| NVIDIA NIM | `nvidia` | Cloud | Yes | `nvidia_nim/` |
| Together AI | `together` | Cloud | Yes | `together_ai/` |
| Groq | `groq` | Cloud | Yes | (none) |
| OpenRouter | `openrouter` | Cloud | Yes | (none) |
| DeepSeek | `deepseek` | Cloud | Yes | `deepseek/` |
| Mistral | `mistral` | Cloud | Yes | (none) |
| Gemini | `gemini` | Cloud | Yes | `gemini/` |
| Ollama | `ollama` | Local | No | `ollama/` |
| OmniRoute | `omniroute` | Local proxy | Optional | OpenAI-compatible base URL |

### 7.2 Model Discovery — Two-Tier System

**Tier 1: Live API Fetch** (`fetch_models_from_provider` in `providers/model_discovery.py`)

For each provider with a linked API key, the backend queries the provider's actual model listing endpoint:

| Provider | API Endpoint | Auth Method |
|----------|-------------|-------------|
| OpenAI | `GET /v1/models` | Bearer token |
| Anthropic | `GET /v1/models` | x-api-key header |
| Gemini | `GET /v1beta/models` | Query param (`key=`) |
| NVIDIA NIM | `GET /v1/models` | Bearer token |
| Together/Groq/OpenRouter | `GET /v1/models` | Bearer token |
| DeepSeek/Mistral | `GET /v1/models` | Bearer token |

Models are filtered to remove non-chat ones (embedding, vision, dall-e, whisper, moderation, rerank, etc.) using keyword matching against `_NON_CHAT_MARKERS`.

**Tier 2: Curated Fallback** (`CURATED_MODELS`)

If live fetch fails (offline, bad key), curated defaults are shown so the provider isn't invisible:

```python
CURATED_MODELS = {
    "claude-sonnet-4":   ModelInfo(id="claude-sonnet-4", …, litellm_id="anthropic/claude-sonnet-4"),
    "gpt-4o":            ModelInfo(id="gpt-4o", …, litellm_id="openai/gpt-4o"),
    "nim-llama-3-3-70b": ModelInfo(id="nim-llama-3-3-70b", …, litellm_id="nvidia_nim/meta/llama-3.3-70b-instruct"),
    # ... (full list in providers/compat.py)
}
```

### 7.3 Ollama Integration

Ollama gets special treatment:

```python
async def list_ollama_models():
    # 1. Query local Ollama server: GET /api/tags
    # 2. If unreachable, try to auto-start `ollama serve` in background
    # 3. Query again after a delay
    # 4. Return real pulled models only
```

The `_try_start_ollama()` function in `providers/ollama.py` **actually spawns** a detached `ollama serve` process (located via `shutil.which("ollama")`) when the server is unreachable and the binary is installed. It runs at most once per backend process; the child handle is tracked globally and terminated by `_cleanup_ollama()` on application shutdown (see the `main.py` lifespan). If Ollama is not installed, discovery simply returns no local models — you can still run `ollama serve` manually if you prefer.

### 7.4 Model Resolution

Model IDs flow through the system in this format:

- **Ollama models:** `ollama:llama3.2` (accepted input) → resolved to `ollama::llama3.2` with `litellm_id="ollama/llama3.2"`
- **Dynamic cloud models:** `openai::openai/gpt-4o` → `::` separator between provider_id and litellm_id (this is the format `/api/models` returns)
- **Curated models:** `::`-prefixed IDs matched against `CURATED_MODELS` by litellm_id

The `_resolve_model()` function in `llm.py` handles all three formats; unknown IDs make `/api/chat/stream` fail fast with a 400 `Unknown model`.

### 7.5 Provider Key Management

Users can link API keys entirely from the Settings UI — no `.env` editing required:

- **PUT** `/api/settings/providers/{id}/key` — Save a new key (stored in SQLite `provider_keys` table, encrypted with Fernet)
- **DELETE** `/api/settings/providers/{id}/key` — Remove a saved key
- **GET** `/api/settings/providers` — List all providers with masked key status

The `resolve_api_key()` function checks database keys first (Fernet-encrypted `provider_keys` table), then falls back to `.env` values:

```python
async def resolve_api_key(provider_id: str, db: AsyncSession) -> str | None:
    db_keys = await get_db_keys(db)
    if provider_id in db_keys:
        return db_keys[provider_id]
    return get_static_env_key(provider_id)
```

---

## 8. Chat Streaming

### 8.1 Route Handler (`POST /api/chat/stream`)

The request body (`ChatStreamRequest`) includes:

```json
{
    "chat_id": null,         // null = create new chat
    "model": "openai::openai/gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}],
    "file_ids": [],
    "temperature": 0.7,
    "max_tokens": 1024,
    "regenerate": false,
    "web_search": false,
    "reasoning_effort": "medium"
}
```

Processing pipeline (implemented in `api_routes/chat_stream_routes.py`; in order, all best-effort steps fail open with a log warning):
1. **Model validation** — unknown models are rejected with a fast 400 before any resources are allocated
2. **Web search** (optional) — live results injected as a system message
3. **Chat resolution** — find existing or create new `Chat` record
4. **File context** — RAG retrieval over attached files, folded into the latest user message
5. **Response Intelligence** — intent/style analysis → system-prompt guidance; user's stored preferences override detected style
6. **Clarification gate** — ambiguous short requests short-circuit into a `clarification_request` event with interpretation options (no provider call)
7. **Cross-session memory** — relevant past-chat summaries injected as context
8. **Safe context truncation** — token budgeting before provider routing
9. **Stream** — `llm.stream_response_events()` yields canonical response events; SSE heartbeats keep the connection alive
10. **Persist atomically** — user + assistant messages saved in one commit (orphaned-chat cleanup on disconnect/error); rolling summarization fires in the background
11. **Uncertainty post-processing** — hedges are applied to the *stored* text only, never the live stream

### 8.2 Provider Routing (`stream_response_events`)

`llm.py` is a facade over the `providers/` package. `stream_response_events()` (and the chunk-level `stream_completion()`) delegate to `providers/__init__.py`, where the enhanced routing layer (`providers/enhanced/`) scores providers on cost/latency/capability before dispatching:

```python
async def stream_response_events(model_id, messages, db, temperature, max_tokens, reasoning_effort, message_id, request_id):
    model = _resolve_model(model_id)  # Convert app model_id → ModelInfo
    if model.provider_id == "ollama":
        async for event in ollama_provider.stream_response_events(...):
            yield event
        return

    # Cloud provider: OpenAI-compatible adapter or LiteLLM fallback
    api_key = await resolve_api_key(model.provider_id, db)
    async for event in provider.stream_response_events(...):
        yield event
```

Events are built by `ResponseEventBuilder` (`response_events.py`), which normalizes provider-specific chunks (including reasoning content) into the canonical event stream. Unknown/inaccessible models are filtered through `inaccessible.py` markers.

**Ollama streaming** uses its native `/api/chat` endpoint with SSE parsing for better support of reasoning models:

```python
payload = {"model": model.name, "messages": messages, "stream": True, "options": {...}}
async with client.stream("POST", endpoint, json=payload) as response:
    async for line in response.aiter_lines():
        chunk = json.loads(line)
        content = chunk.get("message", {}).get("content", "")
        if content:
            yield content
```

---

## 9. Skills System

### 9.1 Skill Definition Format

Skills are defined as `SKILL.md` files in `mainfiles/config/skills/<skill-name>/SKILL.md` using YAML front matter:

```markdown
---
id: api-design
name: API Design Assistant
category: engineering
invocation: both
parameters:
  - name: spec_type
    type: string
    description: Type of API specification needed
    required: true
  - name: model
    type: string
    description: Specific model to use
    required: false
    default: default
tags: [api, design, rest]
---

You are an API design expert. Given the following requirements...
```

### 9.2 Skill Categories

| Category | Example |
|----------|---------|
| `engineering` | Code review, architecture, API design, debugging |
| `design` | UI/UX feedback |
| `behavioral` | Interview coaching |
| `productivity` | Task planning, web search assistant |
| `knowledge` | Research assistant |
| `system` | DevOps, deployment |
| `personal` | Career advice |
| `misc` | Other |

### 9.3 Skill Registry

The `SkillRegistry` class:
1. Scans `mainfiles/config/skills/` for `SKILL.md` files
2. Parses YAML front matter + body
3. Validates parameters, categories, invocation types
4. Supports dependency resolution (`resolve()` — DFS traversal with cycle detection)
5. Supports parameterized prompt building (`build_prompt()`)

### 9.4 Skill Router

The `SkillRouter` handles execution:
1. **Resolve dependencies** — run dependent skills first (DFS order)
2. **Build prompt** — substitute parameters into the template
3. **Execute** — call the model with the skill prompt (uses default model from `default_model_id()`)
4. **Chain** — run multiple skills sequentially, passing context between them

### 9.5 Skill API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/skills/` | GET | List all skills (filterable by category, invocation, search) |
| `/api/skills/categories` | GET | List available categories |
| `/api/skills/{id}` | GET | Get skill detail with params, dependencies, prompt preview |
| `/api/skills/execute` | POST | Execute a skill with parameters |
| `/api/skills/auto-suggest` | POST | Suggest skills based on context |
| `/api/skills/chain` | POST | Execute a chain of skills sequentially |

### 9.6 Frontend Skills Browser

Skills are browsed in the **Library tab** (`features/library/`), which provides:
- **Search** — filter by name, description, tags
- **Category filters** — engineering, design, behavioral, productivity, knowledge, system, personal, misc
- **Detail panel** — parameters with validation, dependencies, execute button
- **Execution** — runs `/api/skills/execute`, shows result
- **Skill packs** — enable/disable bundled packs (spec-driven, diagramming, science, agent-loop)

The legacy skills modal (`features/skills/skills.js`) is deprecated in favor of the Library tab.
- `loadSkills()` moved from `init()` to `openSkillsModal()` so it runs after authentication (fixes 401 on first load)
- Category filter buttons now match backend `SkillCategory` enum values

---

## 10. Web Search

### 10.1 Architecture

```
┌──────────┐    POST /api/chat/stream     ┌──────────┐
│ Frontend │  (web_search: true)           │ Backend  │
│          │ ─────────────────────────────>│          │
│          │                               │          │
│          │                               │  websearch.web_search(query)
│          │                               │          │
│          │                               │  ┌──────┴──────┐
│          │                               │  │ DuckDuckGo  │ (free, no key)
│          │                               │  │ Tavily      │ (if configured)
│          │                               │  │ Brave       │ (if configured)
│          │                               │  └──────┬──────┘
│          │                               │          │
│          │                               │  Inject results as system message
│          │                               │          │
│          │  SSE: stream + web results    │          │
│          │<──────────────────────────────│          │
└──────────┘                               └──────────┘
```

### 10.2 DuckDuckGo Integration (Default)

No API key required. Uses the DuckDuckGo Lite HTML endpoint:

```python
response = await client.post(
    "https://lite.duckduckgo.com/lite/",
    data={"q": query, "kl": ""},
    headers={"User-Agent": "Mozilla/5.0 ..."}
)
```

The HTML response is parsed with regex to extract:
- **Anchors** with `class='result-link'` → title + URL
- **Cells** with `class='result-snippet'` → snippet text

### 10.3 Tavily / Brave Integration (Optional)

Set in `.env`:
```dotenv
WEB_SEARCH_PROVIDER=tavily   # or "brave"
WEB_SEARCH_API_KEY=tvly-xxx  # or your Brave API key
```

Both use JSON APIs for structured, higher-quality results.

### 10.4 Context Format

Search results are formatted as a system message injected into the model's context:

```
Web search results for the user's question (query):
- Title (URL): Snippet text
- ...

Use the sources above to answer when relevant. Cite the source URL
when you base a claim on a search result.
```

---

## 11. Document Processing

### 11.1 Supported Formats

| Extension | Library | Method |
|-----------|---------|--------|
| `.txt`, `.md` | — | `read_text()` |
| `.json`, `.html`, `.xml` | — | `read_text()` |
| `.py`, `.java`, `.js`, `.c`, ... | — | `read_text()` (source code) |
| `.pdf` | pypdf | `PdfReader().pages` |
| `.docx` | python-docx | Paragraph text extraction |
| `.csv` | pandas | `read_csv()` → `to_string()` |
| `.xlsx` | openpyxl | Cell-by-cell iteration |
| `.pptx` | python-pptx | Slide + shape text extraction |

### 11.2 File Upload Flow

```
1. User selects file(s) in frontend
2. Frontend sends POST /api/files with multipart form data
3. Backend validates:
   - Filename is not empty
   - Extension is in ALLOWED_UPLOAD_EXTENSIONS
   - File size < MAX_UPLOAD_SIZE_MB
4. File is saved to uploads/ directory with UUID prefix
5. Text is extracted via extract_text()
6. UploadedFile record is created in database
7. Response includes file_id, filename, extension, size, preview (first 300 chars)
8. Frontend stores file_id for use in chat messages
```

### 11.3 File Attachment in Chat (RAG)

When a message is sent with `file_ids`, the backend uses **Retrieval-Augmented Generation (RAG)** instead of full-text concatenation:

1. The user's latest message text is embedded using ChromaDB's built-in ONNX model (`all-MiniLM-L6-v2`)
2. The top-5 most similar chunks are retrieved from the vector index (filtered by `file_ids`)
3. Only those relevant chunks are injected into the prompt, prefixed with their source filenames
4. If RAG fails (e.g., vector index unavailable), the system falls back to full extracted text from the database

```
[User's original message]

[Attached files]
--- From document.pdf ---
[relevant chunk 1]
--- From document.pdf ---
[relevant chunk 2]
--- From data.csv ---
[relevant chunk]
```

**RAG Pipeline (backend/rag.py):**

| Step | Function | Description |
|------|----------|-------------|
| Chunk | `chunk_text()` | Paragraph-aware splitting (~500 tokens, 100-token overlap) |
| Index | `index_document()` | Chunk → embed → store in ChromaDB collection |
| Retrieve | `retrieve_relevant_chunks()` | Embed query → top-k L2 distance search |
| Cleanup | `delete_document_chunks()` | Remove all chunks for a deleted file |

**Key properties:**
- ChromaDB runs in embedded mode — no external service required
- Vector index stored on disk at `mainfiles/.chromadb/` (overridable via `CHROMA_DB_PATH`)
- All RAG operations catch exceptions and log warnings; chat never breaks
- Configurable chunk size (`CHUNK_SIZE`), overlap (`CHUNK_OVERLAP`), and top-k (`TOP_K`)

---

## 12. Testing

### 12.1 Test Suite Overview

The test suite is a single unified tree at `tests/` (60 test files: unit,
`integration/`, `e2e/`, `manual/`). As of Phase 6 (2026-10-09): **1148 passed,
1 flaky, 100 skipped**. The backend package is importable via the path setup in
`tests/conftest.py` (plus `PYTHONPATH=mainfiles` in CI).

Representative modules:

| Area | Files | Coverage |
|-----------|-------|----------|
| Authentication | `test_auth.py` | Password hashing, tokens, session lifecycle, brute-force lockout |
| API surface | `test_api.py`, `tests/integration/test_api_*.py` | Route behavior, auth gates, chat/model/file endpoints |
| Documents + RAG | `test_document.py`, `test_rag.py` | Extraction, truncation, chunking, retrieval |
| Models/providers | `test_models.py`, `test_providers.py`, `test_provider_adapters.py`, `test_llm.py` | Live fetch, filtering, Ollama discovery, curated fallback, routing |
| Enhanced routing | `test_enhanced_routing.py`, `test_standalone_routing.py` | Provider scoring, resilience, fallback dispatch |
| Response intelligence | `test_response_intelligence.py`, `test_capability_orchestration.py`, `test_clarification.py`, `test_response_events.py` | Ambiguity triggers, clarification gate, canonical SSE events |
| Policy + postprocessing | `test_policy_domain.py`, `test_policy_integration.py`, `test_policy_module.py`, `test_postprocessor.py` | Response policy rules, uncertainty hedging |
| Web search | `test_websearch.py` | DuckDuckGo parser, format_context, providers |
| Memory + feedback | `test_memory.py`, `test_message_feedback.py`, `test_preferences.py` | Cross-session memory, message feedback, user preferences |
| Streaming + frontend contract | `test_streaming.py`, `test_frontend_response_controller.py` | SSE frame format, client state machine |
| Phase 3: Knowledge + Agents | `test_phase3.py` | Knowledge graph, approval gate (approve/deny), run history |
| Phase 4: Create + Learn | `test_phase4.py` | Artifacts, spec wizard, quality preview |
| Phase 5: Automations | `test_phase5.py` | Automation CRUD, scheduler |
| Phase 6: Behaviors | `test_phase6_behaviors.py` | Budget stop, settings roundtrip, 1k-node graph perf, routing |
| Phase 6: Teams streaming | `test_teams_streaming.py` | SSE streaming, per-agent retry |
| Phase 6: Graph provenance | `test_graph_provenance.py` | Edge provenance, memory wings |
| Phase 6: Compare + Arena | `test_compare_arena.py` | Parallel compare, leaderboard |
| Phase 6: Fallback chain | `test_fallback_chain.py` | Circuit breakers, quotas, fallback |
| E2E (Playwright) | `tests/e2e/` | Smoke boot, authentication, composer popovers, Settings, chat, knowledge, and responsive layout flows |
| Other | `test_startup.py`, `test_schemas.py`, `test_skill_registry.py`, `test_skills.py`, `test_executor_coverage.py`, `test_context_manager.py`, `test_prompt_injection_new.py`, `test_ratelimit_redis.py`, `test_main.py`, `test_e2e.py` | Launcher, validation, skills, context truncation, injection detection, Redis limiter |

**Frontend module validation:** `scripts/check_frontend_modules.mjs` parses and links
all 50 ES modules through V8 (`node --experimental-vm-modules`). This catches
import/export errors that `node --check` misses.

### 12.2 Running Tests

```bash
# pytest (the runner — asyncio_mode=auto via pyproject.toml; fixtures in tests/conftest.py)
venv\Scripts\python.exe -m pytest tests -v

# with coverage (what CI runs)
PYTHONPATH=mainfiles TEST_MODE=1 python -m pytest tests -q --cov=backend --cov-report=term-missing
```

### 12.3 CI Pipeline (GitHub Actions)

The `.github/workflows/ci.yml` has two jobs:

**verify** — checkout, Python 3.13, Node 22, install deps (root `requirements.txt` + `mainfiles/backend/requirements-dev.txt`), `compileall` on `mainfiles/backend`/`start.py`/`scripts`/`tests`, run the unified pytest suite with pytest-cov (`PYTHONPATH=mainfiles`, `TEST_MODE=1`), enforce the coverage gate (66%, see `pyproject.toml`), `node --check` every file under `mainfiles/frontend/js`, and validate the frontend module graph with `scripts/check_frontend_modules.mjs`.

> **Note:** the coverage gate is the measured pytest baseline (66.27% on Linux/CI, 66.47% on Windows, as of 2026-10-09, 1148 passed / 100 skipped on the unified tree) rather than the historical 76%, because the response-intelligence and enhanced-provider subsystems still have limited coverage. Raise `fail_under` in `pyproject.toml` (and the workflow) as coverage grows.

**security** — Bandit static analysis and Safety dependency scan, uploaded as build artifacts (both non-blocking).

---

## 13. Configuration Reference

### 13.1 Environment Variables (`.env`)

```dotenv
# --- Application ---
APP_NAME=UniversalAI                          # App title in API responses
ENV=development                                # development | production (enables HSTS)
APP_DEBUG=false                                # FastAPI debug (maps to settings.DEBUG)
API_PREFIX=/api                                # URL prefix for all routes
ALLOWED_ORIGINS=["http://localhost:5500","http://127.0.0.1:5500","http://localhost:3000"]

# --- Security ---
MASTER_KEY=                                    # Fernet key for encrypting provider keys at rest
                                               # (start.py generates this automatically on first run)

# --- Storage ---
MAX_UPLOAD_SIZE_MB=25                          # File upload limit

# --- Provider API Keys (only set what you use) ---
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
NVIDIA_NIM_API_KEY=nvapi-...
TOGETHER_API_KEY=...
GROQ_API_KEY=gsk_...
OPENROUTER_API_KEY=sk-or-...
DEEPSEEK_API_KEY=sk-...
MISTRAL_API_KEY=...
GEMINI_API_KEY=AIza...
OMNIROUTE_API_KEY=...                          # optional (local proxy)

# --- Local Runtimes ---
OLLAMA_BASE_URL=http://localhost:11434
LM_STUDIO_BASE_URL=http://localhost:1234/v1
VLLM_BASE_URL=http://localhost:8001/v1

# --- Web Search (optional, DuckDuckGo is default) ---
WEB_SEARCH_PROVIDER=          # tavily, brave, or blank for DuckDuckGo
WEB_SEARCH_API_KEY=           # Required for Tavily/Brave
WEB_SEARCH_MAX_RESULTS=5
```

### 13.2 API Endpoints Summary

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| GET | `/api/health` | **No** | Health check (public) |
| GET | `/api/websearch?q=...` | Yes | Direct web search |
| GET | `/api/models` | Yes | Available models (live + curated fallback) |
| GET | `/api/models/{provider}` | Yes | Per-provider model listing |
| POST | `/api/models/inaccessible/clear` | Yes | Reset inaccessible-model markers |
| GET | `/api/analytics/stats` | Yes | Aggregate usage stats (opt-in) |
| GET | `/api/analytics/summary` | Yes | Quota-view summary: messages (14-day DB count) + tokens/cost (process-lifetime telemetry ledger) |
| GET | `/api/providers` | Yes | Provider status |
| GET | `/api/providers/status` | Yes | Circuit breaker + quota states (Phase 6.4d) |
| GET | `/api/omniroute/status` | Yes | OmniRoute gateway status |
| POST | `/api/omniroute/config` | Yes | Save OmniRoute endpoint + key |
| POST | `/api/omniroute/sync` | Yes | Sync models from OmniRoute |
| POST | `/api/chat/stream` | Yes | Stream chat response (SSE) |
| POST | `/api/agent/run` | Yes | Run agent loop (SSE streaming) |
| POST | `/api/agent/approve/{approval_id}` | Yes | Approve/deny tool call |
| POST | `/api/code-agent/run` | Yes | Code agent execution (SSE) |
| GET | `/api/designs/{project_id}/{filename}` | Yes | Design Studio generated file serving |
| POST | `/api/code-agent/code-map` | Yes | Codebase AST graph query |
| GET | `/api/chats` | Yes | List all chats (with summaries) |
| POST | `/api/chats` | Yes | Create a chat |
| GET | `/api/chats/{id}` | Yes | Get chat with messages |
| DELETE | `/api/chats/{id}` | Yes | Delete chat |
| GET | `/api/chats/{id}/summary` | Yes | Rolling summary + topics |
| GET | `/api/chats/{id}/export` | Yes | Export chat as Markdown |
| POST | `/api/chats/{id}/messages` | Yes | Append message (used by Agent mode) |
| POST | `/api/messages/{id}/feedback` | Yes | Message quality feedback (up/down + note) |
| POST | `/api/files` | Yes | Upload document |
| GET | `/api/files` | Yes | List uploaded documents (references only) |
| POST | `/api/media/upload` | Yes | Upload image/audio, returns attachment |
| GET | `/api/media/{media_id}` | Yes | Serve stored media file |
| GET | `/api/user/settings` | Yes | Get all settings (Phase 2) |
| PUT | `/api/user/settings` | Yes | Update settings |
| GET | `/api/memory` | Yes | List/search memories (ranked) |
| POST | `/api/memory` | Yes | Save a memory |
| DELETE | `/api/memory/{id}` | Yes | Forget a memory |
| GET | `/api/memory/stats` | Yes | Memory totals by kind |
| POST | `/api/memory/consolidate` | Yes | Decay + prune stale memories |
| PUT | `/api/memory/{id}/move` | Yes | Move memory to room/drawer |
| GET | `/api/memory/rooms` | Yes | Rooms/drawers hierarchy + counts |
| GET | `/api/memory/rooms/{room}/{drawer}` | Yes | Memories in one room/drawer |
| POST | `/api/memory/extract` | Yes | On-demand LLM fact extraction, saved as semantic memories (Batch 4) |
| GET | `/api/memory/entities` | Yes | List memory entities (Batch 4) |
| GET | `/api/memory/entities/{name}/timeline` | Yes | Entity timeline, open + closed relations (Batch 4) |
| POST | `/api/memory/entities/extract` | Yes | LLM extraction + entity/relation upsert, heuristic fallback without a model (Batch 4) |
| POST | `/api/memory/transcripts` | Yes | Store a verbatim transcript message, no cap (Batch 4) |
| GET | `/api/memory/transcripts` | Yes | List transcripts, newest first (Batch 4) |
| PUT | `/api/memory/{id}` | Yes | PATCH-style memory update, absent fields kept (Batch 4) |
| POST | `/api/memory/reflect` | Yes | Reflect over recalled memories + timelines, stored as a semantic memory; 503 without a model (Batch 4) |
| POST | `/api/notebooks` | Yes | Create a notebook (Batch 4) |
| GET | `/api/notebooks` | Yes | List notebooks (Batch 4) |
| GET | `/api/notebooks/{id}` | Yes | Get a notebook (Batch 4) |
| PUT | `/api/notebooks/{id}` | Yes | Update a notebook (Batch 4) |
| DELETE | `/api/notebooks/{id}` | Yes | Delete a notebook + children (Batch 4) |
| POST | `/api/notebooks/{id}/sources` | Yes | Add a notebook source (file/url/note/chat) (Batch 4) |
| GET | `/api/notebooks/{id}/sources` | Yes | List notebook sources (Batch 4) |
| PUT | `/api/notebooks/{id}/sources/{source_id}/context` | Yes | Set a source context mode (Batch 4) |
| GET | `/api/notebooks/{id}/retrieve` | Yes | Retrieve notebook context honouring context modes (Batch 4) |
| POST | `/api/notebooks/{id}/notes` | Yes | Add a notebook note (Batch 4) |
| GET | `/api/notebooks/{id}/notes` | Yes | List notebook notes with outgoing links (Batch 4) |
| GET | `/api/notebooks/{id}/notes/{note_id}` | Yes | Get a note with outgoing wiki-links (Batch 4) |
| POST | `/api/notebooks/{id}/notes/from-chat` | Yes | Save a chat message as a note; 404 if missing (Batch 4) |
| GET | `/api/notebooks/{id}/notes/{note_id}/backlinks` | Yes | Notes linking [[this title]] (Batch 4) |
| PUT | `/api/notebooks/{id}/notes/{note_id}` | Yes | Update a note; title change renames with link propagation (Deep-read merge) |
| POST | `/api/notebooks/{id}/notes/{note_id}/extract-section` | Yes | Extract a section into a new note; source keeps a [[link]] (Deep-read merge) |
| GET | `/api/notebooks/{id}/notes/{note_id}/expand` | Yes | Token-budgeted graph-expansion retrieval from a seed note (Deep-read merge) |
| POST | `/api/notebooks/{id}/transforms` | Yes | Run a prompt over sources; stored as transform + note (Batch 4) |
| GET | `/api/notebooks/{id}/transforms` | Yes | List notebook transforms (Batch 4) |
| GET | `/api/settings/providers` | Yes | Provider key status |
| PUT | `/api/settings/providers/{id}/key` | Yes | Save API key |
| DELETE | `/api/settings/providers/{id}/key` | Yes | Remove API key |
| GET | `/api/settings/providers/{id}/models/refresh` | Yes | Re-fetch models for one provider |
| GET | `/api/knowledge/graph` | Yes | Unified knowledge graph (Phase 3) |
| GET | `/api/knowledge/search` | Yes | Search across memories, docs, code, chats |
| GET | `/api/knowledge/retrieve` | Yes | Hybrid retrieval over documents (Phase 2) |
| POST | `/api/knowledge/ingest-url` | Yes | Ingest a public page as a document (Phase 2) |
| POST | `/api/workflows` | Yes | Create a DAG workflow (Phase 3) |
| GET | `/api/workflows` | Yes | List workflows (Phase 3) |
| GET | `/api/workflows/{id}` | Yes | Get workflow (Phase 3) |
| PUT | `/api/workflows/{id}` | Yes | Update workflow, version bumps on definition change (Phase 3) |
| DELETE | `/api/workflows/{id}` | Yes | Delete workflow (Phase 3) |
| POST | `/api/workflows/{id}/run` | Yes | Run workflow manually (Phase 3) |
| GET | `/api/workflows/{id}/runs` | Yes | List workflow runs (Phase 3) |
| POST | `/api/workflows/{id}/runs/{run_id}/replay` | Yes | Replay a run with the same input (Phase 3) |
| POST | `/api/workflows/{id}/webhook` | Yes | Webhook trigger, token-authenticated (Phase 3) |
| POST | `/api/media-jobs` | Yes | Create a media worker job, runs in background (Phase 4) |
| GET | `/api/media-jobs` | Yes | List media jobs (Phase 4) |
| GET | `/api/media-jobs/{id}` | Yes | Poll one media job (Phase 4) |
| POST | `/api/media-jobs/{id}/approve` | Yes | Resume a checkpoint-paused pipeline job; revision cap enforced (Batch 11) |
| POST | `/api/voice/dub` | Yes | True dubbing: timed segments -> fitted SRT/VTT/word-level ASS (Batch 11) |
| POST | `/api/voice/tts/chunked` | Yes | Chunked long-form TTS, WAV join with silence gaps (Batch 11) |
| POST | `/api/voice/audiobook` | Yes | Audiobook plan: chapters/spans/deterministic seeds + manifest (Batch 11) |
| POST | `/api/diagrams/validate` | Yes | Typed-IR validation: architecture/erd/sequence/workflow/timeline (Batch 11) |
| POST | `/api/diagrams/verify` | Yes | Layout verifier: 4px grid, single accent, budgets, overlap (Batch 11) |
| POST | `/api/diagrams/export` | Yes | Standalone HTML+SVG diagram export (Batch 11) |
| POST | `/api/design-systems` | Yes | Create a design-system contract (tokens + evidence + version) (Batch 11) |
| GET | `/api/design-systems` | Yes | List design-system contracts (Batch 11) |
| POST | `/api/design-systems/{id}/critique` | Yes | Measured prototype critique: contrast, hairline, shadow, type (Batch 11) |
| POST | `/api/design-systems/{id}/transform` | Yes | bolder/quieter/distill as parameterised token operations (Batch 11) |
| POST | `/api/media/graph/validate` | Yes | Node-graph validation: typed sockets, cycles, fixed registry (Batch 11) |
| POST | `/api/media/graph/run` | Yes | Node-graph execution through existing engines only (Batch 11) |
| POST | `/api/media/overlay` | Yes | Non-destructive SVG annotation overlay render (Batch 11) |
| POST | `/api/media/storyboard` | Yes | Scene plan -> still-image prompts; no video rendered (Batch 11) |
| POST | `/api/image/mask` | Yes | PNG mask in/out with edge feathering; server never invents a mask (Batch 11) |
| GET | `/api/connectors` | Yes | List OAuth connectors + status (Phase 5) |
| GET | `/api/connectors/{name}/authorize` | Yes | OAuth authorize URL (Phase 5) |
| GET | `/api/connectors/{name}/callback` | Yes | OAuth callback, token stored encrypted (Phase 5) |
| DELETE | `/api/connectors/{name}` | Yes | Disconnect an OAuth connector (Phase 5) |
| GET | `/api/system/backup` | Yes | Download backup zip (DB + uploads) (Phase 5) |
| GET | `/api/security/allowlist` | Yes | List target allowlist (Batch 2) |
| POST | `/api/security/allowlist` | Yes | Add allowlist target (Batch 2) |
| DELETE | `/api/security/allowlist/{target_id}` | Yes | Remove allowlist target (Batch 2) |
| GET | `/api/security/catalog` | Yes | Curated security tool catalog, data only (Batch 2) |
| POST | `/api/security/catalog/{name}/enable` | Yes | Enable/disable a catalog entry (Batch 2) |
| POST | `/api/security/runs` | Yes | Create a PENDING security run (Batch 2) |
| GET | `/api/security/runs` | Yes | List security runs (Batch 2) |
| GET | `/api/security/runs/{run_id}` | Yes | Get one security run (Batch 2) |
| POST | `/api/security/runs/{run_id}/approve` | Yes | Approve + execute a run (Batch 2) |
| POST | `/api/security/runs/{run_id}/phase` | Yes | Advance run phase Recon→Reporter (Batch 2) |
| POST | `/api/security/runs/{run_id}/browser` | Yes | Browser agent, automation/security-test modes (Batch 2) |
| GET | `/api/security/runs/{run_id}/audit` | Yes | Audit log for a run (Batch 2) |
| POST | `/api/security/runs/{run_id}/findings` | Yes | Add a finding (Batch 2) |
| GET | `/api/security/runs/{run_id}/findings` | Yes | List findings (Batch 2) |
| POST | `/api/security/findings/{finding_id}/validate` | Yes | Set validation verdict (Batch 2) |
| POST | `/api/security/runs/{run_id}/report` | Yes | Gated report (refuses unless findings PASS) (Batch 2) |
| GET | `/api/memory/export` | Yes | Export memories as JSON download (Phase 2) |
| POST | `/api/memory/forget` | Yes | Bulk forget memories by filter, confirm required (Phase 2) |
| GET | `/api/agents` | Yes | List custom agents (Phase 3) |
| POST | `/api/agents` | Yes | Create custom agent |
| GET | `/api/agents/{id}` | Yes | Get agent |
| PUT | `/api/agents/{id}` | Yes | Update agent |
| DELETE | `/api/agents/{id}` | Yes | Delete agent |
| POST | `/api/agents/{id}/run` | Yes | Run agent (SSE) |
| GET | `/api/teams` | Yes | List agent teams |
| POST | `/api/teams/run` | Yes | Run team (fan-out/fan-in) |
| POST | `/api/teams/run/stream` | Yes | Stream team run (SSE per specialist, Phase 6.4a) |
| POST | `/api/teams/retry-agent` | Yes | Retry single specialist |
| POST | `/api/teams/stop-agent` | Yes | Stop one specialist mid-stream |
| GET | `/api/runs` | Yes | Agent run history |
| POST | `/api/runs` | Yes | Record a completed agent run |
| GET | `/api/runs/live` | Yes | Live run plane (Phase 1 Runs centre) |
| GET | `/api/runs/{run_id}` | Yes | Run detail with steps |
| GET | `/api/artifacts` | Yes | List artifacts (Phase 4) |
| POST | `/api/artifacts` | Yes | Create artifact |
| GET | `/api/artifacts/{id}` | Yes | Get artifact |
| PUT | `/api/artifacts/{id}` | Yes | Update artifact (new version) |
| DELETE | `/api/artifacts/{id}` | Yes | Delete artifact |
| GET | `/api/artifacts/{id}/versions` | Yes | Version history |
| POST | `/api/artifacts/{id}/signed-url` | Yes | Signed download URL, 15 min (Phase 1) |
| GET | `/api/artifacts/download` | No | Signed-token download, no session (Phase 1) |
| POST | `/api/artifacts/retention/prune` | Yes | Delete stale artifacts, explicit only (Phase 1) |
| POST | `/api/spec/build` | Yes | Build spec from prompt (Phase 4) |
| POST | `/api/spec/to-task` | Yes | Convert spec to task |
| POST | `/api/quality/preview` | Yes | Preview quality cleanup diff |
| GET | `/api/automations` | Yes | List automations (Phase 5) |
| POST | `/api/automations` | Yes | Create automation |
| GET | `/api/automations/{id}` | Yes | Get automation |
| PUT | `/api/automations/{id}` | Yes | Update automation |
| DELETE | `/api/automations/{id}` | Yes | Delete automation |
| POST | `/api/automations/{id}/run` | Yes | Run now |
| POST | `/api/compare` | Yes | Parallel model comparison (Phase 6.4c) |
| POST | `/api/compare/stream` | Yes | Parallel model comparison (SSE) |
| POST | `/api/routing/evaluate` | Yes | Evaluate routing rules on a message |
| POST | `/api/arena/vote` | Yes | Record Arena vote |
| GET | `/api/arena/leaderboard` | Yes | Win rates by model |
| POST | `/api/voice/tts` | Yes | Text-to-speech |
| POST | `/api/voice/stt` | Yes | Speech-to-text |
| GET | `/api/voice/voices` | Yes | Available voices |
| GET | `/api/voice/status` | Yes | Voice engine status |
| POST | `/api/image/generate` | Yes | Generate image |
| GET | `/api/image/status` | Yes | Image engine status |
| POST | `/api/learn/lesson` | Yes | Generate lesson |
| POST | `/api/learn/feedback` | Yes | Tutor feedback |
| POST | `/api/learn/outline` | Yes | Generate lesson outline |
| POST | `/api/learn/quiz` | Yes | Generate lesson quiz |
| POST | `/api/learn/grade` | Yes | Grade quiz answers + feedback |
| GET | `/api/auth/status` | No | Registration open? |
| POST | `/api/auth/register` | No | Create account |
| POST | `/api/auth/login` | No | Sign in |
| POST | `/api/auth/forgot-password` | No | Request reset token |
| POST | `/api/auth/reset-password` | No | Reset with token |
| POST | `/api/auth/logout` | Yes | Sign out |
| GET | `/api/auth/me` | Yes | Current user |
| GET | `/api/skills/` | Yes | List skills |
| GET | `/api/skills/categories` | Yes | List categories |
| GET | `/api/skills/{id}` | Yes | Skill detail |
| POST | `/api/skills/execute` | Yes | Execute skill |
| POST | `/api/skills/chain` | Yes | Chain skills |
| POST | `/api/skills/auto-suggest` | Yes | Suggest skills |
| POST | `/api/skills/{id}/pin` | Yes | Pin a skill to a version |
| GET | `/api/skills/packs` | Yes | List skill packs |
| POST | `/api/skills/packs/{name}/enable` | Yes | Enable pack |
| POST | `/api/skills/packs/{name}/disable` | Yes | Disable pack |
| GET | `/api/skills/checks` | Yes | Repo-wide skill checks (frontmatter, links, parse, eval) |
| GET | `/api/skills/lock` | Yes | Skills lockfile verification status |
| GET | `/api/skills/config-audit` | Yes | Config audit: secret-looking keys in skill configs (values redacted) |
| GET | `/api/skills/{name}/checks` | Yes | Per-skill checks |
| POST | `/api/skills/install` | Yes | Hash-verified skill install + auto-scan |
| POST | `/api/skills/install/dry-run` | Yes | Install preview (files + hashes, writes nothing) |
| POST | `/api/skills/verify` | Yes | Recompute lockfile hashes (OK/MISMATCH per skill) |
| POST | `/api/skills/{name}/scan` | Yes | Server-side supply-chain / injection scan |
| POST | `/api/skills/{name}/run` | Yes | Approval-gated skill script execution (202 approval_needed first) |
| POST | `/api/skills/packs/{pack}/pin` | Yes | Pin a skill pack version (packs-lock.json) |
| DELETE | `/api/skills/packs/{pack}/pin` | Yes | Unpin a skill pack |
| POST | `/api/skills/recommend` | Yes | Stack-aware skill recommendations |
| POST | `/api/skills/documents/generate` | Yes | Generate docx/pdf/pptx/xlsx (file download) |
| POST | `/api/engineering` | Yes | Create engineering pipeline |
| GET | `/api/engineering` | Yes | List engineering pipelines |
| GET | `/api/engineering/{id}` | Yes | Get engineering pipeline + stages |
| GET | `/api/engineering/{id}/stages` | Yes | List engineering pipeline stages |
| POST | `/api/engineering/{id}/advance` | Yes | Advance pipeline stage (422 on out-of-order / missing prerequisite) |
| GET | `/api/extensions` | Yes | List extensions |
| POST | `/api/extensions/{name}/enable` | Yes | Enable extension |
| POST | `/api/extensions/{name}/disable` | Yes | Disable extension |
| GET | `/api/features` | Yes | List feature flags |
| POST | `/api/features/{name}` | Yes | Toggle feature |
| POST | `/api/devices/pairing/start` | Yes | Start a LAN pairing (LAN_ENABLED must be on; 10 per 15 min per host) (Batch 6) |
| GET | `/api/devices/pairing` | Yes | List pairings for the host, incl. codes (Batch 6) |
| GET | `/api/devices/pairing/{pairing_id}` | Yes | Pairing status: pending/approved/denied/expired/claimed (Batch 6) |
| POST | `/api/devices/pairing/{pairing_id}/approve` | Yes | Approve a pending pairing (Batch 6) |
| POST | `/api/devices/pairing/{pairing_id}/deny` | Yes | Deny a pending pairing (Batch 6) |
| POST | `/api/devices/pairing/claim` | **No** | Claim an approved pairing with its code -> device token, exactly once; rate-limited (Batch 6) |
| GET | `/api/devices` | Yes | List paired devices (never token hashes or raw tokens) (Batch 6) |
| DELETE | `/api/devices/{device_id}` | Yes | Revoke one paired device (Batch 6) |
| POST | `/api/devices/revoke-all` | Yes | Revoke all paired devices (Batch 6) |
| GET | `/api/devices/lan` | Yes | Host LAN IPv4 addresses + binding hints (Batch 6) |
| GET | `/api/devices/cert` | Yes | LAN certificate fingerprint / existence (Batch 6) |
| POST | `/api/devices/cert/regenerate` | Yes | New self-signed cert; revokes all devices + expires pending pairings (Batch 6) |
| GET | `/api/models/hardware` | Yes | Host CPU/RAM/VRAM detection; VRAM unknown unless nvidia-smi answers (Batch 7) |
| GET | `/api/models/catalogue` | Yes | Built-in model catalogue estimates, embeddings marked non-runnable (Batch 7) |
| POST | `/api/models/recommend` | Yes | Ranked fit/speed/quality/context recommendations (Batch 7); Batch 13 adds shown per-use-case weights, weighted scores, bandwidth speed estimate, measured-benchmark override |
| POST | `/api/models/route` | Yes | OmniRoute-style strategy choice (priority / cost-optimized / headroom / quota-weighted / round-robin / fail-closed) with reasons + session pinning (Batch 13) |
| POST | `/api/models/benchmark` | Yes | Timed generation via provider stream; local-only unless allow_remote=true (Batch 7) |
| GET | `/api/models/benchmarks` | Yes | Stored benchmark results, newest first (Batch 7) |
| POST | `/api/models/ollama/pull` | Yes | Start an Ollama pull (202 + poll id) (Batch 7) |
| GET | `/api/models/ollama/pulls/{pull_id}` | Yes | Poll an Ollama pull (Batch 7) |
| DELETE | `/api/models/ollama/{model}` | Yes | Delete an Ollama model (Batch 7) |
| POST | `/api/quality/lint` | Yes | Offline deterministic grammar/spell/repetition lint, candidate issues only (Batch 7) |
| GET | `/api/quality/adhd-style` | Yes | Prompt-level ADHD style block; wired into chat behind adhdFriendly (Deep-read Wave-1) |
| POST | `/api/quality/check` | Yes | Ponytail-shaped ranked findings (must-fix first, fix + if-skipped, not-checked footer); detect-only (Batch 13) |
| POST | `/api/quality/humanize` | Yes | Natural rewrite for readability only; states it does not evade AI detectors (Batch 13) |
| POST | `/api/quality/report` | Yes | Per-message quality report: readability, slop, structure, lint count, ADHD pre-send check (Batch 13) |
| GET | `/api/diagrams/catalogue` | Yes | Editorial diagram templates (13 types) (Batch 7) |
| POST | `/api/diagrams/lint` | Yes | Statically checkable style-guide issues only (Batch 7) |
| GET | `/api/diagrams/brands` | Yes | Saved brand profiles (Batch 7) |
| POST | `/api/diagrams/brands` | Yes | Create a brand profile (Batch 7) |
| POST | `/api/diagrams/brands/apply` | Yes | Substitute a brand into a template (Batch 7) |
| POST | `/api/diagrams/import` | Yes | Best-effort mermaid/drawio/excalidraw import to Mermaid (Batch 7) |
| POST | `/api/image/vary` | Yes | Vary an image via engine variations (422 if unsupported) (Batch 7) |
| POST | `/api/image/upscale` | Yes | Upscale; engine or labelled Pillow local resize (Batch 7) |
| POST | `/api/image/inpaint` | Yes | Inpaint with a mask via engine edits (422 if unsupported) (Batch 7) |
| POST | `/api/image/outpaint` | Yes | Outpaint with a border mask via engine edits (422 if unsupported) (Batch 7) |
| POST | `/api/image/image-prompt` | Yes | Image-prompt (img2img) via engine edits (422 if unsupported) (Batch 7) |
| POST | `/api/image/describe` | Yes | Describe an image via a vision chat model; 503 with no model (Batch 7) |
| GET | `/api/code-graph/find-code` | Yes | Graft-style code search, lexical + PageRank re-rank (Deep-read Wave-2) |
| GET | `/api/code-graph/file-api` | Yes | File-scoped code API (Deep-read Wave-2) |
| GET | `/api/code-graph/find-all` | Yes | Find all symbols matching a pattern (Deep-read Wave-2) |
| GET | `/api/code-graph/repo-map` | Yes | Repository map: clusters/hubs/hotspots (Deep-read Wave-2) |
| GET | `/api/code-graph/trace` | Yes | Trace calls in/out/both for a symbol (Deep-read Wave-2) |
| GET | `/api/code-graph/affected` | Yes | Blast radius for a symbol (Deep-read Wave-2); Batch 13 adds an evidence block (sources + limitations) |
| GET | `/api/code-graph/impact` | Yes | Cross-file impact analysis: callers, files touched, risk note, evidence (Batch 13) |
| GET | `/api/code-graph/orphans` | Yes | Dead-code candidates (no caller, not exported, not main); candidates only, nothing deleted (Batch 13) |
| POST | `/api/code-graph/explain-change` | Yes | Explain a unified diff via the graph: files, symbols, per-symbol impact (Batch 13) |
| GET | `/api/code-graph/export` | Yes | Graph export, JSON or standalone HTML (Deep-read Wave-2) |
| GET | `/api/code-graph/diagram` | Yes | Architecture diagram IR generated from the code graph (Deep-read Wave-2) |
| GET | `/api/knowledge/graph/check` | Yes | Fingerprint drift vs the cached code graph (Deep-read Wave-2) |
| GET | `/api/devices/discovery` | Yes | mDNS LAN discovery; 403 unless LAN_ENABLED (Deep-read Wave-2) |
| GET | `/api/system/doctor` | Yes | System health report with fix hints, never 500s (Deep-read Wave-2) |
| GET | `/api/engineering/{spec_id}/chain` | Yes | Spec-kit chain state for a spec (Deep-read Wave-2) |
| POST | `/api/engineering/{spec_id}/chain/advance` | Yes | Advance the spec-kit chain stage (Deep-read Wave-2) |
| POST | `/api/engineering/{spec_id}/chain/finish` | Yes | Finish chain; gated on package-referencing review verdicts (Deep-read Wave-2) |
| POST | `/api/engineering/{spec_id}/chain/review-package` | Yes | Build a BASE/HEAD diff review package; 422 on empty diff (Deep-read Wave-2) |
| POST | `/api/engineering/{spec_id}/chain/review/{axis}` | Yes | Spec or quality review over a review package (Deep-read Wave-2) |
| POST | `/api/engineering/{spec_id}/chain/review/{axis}/fix` | Yes | Fix loop, 5-round cap, fresh context on rounds 4-5 (Deep-read Wave-2) |
| POST | `/api/engineering/{spec_id}/chain/tasks/{task_id}/run` | Yes | Real per-task agent run + test ledger row (Deep-read Wave-2) |
| GET | `/api/goals` | Yes | Goals with task counts (Deep-read Wave-2) |
| POST | `/api/goals` | Yes | Create a goal (tree via parent_id) (Deep-read Wave-2) |
| GET | `/api/goals/{goal_id}` | Yes | Goal tree: subgoals + tasks (Deep-read Wave-2) |
| PATCH | `/api/goals/{goal_id}` | Yes | Update goal title/description/status (Deep-read Wave-2) |
| GET | `/api/goals/{goal_id}/tasks` | Yes | Tasks of a goal (Deep-read Wave-2) |
| POST | `/api/goals/{goal_id}/tasks` | Yes | Create a task under a goal (Deep-read Wave-2) |
| GET | `/api/tasks` | Yes | Open tasks (or all with ?open=false) (Deep-read Wave-2) |
| GET | `/api/tasks/{task_id}` | Yes | One task (Deep-read Wave-2) |
| PATCH | `/api/tasks/{task_id}` | Yes | Update task status/priority/work_ref/assignee (Deep-read Wave-2) |
| POST | `/api/knowledge/crawl` | Yes | BFS deep crawl; requires approved:true, RunStore-mirrored (Deep-read Wave-2) |
| GET | `/api/knowledge/crawls/{crawl_id}` | Yes | Deep-crawl job status/pages (Deep-read Wave-2) |
| GET | `/api/notebooks/{notebook_id}/insights` | Yes | Notebook insight rows (Deep-read Wave-2) |
| POST | `/api/notebooks/{notebook_id}/insights/{insight_id}/save-as-note` | Yes | Promote an insight row to a note (Deep-read Wave-2) |
| GET | `/api/notebooks/{notebook_id}/saved-transforms` | Yes | Saved prompt transformations (Deep-read Wave-2) |
| POST | `/api/notebooks/{notebook_id}/saved-transforms` | Yes | Save a prompt transformation (Deep-read Wave-2) |
| POST | `/api/lessons/from-outline` | Yes | Lesson dict from an outline (Deep-read Wave-2) |
| POST | `/api/lessons/player` | Yes | Create a lesson player session (Deep-read Wave-2) |
| GET | `/api/lessons/player/{player_id}` | Yes | Lesson player snapshot (Deep-read Wave-2) |
| POST | `/api/lessons/player/{player_id}/start` | Yes | Start lesson playback (Deep-read Wave-2) |
| POST | `/api/lessons/player/{player_id}/pause` | Yes | Pause lesson playback (Deep-read Wave-2) |
| POST | `/api/lessons/player/{player_id}/resume` | Yes | Resume lesson playback at the same scene (Deep-read Wave-2) |
| POST | `/api/lessons/player/{player_id}/play-step` | Yes | Advance one lesson action (Deep-read Wave-2) |
| POST | `/api/lessons/player/{player_id}/interrupt` | Yes | Interrupt with a learner question (Deep-read Wave-2) |
| POST | `/api/lessons/player/{player_id}/end-discussion` | Yes | End discussion, return to paused cursor (Deep-read Wave-2) |
| POST | `/api/lessons/player/{player_id}/answer` | Yes | Answer a lesson question action (Deep-read Wave-2) |
| POST | `/api/skills/creator/draft` | Yes | Draft a contract-format skill (Deep-read Wave-2) |
| POST | `/api/skills/creator/evaluate` | Yes | Skill-creator eval loop: test prompts, evaluate, rewrite (Deep-read Wave-2) |
| POST | `/api/skills/creator/publish` | Yes | Publish a skill; refuses unless eval passed + checks pass (Deep-read Wave-2) |
| POST | `/api/skills/import/preview` | Yes | Dry-run curated import: hashes + scan, writes nothing (Deep-read Wave-2) |
| POST | `/api/skills/import/install` | Yes | Explicit per-skill install from a preview; hash-drift refused (Deep-read Wave-2) |
| GET | `/api/skills/personas` | Yes | File-based persona registry listing (Deep-read Wave-2) |
| GET | `/api/skills/personas/suggest` | Yes | Task-based persona suggestions (Deep-read Wave-2) |
| GET | `/api/skills/personas/validate` | Yes | Roster validation report (Deep-read Wave-2) |
| POST | `/api/teams/council/deliberate` | Yes | Council Deliberate mode; splits returned, never manufactured consensus (Deep-read Wave-2); Batch 13 adds panel/profile/manual members, domain-seat locking, Chairman synthesis, enforcement re-prompts, session metadata, verdict-specific kill criteria |
| POST | `/api/teams/debate/scenarios` | Yes | Scenario branches: same debate under 1-3 injected variables, stated as assumptions (Batch 13) |
| GET | `/api/teams/debate/jobs/{job_id}/report` | Yes | Closing report for a finished debate: position ledger, quoted disagreements, what would change it (Batch 13) |
| POST | `/api/teams/debate/estimate` | Yes | Debate cost estimate before start (Deep-read Wave-2) |
| POST | `/api/teams/debate/run` | Yes | Start a capped debate job (202 + poll id) (Deep-read Wave-2) |
| GET | `/api/teams/debate/jobs/{job_id}` | Yes | Debate job status/result (Deep-read Wave-2) |
| POST | `/api/teams/debate/jobs/{job_id}/stop` | Yes | Hard-stop a running debate job (Deep-read Wave-2) |
| GET | `/api/teams/hive/agents` | Yes | Hive agent registry (Deep-read Wave-2) |
| POST | `/api/teams/hive/agents` | Yes | Create a hive agent (Deep-read Wave-2) |
| POST | `/api/teams/hive/agents/{agent_id}/archive` | Yes | Archive a hive agent (Deep-read Wave-2) |
| GET | `/api/teams/hive/agents/{agent_id}/inbox` | Yes | Hive agent inbox (Deep-read Wave-2) |
| GET | `/api/teams/hive/agents/{agent_id}/outbox` | Yes | Hive agent outbox (Deep-read Wave-2) |
| POST | `/api/teams/hive/messages` | Yes | Send a hive message (routed, bounce-never-drop) (Deep-read Wave-2) |
| POST | `/api/teams/hive/route` | Yes | Route queued hive messages (Deep-read Wave-2) |
| POST | `/api/teams/hive/closing` | Yes | Closing-time broadcast (Deep-read Wave-2) |
| GET | `/api/teams/hive/closing/acks` | Yes | Collect closing-time ACKs (Deep-read Wave-2) |
| POST | `/api/teams/hive/breaker/beat` | Yes | Server-side breaker tick (state in hive/breaker.json) (Deep-read Wave-2) |
| GET | `/api/teams/hooks/queue` | Yes | External-agent approval queue: pending + head (Deep-read Wave-2) |
| POST | `/api/teams/hooks/queue/decide` | Yes | Decide the head approval only; stale clicks refused (Deep-read Wave-2) |
| POST | `/api/teams/hooks/phone/issue` | Yes | Issue a one-decision phone approval token (Deep-read Wave-2) |
| POST | `/api/teams/hooks/phone/consume` | Yes | Consume a phone token and apply its decision (Deep-read Wave-2) |
| GET | `/api/teams/worktrees` | Yes | List git worktrees for a repo (Deep-read Wave-2) |
| POST | `/api/teams/worktrees` | Yes | Create a git worktree (Deep-read Wave-2) |
| POST | `/api/teams/worktrees/remove` | Yes | Remove a git worktree (Deep-read Wave-2) |
| POST | `/api/teams/worktrees/run` | Yes | Run an argv command inside a worktree (Deep-read Wave-2) |
| POST | `/api/teams/worktrees/annotate` | Yes | Validate diff-line review comments against a diff (Deep-read Wave-2) |
| GET | `/api/knowledge/catalogue` | Yes | Curated MCP-server + LLM-pattern catalogue (Batch 9) |
| POST | `/api/knowledge/packs` | Yes | Repomix-style workspace pack (Batch 9) |
| POST | `/api/knowledge/code-map/refresh` | Yes | Refresh code memory if stale (Batch 9) |
| POST | `/api/knowledge/code-map/change-impact` | Yes | Callers + tests + layers for a symbol (Batch 9) |
| POST | `/api/knowledge/code-map/analysis` | Yes | Code-map analysis incl. hubs + surprising links (Batch 9) |
| GET | `/api/memory/observations` | Yes | Observation ledger list (Batch 9) |
| GET | `/api/memory/observations-context` | Yes | Top observations as a chat context block (Batch 9) |
| POST | `/api/memory/observations` | Yes | Mint an observation (defense-checked) (Batch 9) |
| GET | `/api/memory/observations/{id}` | Yes | One observation (Batch 9) |
| POST | `/api/memory/observations/{id}/refine` | Yes | Strengthen/weaken an observation (Batch 9) |
| POST | `/api/memory/observations/{id}/supersede` | Yes | Supersede an observation (Batch 9) |
| POST | `/api/memory/ops/preview` | Yes | mem0-style ops preview, never writes (Batch 9) |
| POST | `/api/memory/ops/apply` | Yes | Apply previewed ops (confirm + known ids only) (Batch 9) |
| GET | `/api/memory/notes` | Yes | Browsable Markdown memory notes (Batch 9) |
| POST | `/api/memory/notes` | Yes | Write a dated, typed Markdown memory note (Batch 9) |
| GET | `/api/memory/notes/{id}` | Yes | One Markdown memory note (Batch 9) |
| POST | `/api/memory/notes/normalize` | Yes | Merge duplicate Markdown notes, with report (Batch 9) |
| POST | `/api/research/jobs` | Yes | Create a deep-research job (Batch 9) |
| GET | `/api/research/jobs/{id}` | Yes | Research job state (Batch 9) |
| POST | `/api/research/jobs/{id}/run` | Yes | Run a research job (Batch 9) |
| POST | `/api/research/jobs/{id}/report` | Yes | Cited report (422 on uncited claims) (Batch 9) |
| POST | `/api/research/jobs/{id}/slides` | Yes | Guarded slide/lesson outline from the report (Batch 9) |
| GET | `/api/research/jobs/{id}/source-graph` | Yes | Source graph over the job's own sources (Batch 9) |
| GET | `/api/notebooks/{id}/timeline` | Yes | Notebook source timeline (Batch 9) |
| POST | `/api/notebooks/{id}/deep-research` | Yes | Notebook-scoped deep-research job (Batch 9) |
| POST | `/api/agent/runtime/plan` | Yes | Tool-call dependency planning (Batch 10) |
| POST | `/api/agent/runtime/contract` | Yes | Freeze a per-turn tool contract (Batch 10) |
| POST | `/api/agent/runtime/contract/check` | Yes | Check one tool against a contract (Batch 10) |
| POST | `/api/agent/runtime/compact` | Yes | Structured compaction + branch save (Batch 10) |
| GET | `/api/agent/runtime/branches` | Yes | List compaction branches (Batch 10) |
| POST | `/api/agent/runtime/branches/{id}/resume` | Yes | Resume a branch as a child branch (Batch 10) |
| POST | `/api/agent/runtime/runs/{id}/steer` | Yes | Inject a steering message mid-run (Batch 10) |
| POST | `/api/agent/runtime/runs/{id}/abort` | Yes | Abort a run at the next step boundary (Batch 10) |
| GET | `/api/agent/runtime/runs/{id}/steering` | Yes | Queued steering + abort state (Batch 10) |
| POST | `/api/agent/runtime/approvals/defer` | Yes | Defer a risky call to the tray (Batch 10) |
| GET | `/api/agent/runtime/approvals/tray` | Yes | The "Needs you" approval tray (Batch 10) |
| POST | `/api/agent/runtime/approvals/{id}/decide` | Yes | Decide a deferred approval, exactly once (Batch 10) |
| POST | `/api/agent/runtime/sandbox` | Yes | Per-run sandbox preview / create (confirm) (Batch 10) |
| POST | `/api/agent/runtime/sandbox/verify` | Yes | Verify gate preview / run (confirm) (Batch 10) |
| POST | `/api/agent/runtime/flow` | Yes | Ticket graph: order + frontier + branch review (Batch 10) |
| POST | `/api/agent/runtime/hive/drain` | Yes | Inbox drain + critical-only escalation (Batch 10) |
| GET | `/api/agent/runtime/drivers` | Yes | Supervised external runtimes, detection only (Batch 10) |
| GET | `/api/agent/runtime/drivers/{name}/detect` | Yes | Detect one external runtime binary (Batch 10) |
| POST | `/api/agent/runtime/eval/propose` | Yes | Propose a change from an eval delta, never apply (Batch 10) |
| POST | `/api/skills/propose-from-transcript` | Yes | Draft a skill from a chat transcript (Batch 10) |
| POST | `/api/skills/propose-from-runs` | Yes | Draft skills from run-history clusters (Batch 10) |
| POST | `/api/skills/drafts/save` | Yes | Save a user-reviewed skill draft (not installed) (Batch 10) |
| GET | `/api/skills/{name}/trigger-eval` | Yes | Trigger-accuracy eval for a skill (Batch 10) |
| POST | `/api/skills/{name}/eval-blind` | Yes | Blind A/B gate scored from supplied outputs (Batch 10) |
| POST | `/api/skills/{name}/bootstrap` | Yes | Approval-gated bootstrap skill body (Batch 10) |

| GET | `/api/devqa/node-catalogue` | Yes | Typed workflow node catalogue (Batch 12) |
| GET | `/api/devqa/workflow-templates` | Yes | Dify-style starter graphs: chatbot / agent / workflow (Batch 12) |
| GET | `/api/devqa/workflow-templates/{name}` | Yes | One starter graph (Batch 12) |
| POST | `/api/devqa/workflows/validate` | Yes | Strict workflow validation incl. variable-pool scoping (Batch 12) |
| POST | `/api/devqa/workflows/{workflow_id}/runs/{run_id}/resume` | Yes | Resume an awaiting_input run, exactly once (Batch 12) |
| POST | `/api/devqa/spec/constitution/check` | Yes | Spec-kit constitution gate (keyword-overlap heuristic) (Batch 12) |
| POST | `/api/devqa/spec/mvp-order` | Yes | P1-only MVP task order with dependency checks (Batch 12) |
| POST | `/api/devqa/crawl/order` | Yes | Crawl frontier order: bfs / dfs / best_first (Batch 12) |
| POST | `/api/devqa/crawl/filter` | Yes | Crawl FilterChain: content_type / domain / keyword (Batch 12) |
| POST | `/api/devqa/crawl/chunk` | Yes | Markdown chunking: paragraph / heading / fixed (Batch 12) |
| POST | `/api/devqa/crawl/link-graph` | Yes | Link graph over crawled pages (Batch 12) |
| POST | `/api/devqa/security/scope/validate` | Yes | Validate a scope file (domains / CIDRs / excluded) (Batch 12) |
| POST | `/api/devqa/security/scope/check` | Yes | Hard scope check for a target (Batch 12) |
| POST | `/api/devqa/security/findings/dedup` | Yes | Finding dedup by fingerprint (Batch 12) |
| POST | `/api/devqa/security/findings/cvss-guard` | Yes | CVSS score + version guard before validation (Batch 12) |
| POST | `/api/devqa/security/coverage` | Yes | Coverage ledger: probed vs discovered (Batch 12) |
| POST | `/api/devqa/security/gates` | Yes | Sandbox pre-flight gates, failing closed (Batch 12) |
| GET | `/api/devqa/security/checklist/{phase}` | Yes | Guided security phase checklist (Batch 12) |
| POST | `/api/devqa/security/categories/reject` | Yes | Excluded-category import rejection, wholesale (Batch 12) |
| POST | `/api/devqa/security/tools/availability` | Yes | Tool availability probing, never installs (Batch 12) |
| POST | `/api/devqa/qa/cassette-to-test` | Yes | Generate a pytest case from a cassette, review-only (Batch 12) |
| POST | `/api/devqa/qa/replay-diff` | Yes | Replay diff with noise stripping (Batch 12) |
| POST | `/api/devqa/qa/js-lint` | Yes | JS best-practices lint findings, never rewrites (Batch 12) |
| POST | `/api/devqa/qa/suite-report` | Yes | Suite report; quarantined passes are not green (Batch 12) |
| GET | `/api/devqa/qa/test-tags` | Yes | Test tags: cold / live / quarantined (Batch 12) |
| GET | `/api/devqa/platform/health-actions` | Yes | Sangam-side health action catalogue with risk + undo (Batch 12) |
| POST | `/api/devqa/platform/services` | Yes | Register a local service URL for health checks (Batch 12) |
| GET | `/api/devqa/platform/services` | Yes | List registered services (Batch 12) |
| POST | `/api/devqa/platform/services/{service_id}/check` | Yes | Probe a service now, record in uptime history (Batch 12) |
| GET | `/api/devqa/platform/services/{service_id}/uptime` | Yes | Uptime summary (unknown until checks exist) (Batch 12) |
| POST | `/api/devqa/platform/notifications/webhook` | Yes | Gotify-shaped webhook-in (secret-gated inbox) (Batch 12) |
| GET | `/api/devqa/platform/notifications` | Yes | In-app notification inbox (Batch 12) |
| POST | `/api/devqa/platform/notifications/{note_id}/read` | Yes | Mark a notification read (Batch 12) |
| GET | `/api/devqa/platform/vm-profiles` | Yes | Quickemu-style VM profiles, documented configs only (Batch 12) |
| GET | `/api/devqa/platform/winutil-catalog` | Yes | Winutil safe half: read-only checks + documented tweaks (Batch 12) |
| POST | `/api/devqa/platform/analytics/event` | Yes | Taxonomy-validated analytics event (Batch 12) |
| POST | `/api/devqa/platform/analytics/funnel` | Yes | Simple session funnel over supplied events (Batch 12) |
| GET | `/api/devqa/chat/prompt-templates` | Yes | Prompt template library (Batch 12) |
| POST | `/api/devqa/chat/folders` | Yes | Create a chat folder (Batch 12) |
| GET | `/api/devqa/chat/folders` | Yes | List chat folders (Batch 12) |
| POST | `/api/devqa/chat/folders/{folder_id}/chats` | Yes | Add a chat to a folder (Batch 12) |
| POST | `/api/devqa/chat/presets/share` | Yes | Share a model preset (settings only, never keys/history) (Batch 12) |
| GET | `/api/devqa/chat/presets` | Yes | List model presets (Batch 12) |

### 13.3 Database Schema

┌───────────────────┐       ┌───────────────────┐
│       users       │       │   auth_sessions   │
├───────────────────┤       ├───────────────────┤
│ id (PK)           │──┐    │ id (PK)           │
│ username (unique) │  └───>│ user_id (FK)      │
│ password_salt     │       │ token_hash (uniq) │
│ password_hash     │       │ expires_at (idx)  │
│ created_at        │       │ created_at        │
└───────────────────┘       └───────────────────┘

┌────────────────────────────┐
│  password_reset_tokens     │
├────────────────────────────┤
│ id (PK)                    │
│ user_id (FK)               │
│ token_hash (idx)           │
│ used (single-use flag)     │
│ expires_at (idx, 30 min)   │
│ created_at                 │
└────────────────────────────┘

┌──────────────────────┐       ┌────────────────────────┐
│       chats          │       │     messages           │
├──────────────────────┤       ├────────────────────────┤
│ id (PK)              │──┐    │ id (PK)                │
│ title                │  └───>│ chat_id (FK)           │
│ model                │       │ role                   │
│ summary (rolling)    │       │ content (TEXT)         │
│ key_topics           │       │ model                  │
│ summarized_at        │       │ file_ids (comma-sep)   │
│ created_at           │       │ response_time          │
│ updated_at           │       │ feedback (up|down)     │
└──────────────────────┘       │ feedback_note          │
                               │ created_at             │
┌───────────────────┐          └────────────────────────┘
│   uploaded_files  │
├───────────────────┤       ┌───────────────────┐
│ id (PK)           │       │  provider_keys    │
│ filename          │       ├───────────────────┤
│ stored_path       │       │ provider_id (PK)  │
│ extension         │       │ api_key_encrypted │
│ size_bytes        │       │   (LargeBinary)   │
│ extracted_text    │       │ updated_at        │
│ created_at        │       └───────────────────┘
└───────────────────┘

┌───────────────────────────────┐
│      user_preferences         │
├───────────────────────────────┤
│ user_id (PK, FK → users)      │
│ response_style (concise|      │
│   balanced|detailed)          │
│ formality (casual|neutral|    │
│   formal)                     │
│ expertise_level (beginner|    │
│   general|expert)             │
│ settings_json (TEXT)          │  ← Phase 2: typed settings
│ updated_at                    │
└───────────────────────────────┘

┌───────────────────┐       ┌───────────────────┐
│   custom_agents   │       │    agent_runs     │
├───────────────────┤       ├───────────────────┤
│ id (PK)           │       │ id (PK)           │
│ user_id (FK)      │       │ user_id (FK)      │
│ name              │       │ agent_id (FK)     │
│ system_prompt     │       │ status            │
│ tools_json        │       │ created_at        │
│ created_at        │       └───────────────────┘
└───────────────────┘          ↑ Phase 3: Agent Hub

┌───────────────────┐       ┌───────────────────┐
│    artifacts      │       │ artifact_versions │
├───────────────────┤       ├───────────────────┤
│ id (PK)           │──┐    │ id (PK)           │
│ user_id (FK)      │  └──>│ artifact_id (FK)  │
│ title             │       │ version           │
│ type              │       │ content           │
│ content           │       │ created_at        │
│ created_at        │       └───────────────────┘
└───────────────────┘          ↑ Phase 4: Create Hub

┌───────────────────┐       ┌───────────────────┐
│   automations     │       │  arena_results    │
├───────────────────┤       ├───────────────────┤
│ id (PK)           │       │ id (PK)           │
│ user_id (FK)      │       │ user_id (FK)      │
│ name              │       │ prompt            │
│ trigger           │       │ winner_model      │
│ action            │       │ loser_model       │
│ config_json       │       │ models_compared   │
│ enabled           │       │ created_at        │
│ last_run          │       └───────────────────┘
│ next_run          │          ↑ Phase 6: Arena
│ created_at        │
└───────────────────┘
   ↑ Phase 5: Automations
```

### 13.4 Startup Sequence

The `start.py` launcher:
1. **Ensure virtual environment** — creates `venv/` if missing
2. **Install dependencies** — `pip install -r requirements.txt` (with SHA-256 caching)
3. **Bootstrap `.env`** — creates `.env` from `.env.example` if missing and fills in a valid `MASTER_KEY` when the value is blank
4. **Free stale ports** — kills any process holding port 8001 or 5500
5. **Start frontend first** — `python -m http.server 5500` serving `mainfiles/frontend/` (started before the backend so the backend's stdout pipe is not inherited)
6. **Start backend** — `uvicorn backend.main:app --host 127.0.0.1 --port 8001` with `mainfiles/` on `PYTHONPATH`, stdout piped through the launcher
7. **Monitor** — watches both processes; terminates both on Ctrl+C

This bootstrap behavior is intentional: first-time setup is friction-free, and the generated `MASTER_KEY` is required to encrypt provider API keys safely at rest.

### 13.5 Ports

| Service | URL | Description |
|---------|-----|-------------|
| Frontend | http://127.0.0.1:5500 | Chat interface |
| Backend API | http://127.0.0.1:8001 | REST API |
| API Docs | http://127.0.0.1:8001/docs | Swagger UI |
| Ollama | http://localhost:11434 | Local LLM runtime (if installed) |

---

## Data Flow Diagram (Complete)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           FRONTEND (port 5500)                          │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  app.js → nav.js (intent rail) → state.js (signals)                │   │
│  │  ┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌──────────┐  │   │
│  │  │ Chat     ││ Agents   ││Knowledge ││ Create   ││ Learn    │  │   │
│  │  │ (pinned) ││ Hub+Teams││ Graph    ││ Hub      ││ Mode     │  │   │
│  │  └──────────┘└──────────┘└──────────┘└──────────┘└──────────┘  │   │
│  │  ┌──────────┐┌──────────┐┌──────────┐┌──────────────────┐     │   │
│  │  │ Code     ││ Library  ││ Insights ││ Automations etc. │     │   │
│  │  │ Agent    ││ (skills) ││          ││                    │     │   │
│  │  └──────────┘└──────────┘└──────────┘└──────────────────┘     │   │
│  │  tabs/ (mount-once) │ inspector/ │ tray/ (jobs)                │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                            │                                            │
│              apiFetch() / streamChatCompletion() / parseSSE()            │
│                            │                                            │
└────────────────────────────┼───────────────────────────────────────────┘
                             │
┌────────────────────────────┼───────────────────────────────────────────┐
│                    BACKEND (port 8001)                                  │
│                            │                                            │
│  ┌─────────────────────────┴─────────────────────────────────────────┐ │
│  │  main.py — FastAPI app + CORS + lifespan                          │ │
│  │  ├── /api/auth/* — auth.py (register, login, logout, session)     │ │
│  │  ├── /api/* — handlers in api_routes/                          │ │
│  │  └── /api/skills/* — skills/api_skills.py (skills CRUD + execute) │ │
│  └─────────────────────────┬─────────────────────────────────────────┘ │
│                            │                                            │
│  ┌─────────────────────────┴─────────────────────────────────────────┐ │
│  │  LLM Layer (llm.py)                                               │ │
│  │  ├── list_models() → live API fetch + curated fallback            │ │
│  │  ├── list_provider_status() → online/offline/needs_key per provider│ │
│  │  ├── stream_response_events() → provider adapters or LiteLLM     │ │
│  │  └── resolve_api_key() → DB keys (Fernet) or .env fallback       │ │
│  └─────────────────────────┬─────────────────────────────────────────┘ │
│                            │                                            │
│  ┌──────────┐  ┌──────────┴──────────┐  ┌───────────────────────────┐  │
│  │ SQLite   │  │ Document Extraction  │  │ Web Search                │  │
│  │(mainfiles│  │ (document.py)        │  │ (websearch.py)            │  │
│  │/history/ │  │ PDF  DOCX  XLSX     │  │ DuckDuckGo  Tavily  Brave │  │
│  │sangam.db)│  │ CSV  PPTX  Code     │  │                           │  │
│  └──────────┘  └─────────────────────┘  └───────────────────────────┘  │
│                            │                                            │
└────────────────────────────┼───────────────────────────────────────────┘
                             │
              ┌──────────────┴──────────────┐
              │                              │
       ┌────────┴────────┐          ┌─────────┴────────┐
       │  Ollama Server  │          │  Cloud Provider  │
       │  (localhost:    │          │  APIs            │
       │   11434)        │          │  (OpenAI,        │
       │  Local models   │          │   Anthropic,     │
       │                 │          │   Gemini, etc.)  │
       └─────────────────┘          └──────────────────┘
```
---

## 15. Recent Additions (Phase 6, 2026-10-09)

### Teams Streaming
- `backend/teams/streaming.py`: `stream_team_run()` yields SSE events per specialist
- `POST /api/teams/run/stream`: SSE endpoint with disconnect handling
- `POST /api/teams/retry-agent`: Retry single specialist

### Knowledge Graph Provenance
- Edges have `provenance`: EXTRACTED (from data), INFERRED (heuristic), AMBIGUOUS (uncertain)
- Memory wings: `wing:{kind}` hub nodes group memories by type
- `backend/graph_provenance.py`: `AnswerProvenance` tracks "used in this answer"

### Model Compare & Arena
- `POST /api/compare`: Parallel execution across 2-4 models
- `POST /api/arena/vote`, `GET /api/arena/leaderboard`: Win rate tracking
- `ArenaResult` model

### Provider Resilience
- `backend/providers/fallback_chain.py`: `FallbackChain` with circuit breakers + quotas
- `GET /api/providers/status`: Expose breaker states + quota usage

### Automations
- `backend/automations.py`: Scheduler (hourly/daily/weekly/cron)
- `Automation` model, `/api/automations` CRUD

### Frontend Module Validation
- `scripts/check_frontend_modules.mjs`: Validates ES module imports/exports via V8
- Run: `node --experimental-vm-modules scripts/check_frontend_modules.mjs`
- Catches bugs that `node --check` misses (e.g. wrong relative import paths)
