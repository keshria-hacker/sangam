# ARCHITECTURE.md — Sangam AI Studio

**Date:** 2026-10-09
**Branch:** `integration/full-program`

## Overview

Sangam is a self-hosted AI chat platform with an AI Studio shell. Built with:
- **Backend:** FastAPI + SQLAlchemy (async) + Alembic + SQLite
- **Frontend:** Vanilla ES modules (no framework) + CSS custom properties
- **Auth:** JWT with local user accounts

## Intent-Grouped Navigation

The sidebar rail groups features by user intent:
- **Home**: Dashboard with quick actions
- **Chat**: Main conversation (pinned, never closes)
- **Agents**: Agent Hub (custom agents, teams)
- **Knowledge**: Knowledge graph, memory browser, MCP
- **Create**: Artifact hub (docs, diagrams, code, HTML)
- **Code**: Code agent, design studio
- **Learn**: Learning mode (teacher + tutor)
- **Library**: Skills, MCP servers, extensions, templates
- **Insights**: Analytics dashboard, Arena leaderboard
- **Settings**: Full-page settings with schema

## Key Subsystems

### Agent Engine (`backend/code_agent.py`)
- `run_agent()`: Generalized agent loop yielding `AgentStep` events
- Tools: write_file, edit_file, run_bash, etc.
- Approval gate: sensitive tools emit `approval_needed`, wait for user
- Budget: `max_cost_usd` stops the loop when exceeded

### Teams (`backend/teams/`)
- `runner.py`: Fan-out/fan-in execution
- `streaming.py`: SSE streaming per specialist (Phase 6.4a)
- Endpoints: `/api/teams/run`, `/api/teams/run/stream`, `/api/teams/retry-agent`

### Knowledge Graph (`backend/knowledge_graph.py`)
- Unified graph: memories + documents + code + chats
- Edge provenance: EXTRACTED/INFERRED/AMBIGUOUS (Phase 6.4b)
- Memory wings: grouped by kind (episodic/semantic/procedural)

### Provider Resilience (`backend/providers/`)
- `resilience.py`: CircuitBreaker, retry with backoff
- `fallback_chain.py`: FallbackChain with quotas (Phase 6.4d)
- `GET /api/providers/status`: Expose breaker + quota states

### Automations (`backend/automations.py`)
- Scheduled tasks: hourly/daily/weekly/cron
- Actions: agent tasks, chat messages
- CRUD: `/api/automations`

### Model Compare & Arena (`backend/api_routes/compare_routes.py`)
- `POST /api/compare`: Parallel model comparison
- `POST /api/arena/vote`: Record winner
- `GET /api/arena/leaderboard`: Win rates

## Frontend Architecture

- **Entry:** `js/app.js` → initializes auth, nav, tabs
- **State:** `js/core/state.js` (signals), `js/core/jobs.js` (background jobs)
- **Nav:** `js/core/nav.js` (intent-grouped rail)
- **Tabs:** `js/features/tabs/tabs.js` (mount-once, persistent)
- **Settings:** `js/shared/settings_schema.js` + `settings_store.js`

## Security

- Prompt injection detection (`backend/prompt_injection.py`) — warn-only mode
- Approval gate for sensitive tools
- Per-user data isolation (all queries filter by `user_id`)
- JWT auth with CSRF tokens
