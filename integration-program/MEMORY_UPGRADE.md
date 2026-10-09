# Memory++ — Long-Term Memory Upgrade

**Status:** implemented (2026-10-08) · branch `memory-plus`
**Inspired by:** MemPalace (memory quality benchmark patterns), codebase-memory-mcp / graphify (knowledge-graph ideas, via the MCP seam — not yet connected)

## What changed

The old system stored one summary per chat and did plain top-2 vector search.
Memory++ keeps that data readable and adds a real memory system underneath.

### Typed memories (`backend/memory/models.py`)
- **episodic** — things that happened (corrections, events)
- **semantic** — durable facts about the user (name, dog, preferences)
- **procedural** — how the user likes things done ("never use emojis in changelogs")

Each record carries `importance` (0–1), `created_at`, `last_accessed`, `access_count`.

### Explainable ranking (`backend/memory/scoring.py`)
`score = similarity × recency × importance × access`
- Recency: 30-day half-life exponential decay, floored at 0.2
- Importance: offline regex heuristics — "remember this" → 0.9, "I prefer" → 0.75, corrections → 0.7; no LLM call, works offline and free
- Access: frequently recalled memories get up to 1.5× boost

### Auto-extraction (`backend/memory/extract.py`)
After every chat turn (fire-and-forget, never blocks streaming), the user's
message is scanned for memory-worthy sentences. Near-duplicates bump the
existing memory's importance instead of creating a new record. Conservative:
max 2 per turn, minimum importance 0.55.

### Consolidation (`backend/memory/consolidation.py`)
- Untouched memories decay 5% per pass (floor 0.10)
- Prune only when a memory is unimportant AND >90 days old AND never recalled
- Exposed as `POST /api/memory/consolidate` — safe to cron

### API (`backend/api_routes/memory_routes.py`)
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/memory?q=&kind=&limit=` | search (ranked) or list recent |
| POST | `/api/memory` | explicitly save a memory |
| DELETE | `/api/memory/{id}` | forget one memory |
| GET | `/api/memory/stats` | totals by kind |
| POST | `/api/memory/consolidate` | run a consolidation pass |

Also mirrored under `/api/v1/*` by the foundation's versioning.

### Chat pipeline
- Retrieval upgraded from `retrieve_memories(top_k=2)` to ranked `recall(top_k=3, exclude_chat_id=...)` — the current chat's own summaries no longer leak into context via the old string-contains hack
- Legacy `store_memory`/`retrieve_memories` signatures preserved for `summarizer.py`

### Extension registry
Registered as `capability:memory` v2.0.0 (kind: CAPABILITY) on startup.

### Settings UI
New **Memory** section in Settings: stats by kind, live search, per-memory
delete ("forget"), and a **Tidy up** button that runs consolidation.

## Design decisions
1. **No LLM in the memory loop.** Extraction and scoring are heuristic so memory stays fast, offline, and free. An LLM judge can be added later behind the `multi-agent` flag.
2. **Conservative pruning.** Losing a memory is worse than keeping a stale one; prune conditions require all three signals.
3. **Old memories keep working.** Same ChromaDB collection; legacy records read with sensible defaults (episodic, 0.4 importance).

## Future (not in this pass)
- Consolidation cron (needs a scheduler decision)
- Memory UI for "pin this memory" / importance editing
- Codebase knowledge graph via MCP (`codebase-memory-mcp` / `graphify` connect through `MCP_SERVERS_JSON` — the client seam exists from Phase 0)
- MemPalace-style quality eval harness for recall
