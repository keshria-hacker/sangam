# Sangam — Memory, Knowledge & Projects (perfect-flow program)

## Memory V2

Typed memories (episodic / semantic / procedural), importance-ranked
recall, auto-extraction from turns, consolidation (decay + prune),
and a REST API. Chat recall uses a reranker + knowledge-graph
expansion on top of hybrid retrieval.

## Projects: scoped, not partitioned

A project is a workspace with versioned instructions, sources,
tasks, and scoped chats. Project tasks reuse the goals Task system
(`project_id` set, `goal_id` NULL). Sources are ingested on add with
the SSRF guard and deduped. Project-scoped retrieve is proven by a
test to leak nothing across projects — but the honest shape is that
project memory *scope governs retrieval*; it is not a separate
partition. Project retrieve deliberately has no graph expansion and
no web fallback: both would break scoping.

## Provenance labels

Retrieved chunks carry `verified` / `inferred` labels. Graph
expansion is kept separate from chunk scores (it must not inflate a
chunk's relevance silently).

## Knowledge graph + notebooks

- Graph hardening + read-only reflect from the deep-read run.
- Notebooks support URL ingest + BFS crawl; un-excluding a URL source
  now ingests it (a real bug fixed in this program).
- Corrective RAG: retrieval failures feed back into the query path
  instead of returning thin answers silently.

## Memory privacy dashboard

Settings → Memory & Knowledge hosts the per-memory dashboard: every
memory listed, per-memory delete, export. Knowledge Export is still
memories-JSON only (carried limit from the previous program, not
re-claimed as full export).

## What memory does NOT do

- No cross-project leakage (tested), but also no claim of a separate
  encrypted partition per project.
- No automatic memory of other people's data: single-user by design;
  LAN devices see the host's workspace only through their own paired
  token, revocable from Settings → Security.
- Lesson-player TTS is not wired (carried limit).
