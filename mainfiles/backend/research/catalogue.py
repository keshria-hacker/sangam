"""
research/catalogue.py — Batch 9: curated catalogue (awesome-mcp-servers
+ awesome-llm-apps, as DOCUMENTED data, not code).

These lists are curated reference rows, not scraped live data and not
installers: ``install`` tells the user how THEY would install or
enable something, and ``sangam_equivalent`` names the Sangam-native
operation that already covers the pattern (or null). Nothing here
auto-installs or executes a remote server — an entry whose install
route is not an existing Sangam connector/skill stays a documented
manual step, with its risk note attached.

Freshness is honest: ``CATALOGUE_VERSION`` + ``CURATED_ON`` stamp
when this snapshot was written; the UI labels it as a curated
snapshot to verify upstream before installing, not a live index.

Batch 6 audit note (2026-10-26): Batch 11 described imajev, Vane and
Open-Generative-AI as "catalogue entries", but no such rows existed in
this file — the claim was checked against the code and found untrue.
The three ``reference_note`` rows below are the correction: documented
reference rows only, no model run, no install, no code ported.
"""
from __future__ import annotations

CATALOGUE_VERSION = "batch9-1"
CURATED_ON = "2026-10-26"

# kind: "mcp_server" | "llm_pattern" | "reference_note"
_ENTRIES: list[dict] = [
    # --- MCP servers (awesome-mcp-servers taxonomy, curated subset) ---
    {"id": "mcp-filesystem", "kind": "mcp_server", "name": "Filesystem",
     "category": "local", "official": True,
     "description": "Read/write files under an allowed directory.",
     "install": "User-installed MCP server; scope it to one directory.",
     "risk": "File access — restrict to a single directory, never home.",
     "sangam_equivalent": "/knowledge/packs (workspace-scoped pack) + workspace-gated tools"},
    {"id": "mcp-sqlite", "kind": "mcp_server", "name": "SQLite",
     "category": "databases", "official": True,
     "description": "Query a local SQLite database with read-only intent.",
     "install": "User-installed MCP server; point it at a copy, not the live DB.",
     "risk": "Read-only queries only; never point at production data.",
     "sangam_equivalent": "SQLite-backed memory/knowledge stores (built in)"},
    {"id": "mcp-github", "kind": "mcp_server", "name": "GitHub",
     "category": "developer", "official": True,
     "description": "Repos, issues, pull requests via the GitHub API.",
     "install": "User-installed MCP server with a scoped personal token.",
     "risk": "Token scope — read-only unless the user explicitly needs writes.",
     "sangam_equivalent": None},
    {"id": "mcp-fetch", "kind": "mcp_server", "name": "Fetch",
     "category": "web", "official": True,
     "description": "Fetch a public URL as markdown/text.",
     "install": "User-installed MCP server.",
     "risk": "SSRF — only public URLs, same rule as Sangam ingest.",
     "sangam_equivalent": "POST /knowledge/ingest-url (SSRF-guarded)"},
    {"id": "mcp-brave-search", "kind": "mcp_server", "name": "Brave Search",
     "category": "web", "official": False,
     "description": "Web search via the Brave Search API.",
     "install": "User-installed MCP server with a Brave API key.",
     "risk": "API key handling — store in the provider key store, never in chat.",
     "sangam_equivalent": "POST /research/jobs (websearch providers incl. Brave)"},
    {"id": "mcp-memory", "kind": "mcp_server", "name": "Memory",
     "category": "local", "official": True,
     "description": "Persistent knowledge-graph memory for an assistant.",
     "install": "User-installed MCP server.",
     "risk": "Memory contents are durable — review before sharing a machine.",
     "sangam_equivalent": "GET /memory/observations (evidence-backed ledger)"},
    {"id": "mcp-git", "kind": "mcp_server", "name": "Git",
     "category": "developer", "official": True,
     "description": "Git operations (status, diff, log) on a local repo.",
     "install": "User-installed MCP server scoped to one repo.",
     "risk": "Mutating git commands need per-run approval, as in Sangam.",
     "sangam_equivalent": "POST /knowledge/code-map/change-impact + worktrees"},
    {"id": "mcp-postgres", "kind": "mcp_server", "name": "PostgreSQL",
     "category": "databases", "official": True,
     "description": "Query a PostgreSQL database.",
     "install": "User-installed MCP server with a read-only role.",
     "risk": "Not used by single-user Sangam (SQLite); read-only role required.",
     "sangam_equivalent": None},
    {"id": "mcp-puppeteer", "kind": "mcp_server", "name": "Puppeteer",
     "category": "browser", "official": False,
     "description": "Browser automation via Puppeteer.",
     "install": "User-installed MCP server; run headless in a sandbox.",
     "risk": "Browser agents can act on pages — per-run approval required.",
     "sangam_equivalent": "Browser agent (two-mode, approval-gated)"},
    {"id": "mcp-slack", "kind": "mcp_server", "name": "Slack",
     "category": "messaging", "official": False,
     "description": "Read/post Slack messages via bot token.",
     "install": "User-installed MCP server with a bot token.",
     "risk": "Posting as a bot is a public action — approval-gated in Sangam use.",
     "sangam_equivalent": None},
    # --- LLM app patterns (awesome-llm-apps, named + testable) ---
    {"id": "pattern-corrective-rag", "kind": "llm_pattern", "name": "Corrective RAG",
     "category": "rag", "official": False,
     "description": "Retrieve, grade evidence, rewrite the query or fall back to web search.",
     "install": "Built-in pattern; no install.",
     "risk": "Grading is heuristic without a model; results carry their grade.",
     "sangam_equivalent": "GET /knowledge/retrieve (grade_results + rewrite_query)"},
    {"id": "pattern-hybrid-search", "kind": "llm_pattern", "name": "Hybrid Search",
     "category": "rag", "official": False,
     "description": "Vector + keyword retrieval fused by reciprocal rank.",
     "install": "Built-in pattern; no install.",
     "risk": "None — ranking only.",
     "sangam_equivalent": "GET /knowledge/retrieve + hybrid_retrieval.rrf_fuse"},
    {"id": "pattern-graph-rag", "kind": "llm_pattern", "name": "Knowledge-Graph RAG",
     "category": "rag", "official": False,
     "description": "Retrieval boosted by entity-graph relations, with citations.",
     "install": "Built-in pattern; no install.",
     "risk": "Entity boosts are string-matched, not embedding-resolved.",
     "sangam_equivalent": "memory/retrieval entity boost + /memory/entities"},
    {"id": "pattern-agentic-rag", "kind": "llm_pattern", "name": "Agentic RAG",
     "category": "agents", "official": False,
     "description": "Reasoning loop that decides when to retrieve, search, or answer.",
     "install": "Built-in pattern; no install.",
     "risk": "Loop bounded by iteration cap; every tool call is audited.",
     "sangam_equivalent": "POST /research/jobs (plan/search/curate/compress/write)"},
    {"id": "pattern-critique-loop", "kind": "llm_pattern", "name": "Critique-Improvement Loop",
     "category": "agents", "official": False,
     "description": "Draft, critique against sources, revise; uncited claims rejected.",
     "install": "Built-in pattern; no install.",
     "risk": "The gate is only as good as the citation check — it rejects, never invents.",
     "sangam_equivalent": "POST /research/jobs/{id}/report (422 on uncited claims)"},
    {"id": "pattern-deep-research", "kind": "llm_pattern", "name": "Deep Research Loop",
     "category": "research", "official": False,
     "description": "Breadth queries, depth recursion, curation, word-budget compression.",
     "install": "Built-in pattern; no install.",
     "risk": "Search providers vary; sources always carry curator scores.",
     "sangam_equivalent": "POST /research/jobs + POST /research/jobs/{id}/run"},
    {"id": "pattern-memory-ledger", "kind": "llm_pattern", "name": "Observation Ledger",
     "category": "memory", "official": False,
     "description": "Consolidated beliefs with quote evidence, proof counts, refinement history.",
     "install": "Built-in pattern; no install.",
     "risk": "Strength is a heuristic counter, not a probability.",
     "sangam_equivalent": "GET /memory/observations"},
    {"id": "pattern-markdown-memory", "kind": "llm_pattern", "name": "Memory as Markdown",
     "category": "memory", "official": False,
     "description": "Agent memory as dated, typed Markdown notes in one browsable folder.",
     "install": "Built-in pattern; no install.",
     "risk": "Notes live on disk — the folder itself should stay private.",
     "sangam_equivalent": "GET /memory/notes + POST /memory/notes/normalize"},
    # --- Batch 6 reference notes: documented rows only, nothing runs ---
    {"id": "ref-imajev", "kind": "reference_note", "name": "imajev (decision models)",
     "category": "decision", "official": False,
     "description": "Small open decision models (2B/4B/9B) that answer in caller-set options "
     "with per-option probabilities and an explicit can't-tell. No portable mechanism "
     "beyond model weights + prompting, and the weights are not run in Sangam.",
     "install": "Not installed; documented pattern only. No model call is faked.",
     "risk": "Probabilities here are a documented output shape, not a live model result.",
     "sangam_equivalent": "Documented shape only (options + probabilities + abstain threshold) "
     "for future critique/decision outputs; no endpoint implements it as a model."},
    {"id": "ref-vane", "kind": "reference_note", "name": "Vane (privacy answering engine)",
     "category": "search", "official": False,
     "description": "Privacy-focused AI answering engine (SearxNG + local/cloud LLMs, cited "
     "sources, speed/balanced/quality search modes, source picking). That is "
     "search/research, not media — no Vane code is built in Sangam.",
     "install": "Not installed; pattern already covered by Sangam's own search/research.",
     "risk": "Search-mode/source-picking claims are Sangam's own behaviour, not Vane's.",
     "sangam_equivalent": "POST /research/jobs + websearch (Batch 9) + cited reports"},
    {"id": "ref-open-generative-ai", "kind": "reference_note", "name": "Open-Generative-AI (model studio)",
     "category": "studio", "official": False,
     "description": "Electron studio fronting 600+ models across image/video/audio/lip-sync "
     "studios. Its portable idea (a model catalogue with per-model input schemas) "
     "already exists in Sangam as the provider/engine registries.",
     "install": "Not installed; no new catalogue built for it.",
     "risk": "Its video, lip-sync and unrestricted-generation studios are excluded "
     "(video generation + no content-filter bypass, per standing guardrails).",
     "sangam_equivalent": "Provider/engine registries + GET /api/models; video/lip-sync excluded"},
]


def catalogue_entries() -> list[dict]:
    """Deduped entries (by id, first wins) with the freshness stamp.
    Dedupe is structural: a repeated id can never produce two rows."""
    seen: dict[str, dict] = {}
    for entry in _ENTRIES:
        if entry["id"] not in seen:
            seen[entry["id"]] = dict(entry)
    rows = list(seen.values())
    for row in rows:
        row["catalogue_version"] = CATALOGUE_VERSION
        row["curated_on"] = CURATED_ON
    return rows


def search_catalogue(q: str = "", category: str = "", kind: str = "") -> list[dict]:
    """Case-insensitive substring search over name/description/
    category, with optional category + kind filters."""
    needle = (q or "").strip().lower()
    out = []
    for entry in catalogue_entries():
        if kind and entry["kind"] != kind:
            continue
        if category and entry["category"] != category:
            continue
        if needle and needle not in f"{entry['name']} {entry['description']} {entry['category']}".lower():
            continue
        out.append(entry)
    return out
