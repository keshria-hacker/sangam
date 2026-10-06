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
- Real-time streaming responses (Server-Sent Events, canonical `response_event` protocol)
- Document upload + text extraction (PDF, DOCX, XLSX, code, etc.)
- Web search augmentation (DuckDuckGo out of the box, Tavily/Brave optional)
- In-app API key management (no server restarts)
- Conversation history with bucketed date grouping + rolling cross-session summaries
- Response Intelligence: intent/style classification, clarification gate, uncertainty hedging
- Paper / Ink theme system (light / dark / system) — monochrome design tokens
- Extensible Skills system
- Local authentication (single-user, scrypt password hashing, login lockout, forgot/reset flow)
- Ollama auto-detection and auto-start (Sangam launches `ollama serve` in the background if installed but not running)

---

## 2. Directory Structure

```
<repo root>/
├── .dockerignore               # Docker build exclusion rules
├── Dockerfile                  # Multi-stage Docker build (builder + slim runtime)
├── docker-compose.yml          # Backend + optional Redis/frontend services
├── mainfiles/                  # Application code (backend package + frontend + config)
│   ├── backend/                # FastAPI Python backend (imported as `backend.*`)
│   │   ├── main.py             # App entrypoint/factory, lifespan, CORS, CSRF, security headers, router mounts
│   │   ├── config.py           # Typed settings loaded from .env via pydantic-settings
│   │   ├── database.py         # Async SQLAlchemy engine + session factory (SQLite)
│   │   ├── models.py           # SQLAlchemy ORM tables (Chat, Message, User, UserPreference, AuthSession, …)
│   │   ├── schemas.py          # Pydantic request/response validation models
│   │   ├── api.py              # HTTP API facade — mounts handlers from api_routes/
│   │   ├── api_routes/         # Route handlers split by resource
│   │   │   ├── common.py               # SSE framing + upload-content helpers
│   │   │   ├── providers_routes.py     # provider keys, model refresh, websearch, health
│   │   │   ├── files_routes.py         # document upload
│   │   │   ├── chats_routes.py         # chat CRUD, preferences, summary, feedback
│   │   │   ├── models_routes.py        # model catalogue
│   │   │   └── chat_stream_routes.py   # chat streaming pipeline + agentic reasoning
│   │   ├── auth.py             # Local auth (register, login, logout, forgot/reset, sessions, CSRF, lockout)
│   │   ├── llm.py              # Facade over providers/: model resolution, streaming
│   │   ├── capability_orchestration.py  # Clarification gate (should_clarify) + interpretations
│   │   ├── response_events.py  # Canonical SSE event model + ResponseEventBuilder
│   │   ├── response_intelligence/  # Intent/style classification, ambiguity triggers, prompt injection
│   │   ├── response_postprocessor.py   # Uncertainty hedging at persistence time
│   │   ├── context_manager.py  # Safe context truncation / token budgeting
│   │   ├── memory.py           # Cross-session memory store (ChromaDB)
│   │   ├── summarizer.py       # Rolling chat summarization
│   │   ├── security.py         # Fernet field encryption (MASTER_KEY) + CSRF tokens
│   │   ├── prompt_injection.py # Prompt-injection detection
│   │   ├── document.py         # File text extraction (PDF, DOCX, XLSX, CSV, PPTX, code, text)
│   │   ├── rag.py              # Document chunking + vector retrieval (ChromaDB)
│   │   ├── websearch.py        # Web search (DuckDuckGo Lite / Tavily / Brave)
│   │   ├── ratelimit.py        # Rate limiting middleware (+ ratelimit_redis.py Redis store)
│   │   ├── middleware/         # ASGI middleware (request ID)
│   │   ├── migrations/         # Alembic migration scripts
│   │   ├── tools/              # Tool-calling registry + executor (agentic reasoning)
│   │   └── providers/          # Provider adapters + registry
│   │       ├── __init__.py     # Provider registration, list_models, list_provider_status
│   │       ├── base.py         # Abstract provider interface + non-chat model filtering
│   │       ├── registry.py     # ProviderRegistry + provider configs
│   │       ├── model_discovery.py  # Live model fetch (fetch_models_from_provider)
│   │       ├── key_resolver.py # API key resolution (DB → env)
│   │       ├── ollama.py       # Native Ollama streaming + auto-start (_try_start_ollama)
│   │       ├── openai_compatible.py# OpenAI-compatible adapter (Together/Groq/OpenRouter/DeepSeek/Mistral/OmniRoute)
│   │       ├── anthropic.py / gemini.py / nvidia.py
│   │       ├── litellm_fallback.py / compat.py / inaccessible.py
│   │       └── enhanced/       # Intelligent routing layer (cost/latency/capability scores)
│   ├── frontend/               # Static frontend (served via Python http.server)
│   │   ├── index.html          # Single-page application HTML
│   │   ├── css/
│   │   │   └── style.css       # Complete design system + all component styles
│   │   ├── js/
│   │   │   ├── app.js          # Main application bootstrap & global listeners
│   │   │   ├── core/state.js   # Central signal-based reactive state store
│   │   │   ├── shared/         # Shared utilities
│   │   │   │   ├── constants.js    # DEFAULT_SETTINGS, CHAT_BUCKETS, provider colors, STORAGE_KEYS
│   │   │   │   ├── http.js         # apiFetch/apiPost/apiPut/apiDelete + streamChatCompletion/parseSSE
│   │   │   │   ├── markdown.js     # Streaming markdown + highlight.js + KaTeX rendering
│   │   │   │   ├── toast.js        # Toast notifications
│   │   │   │   └── utils.js        # escapeHtml, formatDate, bucketFor, etc.
│   │   │   └── features/       # Feature modules (one per UI area)
│   │   │       ├── auth/auth.js              # Login/register/forgot/reset, session check, logout
│   │   │       ├── chat/chat.js              # Send/regenerate/streaming, SSE handling, clarification cards
│   │   │       ├── chat/message_view.js      # Message DOM construction + in-stream status widgets
│   │   │       ├── chat/autoscroll.js        # Smart auto-scroll controller (hysteresis + jump-to-latest)
│   │   │       ├── chat/response_controller.js  # Canonical response_event state machine (client side)
│   │   │       ├── models/models.js          # Model selector, provider status
│   │   │       ├── settings/settings.js      # Theme, API keys, preferences
│   │   │       ├── skills/skills.js          # Skills modal browser & execution
│   │   │       └── sidebar/sidebar.js        # Chat history sidebar (bucketed by date)
│   │   ├── assets/
│   │   │   └── logo.png        # Sangam brand logo
│   │   └── package.json        # {"type": "module"} so node --check parses JS as ESM
│   ├── config/
│   │   ├── providers.yaml      # Reference provider registry (documentation only)
│   │   └── skills/             # Skill definitions (SKILL.md files)
│   │       ├── api-design/
│   │       ├── coding-standards/
│   │       └── web-search/
│   ├── history/                # SQLite database (sangam.db)
│   ├── uploads/                # Uploaded file storage
│   └── logs/                   # Rotating application logs (loguru)
├── tests/                      # Unified test tree (pytest — unit, integration/, e2e/, manual/)
│   ├── conftest.py             # Shared fixtures (auth client, tmp DB, path setup)
│   ├── integration/            # HTTP-level API tests (auth, chat, models, security)
│   ├── e2e/ + manual/          # End-to-end and manually-run checks
│   └── test_*.py               # Unit tests per backend module (~35 files)
├── scripts/                    # Dev & CI utilities (quality.sh/ps1, check_frontend_modules.mjs,
│                               #   e2e_walkthrough.py, runtime_verify.py, ui_verify_chrome.py,
│                               #   merge_tests.py, generate_master_key.py)
├── start.py                    # Launcher: venv, deps, env, then both servers
├── start.bat / start.sh        # One-command start (Windows / Unix)
├── .env / .env.example         # Environment configuration
├── pyproject.toml              # Ruff, mypy, pytest, coverage, bandit config
├── requirements.txt            # Python dependencies
├── README.md                   # Project README
└── ARCHITECTURE.md             # This file
```

---

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
| `chat_stream_routes.py` | The streaming pipeline (`/chat/stream`) + `/agentic-reasoning` |

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

The frontend now uses a **feature-based module structure** under `frontend/js/features/` — each feature owns its own DOM, state, and logic:

| Module | Responsibility |
|--------|----------------|
| `core/state.js` | Central signal store — `[get, set]` pairs for providers, models, chats, messages, selectedModel, temperature, maxTokens, reasoningEffort, webSearchEnabled, agenticReasoningEnabled, settings (persisted to `localStorage` as `sangam-settings`), etc. Also `createComputed` / `createSyncedSignal` helpers |
| `shared/constants.js` | `DEFAULT_SETTINGS`, `CHAT_BUCKETS`, `STORAGE_KEYS`, provider color/label maps |
| `shared/http.js` | `apiFetch`, `apiGet/apiPost/apiPut/apiDelete`, `apiPostForm`, `streamChatCompletion`, `parseSSE` — authenticated requests + SSE parsing |
| `shared/markdown.js` | Streaming-safe markdown → HTML rendering (marked + highlight.js + KaTeX) |
| `shared/toast.js` | Toast notifications |
| `shared/utils.js` | `escapeHtml`, `formatDate`, `debounce`, etc. |
| `features/auth/auth.js` | Login, register, forgot/reset password, session check, logout |
| `features/chat/chat.js` | SSE streaming orchestration, send/regenerate, file attachments, clarification cards |
| `features/chat/message_view.js` | Message DOM construction — assistant/user message nodes and in-stream status widgets (thinking, reasoning, tools, citations, artifacts) |
| `features/chat/autoscroll.js` | Smart auto-scroll with hysteresis + a "jump to latest" affordance during streaming |
| `features/chat/response_controller.js` | Client-side state machine for the canonical `response_event` SSE protocol |
| `features/models/models.js` | Model selector dropdown, provider status badges, "no models" handling |
| `features/settings/settings.js` | Theme (Paper/Ink/system), font size, chat width, code theme, animations; provider key manager (add/remove keys) |
| `features/skills/skills.js` | Skills modal: search, category/invocation filters, detail panel, execution |
| `features/sidebar/sidebar.js` | Chat history list (bucketed by date), new chat, delete chat |

**Boot sequence (`app.js` `init()`):**
1. Initialize DOM references and inject the markdown CSP
2. Initialize global state (`state.js`) — persisted settings are loaded from `localStorage` (`sangam-settings`)
3. Initialize feature modules in dependency order: auth → settings → models → chat → sidebar
4. Call `initGlobalListeners()` for topbar controls (temperature, tokens, reasoning, web search, shortcuts) and `initSkills()`
5. `initializeAuth()` — validates the stored session, then invokes the `startApplication` callback on success

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

### 9.6 Frontend Skills Modal

The skills modal (`features/skills/skills.js`) provides:
- **Search** — filter by name, description, tags
- **Category filters** — engineering, design, behavioral, productivity, knowledge, system, personal, misc
- **Invocation filters** — all, command, auto, both
- **Detail panel** — parameters with validation, dependencies, execute button, copy command
- **Execution** — runs `/api/skills/execute`, shows result in modal

**Fixed Issues (v1.1):**
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

The test suite is a single unified tree at `tests/` (~45 files: unit, `integration/`, `e2e/`, `manual/`) consolidated by the module-split refactor — ~950 tests collect and run under pytest. The backend package is importable via the path setup in `tests/conftest.py` (plus `PYTHONPATH=mainfiles` in CI).

Representative modules:

| Area | Files | Coverage |
|-----------|-------|----------|
| Authentication | `test_auth.py`, `test_auth_unit.py` | Password hashing, tokens, session lifecycle, brute-force lockout |
| API surface | `test_api.py`, `tests/integration/test_api_*.py` | Route behavior, auth gates, chat/model/file endpoints |
| Documents + RAG | `test_document.py`, `test_rag.py` | Extraction, truncation, chunking, retrieval |
| Models/providers | `test_models.py`, `test_providers.py`, `test_provider_adapters.py`, `test_llm.py` | Live fetch, filtering, Ollama discovery, curated fallback, routing |
| Enhanced routing | `test_enhanced_routing.py`, `test_standalone_routing.py` | Provider scoring, resilience, fallback dispatch |
| Response intelligence | `test_response_intelligence.py`, `test_capability_orchestration.py`, `test_clarification.py`, `test_response_events.py` | Ambiguity triggers, clarification gate, canonical SSE events |
| Policy + postprocessing | `test_policy_domain.py`, `test_policy_integration.py`, `test_policy_module.py`, `test_postprocessor.py` | Response policy rules, uncertainty hedging |
| Web search | `test_websearch.py` | DuckDuckGo parser, format_context, providers |
| Memory + feedback | `test_memory.py`, `test_message_feedback.py`, `test_preferences.py` | Cross-session memory, message feedback, user preferences |
| Streaming + frontend contract | `test_streaming.py`, `test_frontend_response_controller.py` | SSE frame format, client state machine |
| Other | `test_startup.py`, `test_schemas.py`, `test_skill_registry.py`, `test_skills.py`, `test_executor_coverage.py`, `test_context_manager.py`, `test_prompt_injection_new.py`, `test_ratelimit_redis.py`, `test_main.py`, `test_e2e.py` | Launcher, validation, skills, context truncation, injection detection, Redis limiter |

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

> **Note:** the coverage gate is the measured pytest baseline (66.47% on 2026-10-06, 950 passed / 100 skipped on the unified tree) rather than the historical 76%, because the response-intelligence and enhanced-provider subsystems still have limited coverage. Raise `fail_under` in `pyproject.toml` (and the workflow) as coverage grows.

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
| GET | `/api/providers` | Yes | Provider status |
| POST | `/api/chat/stream` | Yes | Stream chat response (SSE) |
| POST | `/api/agentic-reasoning` | Yes | Tool-calling reasoning endpoint |
| GET | `/api/chats` | Yes | List all chats (with summaries) |
| POST | `/api/chats` | Yes | Create a chat |
| GET | `/api/chats/{id}` | Yes | Get chat with messages |
| DELETE | `/api/chats/{id}` | Yes | Delete chat |
| GET | `/api/chats/{id}/summary` | Yes | Rolling summary + topics (Phase 5) |
| POST | `/api/messages/{id}/feedback` | Yes | Message quality feedback (up/down + note) |
| POST | `/api/files` | Yes | Upload document |
| GET | `/api/user/preferences` | Yes | Response style preferences |
| PUT | `/api/user/preferences` | Yes | Update response style preferences |
| GET | `/api/settings/providers` | Yes | Provider key status |
| PUT | `/api/settings/providers/{id}/key` | Yes | Save API key |
| DELETE | `/api/settings/providers/{id}/key` | Yes | Remove API key |
| GET | `/api/settings/providers/{id}/models/refresh` | Yes | Re-fetch models for one provider |
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
│ updated_at                    │
└───────────────────────────────┘
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