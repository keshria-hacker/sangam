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

---

## 1. Project Overview

**Sangam** is a privacy-first, universal AI chat platform that unifies multiple Large Language Models (LLMs) into a single interface. It connects to cloud provider APIs (OpenAI, Anthropic, Gemini, etc.) and local models (Ollama) simultaneously, allowing users to switch between providers mid-conversation.

**Core Philosophy:** One interface, any model. No lock-in, no simulated responses — every chat is a real API call to a real provider.

### Key Features
- Multi-provider chat with live model discovery
- Real-time streaming responses (Server-Sent Events)
- Document upload + text extraction (PDF, DOCX, XLSX, code, etc.)
- Web search augmentation (DuckDuckGo out of the box, Tavily/Brave optional)
- In-app API key management (no server restarts)
- Conversation history with bucketed date grouping
- Paper / Ink theme system (light / dark / system) — monochrome design tokens
- Extensible Skills system
- Local authentication (single-user, password-hashed)
- Ollama auto-detection (auto-starts `ollama serve` when the executable is on PATH)

---

## 2. Directory Structure

```
sangam/
├── .dockerignore               # Docker build exclusion rules
├── Dockerfile                  # Backend-only Docker build (builder + slim runtime)
├── Dockerfile.all              # Backend + frontend in one container (supervisord)
├── docker-compose.yml          # Backend + optional Redis/frontend services
├── docker-compose.all.yml      # Single-container deployment
├── mainfiles/                  # Application code
│   ├── backend/                # FastAPI Python backend
│   │   ├── main.py             # App entrypoint, lifespan, CORS, router mounts
│   │   ├── config.py           # Typed settings loaded from root .env via pydantic-settings
│   │   ├── database.py         # Async SQLAlchemy engine + session factory (SQLite)
│   │   ├── models.py           # SQLAlchemy ORM tables (Chat, Message, User, etc.)
│   │   ├── schemas.py          # Pydantic request/response validation models
│   │   ├── api.py              # API facade — mounts api_routes, keeps stable import surface
│   │   ├── api_routes/         # Route handlers split by resource
│   │   │   ├── common.py       # SSE framing + upload-content validation helpers
│   │   │   ├── providers_routes.py  # Provider keys, model refresh, websearch, health
│   │   │   ├── files_routes.py # Document upload
│   │   │   ├── chats_routes.py # Chat CRUD, preferences, summary, feedback
│   │   │   ├── models_routes.py# Model catalogue
│   │   │   └── chat_stream_routes.py # Chat streaming pipeline + agentic reasoning
│   │   ├── auth.py             # Local authentication (register, login, logout, sessions)
│   │   ├── llm.py              # Stable facade over the providers package
│   │   ├── security.py         # Fernet field encryption (MASTER_KEY) + CSRF tokens
│   │   ├── prompt_injection.py # Prompt-injection detection
│   │   ├── document.py         # File text extraction (PDF, DOCX, XLSX, CSV, PPTX, code, text)
│   │   ├── rag.py              # Document chunking + vector retrieval (RAG with ChromaDB)
│   │   ├── memory.py           # Cross-session conversation memory (ChromaDB)
│   │   ├── summarizer.py       # Rolling chat summarization
│   │   ├── context_manager.py  # Token budgeting + safe context truncation
│   │   ├── response_events.py  # Canonical response event protocol (SSE)
│   │   ├── response_intelligence/ # Adaptive guidance (classification, injection)
│   │   ├── response_postprocessor.py # Uncertainty hedging at persistence time
│   │   ├── capability_orchestration.py # Clarification gate + capability decisions
│   │   ├── websearch.py        # Web search (DuckDuckGo Lite / Tavily / Brave)
│   │   ├── ratelimit.py        # Rate limiting middleware
│   │   ├── ratelimit_redis.py  # Redis-backed rate limit store
│   │   ├── middleware/         # ASGI middleware (request ID, etc.)
│   │   ├── migrations/         # Alembic migration scripts
│   │   ├── providers/          # Provider adapters + registry
│   │   │   ├── __init__.py     # Provider registration, list_models, resolve_api_key
│   │   │   ├── base.py         # Abstract provider interface
│   │   │   ├── registry.py     # ProviderRegistry + model resolution
│   │   │   ├── model_discovery.py  # Live model fetch + curated fallback
│   │   │   ├── key_resolver.py # API key resolution (DB → env)
│   │   │   ├── ollama.py       # Native Ollama streaming
│   │   │   ├── openai_compatible.py# OpenAI-compatible provider adapter
│   │   │   ├── anthropic.py / gemini.py / nvidia.py
│   │   │   ├── litellm_fallback.py / compat.py / inaccessible.py
│   │   │   └── enhanced/       # Experimental multi-provider routing (NOT wired at runtime)
│   │   ├── skills/             # Extensible skills sub-system
│   │   │   ├── registry.py     # Skill catalog loaded from SKILL.md files
│   │   │   ├── models.py       # SkillExecution + UserSkillPreference ORM tables
│   │   │   ├── router.py       # Skill execution engine with dependency resolution
│   │   │   ├── executor.py     # Skill execution + model invocation
│   │   │   └── api_skills.py   # FastAPI routes for skills CRUD + execution
│   │   └── tools/              # Tool-calling infrastructure (schemas, registry, executor)
│   ├── frontend/               # Static frontend (served via Python http.server)
│   │   ├── index.html          # Single-page application HTML
│   │   ├── css/
│   │   │   └── style.css       # Complete design system + all component styles
│   │   ├── js/
│   │   │   ├── app.js          # Main application bootstrap & global listeners
│   │   │   ├── core/state.js   # Central signal-based reactive state store
│   │   │   ├── shared/         # Shared utilities
│   │   │   │   ├── constants.js    # DEFAULT_SETTINGS, CHAT_BUCKETS, provider colors
│   │   │   │   ├── http.js     # Authenticated fetch + SSE helpers
│   │   │   │   ├── markdown.js # Streaming markdown + highlight.js rendering
│   │   │   │   ├── toast.js    # Toast notifications
│   │   │   │   └── utils.js    # escapeHtml, formatDate, bucketFor, etc.
│   │   │   └── features/       # Feature modules (one per UI area)
│   │   │       ├── auth/auth.js                # Login/register/forgot password
│   │   │       ├── chat/chat.js                # Streaming, sending, composer events
│   │   │       ├── chat/message_view.js        # Message DOM construction + status widgets
│   │   │       ├── chat/response_controller.js # Canonical SSE event state machine
│   │   │       ├── chat/autoscroll.js          # Smart auto-scroll controller
│   │   │       ├── models/models.js            # Model selector, provider status
│   │   │       ├── settings/settings.js        # Theme, API keys, preferences
│   │   │       ├── skills/skills.js            # Skills modal browser & execution
│   │   │       └── sidebar/sidebar.js          # Chat history sidebar (bucketed by date)
│   │   └── assets/
│   │       └── logo.svg        # Sangam brand logo
│   ├── config/
│   │   ├── providers.yaml      # Reference provider registry (documentation only)
│   │   └── skills/             # Skill definitions (SKILL.md files)
│   ├── history/                # SQLite database storage (runtime, gitignored)
│   ├── uploads/                # Uploaded file storage (runtime, gitignored)
│   └── logs/                   # Rotating application logs (runtime, gitignored)
├── tests/                      # Single consolidated test tree (pytest)
│   ├── conftest.py             # Shared fixtures (app client, auth, domain objects)
│   ├── integration/            # API-level integration tests
│   ├── test_api.py             # Route handlers (all endpoints)
│   ├── test_auth.py            # Authentication (hashing, sessions, lockout, CSRF)
│   ├── test_clarification.py   # Clarification gate (streaming interception)
│   ├── test_memory.py          # Cross-session memory + chat summaries
│   ├── test_message_feedback.py# Per-message feedback endpoints
│   ├── test_policy_*.py        # Adaptive response policy layer
│   ├── test_preferences.py     # User response-style preferences
│   ├── test_document.py        # Document extraction + truncation
│   ├── test_llm.py             # Provider facade + discovery
│   ├── test_main.py            # App factory, lifespan, health, CSRF middleware
│   ├── test_models.py          # Model discovery + selection
│   ├── test_providers.py       # Provider registry + adapters
│   ├── test_rag.py             # Chunking + vector retrieval│   ├── test_websearch.py       # Web search parsers
│   └── ...                     # One file per domain
├── scripts/                    # Developer tooling
│   ├── quality.sh / quality.ps1# Lint + typecheck + test runner
│   ├── runtime_verify.py       # Provider tool-calling runtime verification
│   └── generate_master_key.py  # Fernet key generator
├── start.py                    # Launcher: venv, deps, env, then both servers
├── start.bat / start.sh        # One-command start (Windows / Unix)
├── .env                        # Environment configuration (user-created)
├── .env.example                # Configuration template
├── pyproject.toml              # Ruff/mypy/pytest/coverage configuration
├── requirements.txt            # Python dependencies
├── README.md                   # Project README
└── ARCHITECTURE.md             # This file
```

---

## 3. Backend Architecture

### 3.1 Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Web Framework | **FastAPI** (0.115) | Async REST API with auto-docs |
| ASGI Server | **Uvicorn** (0.34) | Production-grade Python ASGI server |
| Database | **SQLite + aiosqlite** | Local persistence, zero config |
| ORM | **SQLAlchemy 2.0** (async) | Type-safe database access |
| Validation | **Pydantic v2** | Request/response validation |
| LLM Client | **LiteLLM** (1.56) | Unified API for 100+ LLM providers |
| HTTP Client | **httpx** (0.27) | Async HTTP for model APIs + web search |

### 3.2 Application Lifespan (`main.py`)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "history").mkdir(parents=True, exist_ok=True)
    (BASE_DIR / "logs").mkdir(parents=True, exist_ok=True)
    await init_db()       # Create all SQLAlchemy tables
    logger.info("Application startup complete")
    yield
    _cleanup_ollama()             # stop auto-started Ollama, if any
    await close_rate_limit_store()  # close Redis, if configured
    logger.info("Application shutdown")
```

The lifespan handler runs on startup:
1. Creates the `uploads/`, `history/`, and `logs/` directories if missing
2. Runs `Base.metadata.create_all` to create all database tables

On shutdown it cleans up the auto-started Ollama process (if any) and closes
the Redis rate-limit store (if configured).

### 3.3 CORS Configuration

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,  # ["http://localhost:5500", "http://127.0.0.1:5500"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

The CORS middleware allows the frontend (running on port 5500) to call the backend (port 8001).

### 3.4 API Layering

Route handlers live in `mainfiles/backend/api_routes/`, split by resource:

| Module | Endpoints |
|--------|-----------|
| `common.py` | SSE framing helpers, upload MIME validation, shared routers |
| `providers_routes.py` | Provider key CRUD, live model refresh, websearch, `/health`, provider status |
| `files_routes.py` | Document upload (validation → storage → extraction → RAG index) |
| `chats_routes.py` | Chat CRUD, user preferences, rolling summary, message feedback |
| `models_routes.py` | Model catalogue (`/models`, `/models/{provider}`) |
| `chat_stream_routes.py` | The streaming pipeline (`/chat/stream`) + `/agentic-reasoning` |

`mainfiles/backend/api.py` is a thin **facade**: it imports the route modules
(which register their endpoints on the shared routers) and re-exports every
handler plus the shared module objects (`llm`, `websearch`, `settings`, ...).
`main.py` mounts `router`/`public_router` from `api.py`, and tests patch
`backend.api.llm.*` exactly as before — the route modules import the same
module objects, so a patch on either path affects both.

### 3.5 Router Mounting

```python
app.include_router(auth_router, prefix=settings.API_PREFIX)                    # /api/auth/*
app.include_router(api_router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])  # /api/*
app.include_router(skills_router, prefix=settings.API_PREFIX, dependencies=[Depends(get_current_user)])  # /api/skills/*
```

- **Auth routes** are unprotected (registration/login)
- **API routes** require a valid bearer token via `get_current_user` dependency
- **Skills routes** also require authentication

---

## 4. Frontend Architecture

### 4.1 Single-Page Application

The frontend is a vanilla JS SPA served as static files. There is no build step, no framework — just HTML, CSS, and JS loaded directly.

**Libraries (loaded from CDN):**
| Library | Version | Purpose |
|---------|---------|---------|
| Font Awesome | 6.5.1 | Icons (free tier) |
| Google Fonts | — | Sora (display), Inter (body), JetBrains Mono (code) |
| Highlight.js | 11.9.0 | Code syntax highlighting |
| Marked | 12.0.1 | Markdown → HTML rendering |

### 4.2 Layout Structure

```
┌──────────────────────────────────────────────────────┐
│ MOBILE TOPBAR (hidden on desktop)                    │
├──────────────┬───────────────────────────────────────┤
│              │  TOPBAR                                │
│  SIDEBAR     │  [Model selector] [Conn status] [...] │
│              ├───────────────────────────────────────┤
│  New chat    │                                        │
│  Search      │  CHAT AREA                             │
│              │  [Welcome screen / Messages]            │
│  Chat list   │  [Skeleton / Error state]              │
│  (bucketed   │                                        │
│   by date)   ├───────────────────────────────────────┤
│              │  COMPOSER                              │
│  Settings    │  [Attach] [Textarea] [Send]            │
│  Profile     │  [Temp] [Tokens] [Reasoning] [Web] [Ctrl+Enter]  │
└──────────────┴───────────────────────────────────────┘
```

### 4.3 Module Organization

The frontend now uses a **feature-based module structure** under `mainfiles/frontend/js/features/` — each feature owns its own DOM, state, and logic:

| Module | Responsibility |
|--------|----------------|
| `core/state.js` | Central signal store — `[get, set]` pairs for providers, models, chats, messages, selectedModel, temperature, maxTokens, reasoningEffort, webSearchEnabled, settings (persisted to `localStorage` as `sangam-settings`), etc. |
| `shared/constants.js` | `DEFAULT_SETTINGS`, `CHAT_BUCKETS`, provider color/label maps |
| `shared/http.js` | `apiFetch`, `apiPost`, `apiDelete`, `streamChat` — authenticated requests + SSE |
| `shared/markdown.js` | Streaming-safe markdown → HTML rendering (marked + highlight.js) |
| `shared/toast.js` | Toast notifications |
| `shared/utils.js` | `escapeHtml`, `formatDate`, `debounce`, etc. |
| `features/auth/auth.js` | Login, register, forgot password, session check |
| `features/chat/chat.js` | Streaming pipeline, send/regenerate, composer + file attachments |
| `features/chat/message_view.js` | Message DOM construction + in-stream status widgets (thinking phase, reasoning, tools, citations, artifacts) |
| `features/chat/response_controller.js` | Canonical SSE event state machine (sequence/ordering enforcement, buffering) |
| `features/chat/autoscroll.js` | Smart auto-scroll with hysteresis + "↓ Jump to latest" |
| `features/models/models.js` | Model selector dropdown, provider status badges, "no models" handling |
| `features/settings/settings.js` | Theme (Paper/Ink/system), font size, chat width, code theme, animations; provider key manager (add/remove keys) |
| `features/skills/skills.js` | Skills modal: search, category/invocation filters, detail panel, execution |
| `features/sidebar/sidebar.js` | Chat history list (bucketed by date), new chat, delete chat |

**Boot sequence (`app.js`):**
1. Initialize global state (`state.js`)
2. Load persisted settings from `localStorage` (`state.js` → `sangam-settings`, applied by `settings.js`)
3. Initialize feature modules in dependency order: auth → settings → sidebar → models → chat → skills
4. Call `initGlobalListeners()` for topbar controls (temperature, tokens, reasoning, web search, shortcuts)

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

Design tokens live directly in `mainfiles/frontend/css/style.css` (the `:root` / `[data-theme]` variable blocks).

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
 │                        │                                │                              │
 │                        │                                │  [Optional] Web search       │
 │                        │                                │  [Optional] File extraction  │
 │                        │                                │                              │
 │                        │                                │  If new chat:                │
 │                        │                                │    - Create Chat row in DB   │
 │                        │                                │  Persist user message in DB  │
 │                        │                                │                              │
 │                        │                                │  Call LLM provider           │
 │                        │                                │──────────────────────────────>│
 │                        │                                │                              │
 │                        │   SSE: event=chat_id           │    Stream tokens            │
 │                        │<───────────────────────────────│<──────────────────────────────│
 │                        │   SSE: data=<token>           │                              │
 │                        │<───────────────────────────────│                              │
 │                        │   SSE: data=<token>           │                              │
 │                        │<───────────────────────────────│                              │
 │                        │   ...                         │                              │
 │                        │   SSE: data=[DONE]            │                              │
 │                        │<───────────────────────────────│                              │
 │                        │                                │  Persist assistant message  │
 │                        │                                │                              │
 │  See streaming text    │                                │                              │
 │<───────────────────────│                                │                              │
```

### 5.2 SSE Event Protocol

The backend uses Server-Sent Events (text/event-stream) with a custom frame format:

```
event: chat_id
data: abc123def456

data: Hello, how can I

data:  help you today?

event: error
data: Provider API key not linked

data: [DONE]
```

**Event types:**
- `chat_id` (sent once): The database ID of the chat (useful when creating a new chat)
- `message` (default, no event line): Streaming token data
- `error`: Fatal error — streaming terminated
- `[DONE]` data: Signal that streaming completed successfully

### 5.3 SSE Parsing in Frontend

```javascript
let buffer = '';
while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let frameEnd;
    while ((frameEnd = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, frameEnd);
        buffer = buffer.slice(frameEnd + 2);
        // Parse event type and data from the frame
        // Handle: error, chat_id, [DONE], or regular token
    }
}
```

---

## 6. Authentication System

### 6.1 Design

Single-user, local-only authentication. No OAuth, no third-party identity providers. The first user to register creates the account; subsequent visitors are prompted to sign in.

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
- CSRF protection via double-submit cookie (`csrf_token` cookie + `X-CSRF-Token` header)

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
| Together AI | `together` | Cloud | Yes | (none) |
| Groq | `groq` | Cloud | Yes | (none) |
| OpenRouter | `openrouter` | Cloud | Yes | (none) |
| DeepSeek | `deepseek` | Cloud | Yes | `deepseek/` |
| Mistral | `mistral` | Cloud | Yes | (none) |
| Gemini | `gemini` | Cloud | Yes | `gemini/` |
| Ollama | `ollama` | Local | No | `ollama/` |

### 7.2 Model Discovery — Two-Tier System

**Tier 1: Live API Fetch** (`_fetch_provider_models`)

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
    "claude-sonnet-5":  ModelInfo(id="claude-sonnet-5",  name="Claude Sonnet 5",  provider="anthropic", litellm_id="anthropic/claude-sonnet-5"),
    "gpt-5":            ModelInfo(id="gpt-5",            name="GPT-5",            provider="openai",   litellm_id="openai/gpt-5"),
    "nim-llama-3-70b":  ModelInfo(id="nim-llama-3-70b",  name="Llama 3.3 70B",    provider="nvidia",   litellm_id="nvidia_nim/meta/llama-3.3-70b-instruct"),
    # ... etc
}
```

### 7.3 Ollama Integration

Ollama gets special treatment:

```python
async def fetch_ollama_models(base_url):
    # 1. Query local Ollama server: GET /api/tags
    # 2. If unreachable, auto-start `ollama serve` in the background
    # 3. Query again after a delay
    # 4. Return real pulled models only
```

`_try_start_ollama()` (in `providers/ollama.py`) spawns a detached
`ollama serve` process when the server is unreachable and an `ollama`
executable is on `PATH`; `_cleanup_ollama()` terminates it on shutdown. If
Ollama is not installed, discovery simply returns no local models — users
can also run `ollama serve` manually.

### 7.4 Model Resolution

Model IDs flow through the system in this format:

- **Ollama models:** `ollama:llama3.2` → resolved as provider="ollama", litellm_id="ollama/llama3.2"
- **Dynamic cloud models:** `openai::openai/gpt-4o` → uses `::` separator between provider_id and litellm_id
- **Curated models:** Direct lookup in `MODELS` dict

The `_resolve_model()` function handles all three formats and raises `ValueError` for unknown models.

### 7.5 Provider Key Management

Users can link API keys entirely from the Settings UI — no `.env` editing required:

- **PUT** `/api/settings/providers/{id}/key` — Save a new key (stored in SQLite `provider_keys` table, encrypted with Fernet)
- **DELETE** `/api/settings/providers/{id}/key` — Remove a saved key
- **GET** `/api/settings/providers` — List all providers with masked key status

The `resolve_api_key()` function checks runtime keys first, then falls back to `.env` values:

```python
async def resolve_api_key(provider_id: str, db: AsyncSession) -> str | None:
    return (await get_db_keys(db)).get(provider_id) or PROVIDERS[provider_id]["env_key"]
```

---

## 8. Chat Streaming

### 8.1 Route Handler (`POST /api/chat/stream`)

The request body (`ChatStreamRequest`) includes:

```json
{
    "chat_id": null,         // null = create new chat
    "model": "claude-sonnet-5",
    "messages": [{"role": "user", "content": "Hello"}],
    "file_ids": [],
    "temperature": 0.7,
    "max_tokens": 1024,
    "regenerate": false,
    "web_search": false
}
```

Processing pipeline (implemented in `api_routes/chat_stream_routes.py`):
1. **Model validation** — resolve the model up front; unknown models fail fast with 400
2. **Web search** (optional) — inject live web results as a system message
3. **Chat resolution** — find existing or create new `Chat` record
4. **File context** — attach retrieved RAG chunks from uploaded files
5. **Response intelligence** — analyze the request and inject style guidance; stored user preferences override detected signals
6. **Clarification gate** — ambiguous short requests are intercepted with a clarification_request event instead of calling the provider
7. **Cross-session memory** — inject relevant past-conversation summaries
8. **Context truncation** — token-budget the message list to the model's window
9. **Stream** — emit canonical response events (`message_start` → deltas → `message_end` → `[DONE]`) with heartbeats
10. **Persist** — save user + assistant messages atomically; trigger rolling summarization in the background

### 8.2 Provider Routing (`stream_completion`)

The provider package routes each model to its adapter (Ollama streams
natively; cloud providers stream through LiteLLM):

```python
# mainfiles/backend/providers/__init__.py — stream_completion()
provider_id, litellm_id = _resolve_model(model_id)   # "ollama::x" -> ("ollama", "ollama/x")
provider_class = registry.get_provider_class(provider_id) or LiteLLMProvider
provider = provider_class(config, await resolve_api_key(provider_id, db))
async for chunk in provider.stream_completion(model_id=model_id, messages=messages, ...):
    yield chunk
```

The canonical event stream (`stream_response_events`) wraps this with
`message_start` / `text_delta` / `message_end` lifecycle events, tool-call
execution, and error normalization — see `response_events.py`.

**Ollama streaming** uses its native `/api/chat` endpoint with JSON-line
parsing for better support of reasoning models:

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

### 9.6 Frontend Skills Modal

The skills modal (`features/skills/skills.js`) provides:
- **Search** — filter by name, description, tags
- **Category filters** — engineering, design, behavioral, productivity, knowledge, system, personal, misc
- **Invocation filters** — all, command, auto, both
- **Detail panel** — parameters with validation, dependencies, execute button, copy command
- **Execution** — runs `/api/skills/execute`, shows result in modal

**Fixed Issues (v1.0.0):**
- CSS completely rewritten to match actual HTML structure (`.skills-layout`, `.skills-sidebar`, `.skills-search-wrap`, `.skills-categories`, `.skills-invocations`, `.skills-list`, `.skills-detail`)
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

**RAG Pipeline (mainfiles/backend/rag.py):**

| Step | Function | Description |
|------|----------|-------------|
| Chunk | `chunk_text()` | Paragraph-aware splitting (~500 tokens, 100-token overlap) |
| Index | `index_document()` | Chunk → embed → store in ChromaDB collection |
| Retrieve | `retrieve_relevant_chunks()` | Embed query → top-k L2 distance search |
| Cleanup | `delete_document_chunks()` | Remove all chunks for a deleted file |

**Key properties:**
- ChromaDB runs in embedded mode — no external service required
- Vector index stored on disk at `.chromadb/`
- All RAG operations catch exceptions and log warnings; chat never breaks
- Configurable chunk size (`CHUNK_SIZE`), overlap (`CHUNK_OVERLAP`), and top-k (`TOP_K`)
- Vector DB path overridable via `CHROMA_DB_PATH` env var (used in tests)

---

## 12. Testing

### 12.1 Test Suite Overview

Single consolidated tree under `tests/` — one file per domain, unit tests at
the top level and API-level integration tests under `tests/integration/`.
~1,000 tests total (948 root + 38 integration as of the 2026-09 refactor).

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_document.py` | 129 | Text extraction (PDF/DOCX/CSV/XLSX/PPTX/OCR), truncation |
| `test_auth.py` | 88 | Hashing, sessions, CSRF, lockout, endpoints, production mode |
| `test_llm.py` | 69 | Provider facade, model resolution, discovery wrappers |
| `test_rag.py` | 68 | Chunking, indexing, retrieval, cleanup |
| `test_websearch.py` | 57 | DuckDuckGo parsing, context formatting, providers |
| `test_prompt_injection_new.py` | 54 | Injection detection, log sanitization, validation |
| `test_api.py` | 53 | Route handlers (all endpoints, patch-level) |
| `test_provider_adapters.py` | 52 | Provider base/registry/adapter protocol |
| `test_providers.py` | 47 | Provider registry facade (list/status/stream) |
| `test_response_intelligence.py` | 46 | Request analysis, guidance, prompt additions |
| `test_policy_domain.py` | 42 | Response policy + domain dataclasses |
| `test_policy_integration.py` | 39 | Policy integration with chat flow |
| `test_policy_module.py` | 37 | Policy selector/adapter/manager |
| `test_context_manager.py` | 37 | Token budgeting, safe truncation |
| `test_models.py` | 36 | Model discovery + selection |
| `test_executor_coverage.py` | 31 | Skills executor |
| `test_main.py` | 29 | App factory, lifespan, health, CSRF middleware |
| `test_capability_orchestration.py` | 16 | Clarification heuristics, capability decisions |
| `test_response_events.py` | 11 | Canonical event builder/serialization |
| `test_postprocessor.py` | 11 | Uncertainty hedging |
| `test_preferences.py` / `test_clarification.py` / `test_message_feedback.py` / `test_memory.py` | 9/9/8/8 | Preferences, clarification gate, feedback, memory/summaries |
| `tests/integration/` | 38 | Auth, models, chat, security (HTTP-level) |

### 12.2 Running Tests

```bash
# From project root
venv\Scripts\python.exe -m pytest tests/ -v
```

The full tree is consolidated under `tests/` (one file per domain, ~950 tests).
Environment: `TEST_MODE=1` is set automatically by the suite conftest; every
DB-backed test binds a per-test SQLite file guarded against the production DB.

### 12.3 CI Pipeline (GitHub Actions)

The `.github/workflows/ci.yml` runs on push to `main`/`sangam` and on PRs:
1. Checkout + setup Python 3.13 + Node.js 22
2. Install Python dependencies
3. `compileall` check on backend, scripts, and tests
4. Run the full pytest suite (`TEST_MODE=1`)
5. `node --check` on every frontend JS file

A second `security` job runs Bandit (static analysis) and Safety (dependency
vulnerabilities) and uploads the reports as artifacts.

---

## 13. Configuration Reference

### 13.1 Environment Variables (`.env`)

```dotenv
# --- Application ---
APP_NAME=UniversalAI                          # App title in API responses
ENV=development                                # environment
APP_DEBUG=true                                 # SQLAlchemy echo + FastAPI debug
API_PREFIX=/api                                # URL prefix for all routes
ALLOWED_ORIGINS=["http://localhost:5500","http://127.0.0.1:5500"]

# --- Security ---
MASTER_KEY=                                   # Fernet key for provider-key encryption at rest.
                                              # start.py auto-generates one on first run if blank.

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

# --- Local Runtimes ---
OLLAMA_BASE_URL=http://localhost:11434
LM_STUDIO_BASE_URL=http://localhost:1234/v1
VLLM_BASE_URL=http://localhost:8001/v1

# --- OpenAI-compatible custom providers ---
OMNIROUTE_API_KEY=                            # optional
OMNIROUTE_BASE_URL=http://localhost:20128/v1

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
| GET | `/api/providers` | Yes | Provider status |
| POST | `/api/chat/stream` | Yes | Stream chat response (SSE) |
| GET | `/api/chats` | Yes | List all chats |
| GET | `/api/chats/{id}` | Yes | Get chat with messages |
| DELETE | `/api/chats/{id}` | Yes | Delete chat |
| POST | `/api/files` | Yes | Upload document |
| GET | `/api/settings/providers` | Yes | Provider key status |
| PUT | `/api/settings/providers/{id}/key` | Yes | Save API key |
| DELETE | `/api/settings/providers/{id}/key` | Yes | Remove API key |
| GET | `/api/auth/status` | No | Registration open? |
| POST | `/api/auth/register` | No | Create account |
| POST | `/api/auth/login` | No | Sign in |
| POST | `/api/auth/logout` | Yes | Sign out |
| GET | `/api/auth/me` | Yes | Current user |
| GET | `/api/skills/` | Yes | List skills |
| GET | `/api/skills/{id}` | Yes | Skill detail |
| POST | `/api/skills/execute` | Yes | Execute skill |
| POST | `/api/skills/chain` | Yes | Chain skills |
| POST | `/api/skills/auto-suggest` | Yes | Suggest skills |
| GET | `/api/chats/{id}/summary` | Yes | Rolling summary + key topics |
| POST | `/api/messages/{id}/feedback` | Yes | Thumbs up/down feedback |
| GET/PUT | `/api/user/preferences` | Yes | Response-style preferences |
| GET | `/api/settings/providers/{id}/models/refresh` | Yes | Live model catalogue fetch |
| POST | `/api/models/inaccessible/clear` | Yes | Reset inaccessible-model flags |
| POST | `/api/agentic-reasoning` | Yes | Enhance message with reasoning + tools |
| GET | `/health` (no prefix) | No | Deep health check (DB + Ollama) |

### 13.3 Database Schema

```
┌───────────────────┐       ┌───────────────────┐
│       users       │       │   auth_sessions   │
├───────────────────┤       ├───────────────────┤
│ id (PK)           │──┐    │ id (PK)           │
│ username (unique) │  └───>│ user_id (FK)      │
│ password_salt     │       │ token_hash (uniq) │
│ password_hash     │       │ expires_at (idx)  │
│ created_at        │       │ created_at        │
└───────────────────┘       └───────────────────┘

┌───────────────────┐       ┌───────────────────┐
│       chats       │       │     messages      │
├───────────────────┤       ├───────────────────┤
│ id (PK)           │──┐    │ id (PK)           │
│ title             │  └───>│ chat_id (FK)      │
│ model             │       │ role              │
│ created_at        │       │ content (TEXT)     │
│ updated_at        │       │ model             │
└───────────────────┘       │ file_ids          │
                            │ created_at        │
┌───────────────────┐       └───────────────────┘
│   uploaded_files  │
├───────────────────┤       ┌───────────────────┐
│ id (PK)           │       │  provider_keys    │
│ filename          │       ├───────────────────┤
│ stored_path       │       │ provider_id (PK)  │
│ extension         │       │ api_key           │
│ size_bytes        │       │ updated_at        │
│ extracted_text    │       └───────────────────┘
│ created_at        │
└───────────────────┘

┌───────────────────────────┐
│    skill_executions       │
├───────────────────────────┤
│ id (PK)                   │
│ skill_id (idx)            │
│ skill_name                │
│ params (JSON)             │
│ result (TEXT)             │
│ error (TEXT)              │
│ invocation_type           │
│ duration_ms               │
│ created_at                │
└───────────────────────────┘

┌───────────────────────────────┐
│   user_skill_preferences      │
├───────────────────────────────┤
│ id (PK)                       │
│ skill_id (idx)                │
│ enabled (bool)                │
│ auto_invoke (bool)            │
│ custom_params (JSON)          │
│ updated_at                    │
└───────────────────────────────┘
```

### 13.4 Startup Sequence

The `start.py` launcher:
1. **Ensure virtual environment** — creates `venv/` if missing
2. **Install dependencies** — `pip install -r requirements.txt` (with SHA-256 caching)
3. **Bootstrap `.env`** — creates `.env` from `.env.example` if missing and fills in a valid `MASTER_KEY` when the value is blank
4. **Free stale ports** — kills any process holding port 8001 or 5500
5. **Start backend** — `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001` (with `mainfiles/` on `PYTHONPATH`)
6. **Start frontend** — `python -m http.server 5500` serving `mainfiles/frontend/`
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
│  │  app.js                                                         │   │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────┐  │   │
│  │  │ Auth       │ │ Settings   │ │ Models     │ │ Chat         │  │   │
│  │  │ Module     │ │ Module     │ │ Module     │ │ Module       │  │   │
│  │  └─────┬──────┘ └─────┬──────┘ └─────┬──────┘ └──────┬───────┘  │   │
│  │        │              │              │              │           │   │
│  │  ┌─────┴──────┐ ┌─────┴──────┐ ┌─────┴──────┐ ┌─────┴───────┐  │   │
│  │  │ Sidebar    │ │ Skills     │ │ State      │ │ Storage     │  │   │
│  │  │ Module     │ │ Module     │ │ (signals)  │ │ (localStore)│  │   │
│  │  └────────────┘ └────────────┘ └────────────┘ └─────────────┘  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                            │                                            │
│                      apiFetch() / streamChat()                          │
│                            │                                            │
└────────────────────────────┼───────────────────────────────────────────┘
                             │
┌────────────────────────────┼───────────────────────────────────────────┐
│                    BACKEND (port 8001)                                  │
│                            │                                            │
│  ┌─────────────────────────┴─────────────────────────────────────────┐ │
│  │  main.py — FastAPI app + CORS + lifespan                          │ │
│  │  ├── /api/auth/* — auth.py (register, login, logout, session)     │ │
│  │  ├── /api/* — api.py facade -> api_routes/ (chat, models,          │ │
│  │  │    files, providers, settings)                                 │ │
│  │  └── /api/skills/* — skills/api_skills.py (skills CRUD + execute) │ │
│  └─────────────────────────┬─────────────────────────────────────────┘ │
│                            │                                            │
│  ┌─────────────────────────┴─────────────────────────────────────────┐ │
│  │  LLM Layer (llm.py facade -> providers/)                           │ │
│  │  ├── list_models() → live API fetch + curated fallback            │ │
│  │  ├── list_provider_status() → online/offline/needs_key per provider│ │
│  │  ├── stream_completion() → provider adapters (Ollama/LiteLLM)     │ │
│  │  └── resolve_api_key() → DB keys (Fernet) or .env fallback       │ │
│  └─────────────────────────┬─────────────────────────────────────────┘ │
│                            │                                            │
│  ┌──────────┐  ┌──────────┴──────────┐  ┌───────────────────────────┐  │
│  │ SQLite   │  │ Document Extraction  │  │ Web Search                │  │
│  │ (history │  │ (document.py)        │  │ (websearch.py)            │  │
│  │ /sangam   │  │ PDF  DOCX  XLSX     │  │ DuckDuckGo  Tavily  Brave │  │
│  │  .db)    │  │ CSV  PPTX  Code     │  │                           │  │
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