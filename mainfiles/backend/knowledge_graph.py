"""
knowledge_graph.py — unified knowledge graph (Sangam-native, Phase 3).

Combines memories, documents, code symbols, and chats into one graph:
  nodes: [{id, type, label, metadata}]
  edges: [{from, to, type}]

Types: memory | document | code | chat
Edge types: mentions | defines | calls | contains | related
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def build_knowledge_graph(
    memories: list[dict[str, Any]] | None = None,
    documents: list[dict[str, Any]] | None = None,
    code_graph: dict[str, Any] | None = None,
    chats: list[dict[str, Any]] | None = None,
    max_nodes: int = 200,
) -> dict[str, Any]:
    """Build a unified graph from the available sources."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_node(node_id: str, ntype: str, label: str, metadata: dict | None = None):
        if node_id in seen or len(nodes) >= max_nodes:
            return False
        seen.add(node_id)
        nodes.append({
            "id": node_id, "type": ntype, "label": label[:80],
            "metadata": metadata or {},
        })
        return True

    def add_edge(frm: str, to: str, etype: str,
                 provenance: str = "EXTRACTED", source: str | None = None):
        """Add an edge with provenance tracking.

        Provenance: EXTRACTED (from actual data), INFERRED (from heuristics),
                    AMBIGUOUS (uncertain match).
        Source: where this edge came from (e.g. 'code_ast', 'keyword_match').
        """
        if frm in seen and to in seen and len(edges) < max_nodes * 3:
            edges.append({
                "from": frm, "to": to, "type": etype,
                "provenance": provenance,
                "source": source,
            })

    # Memories (grouped into wings/rooms by kind)
    wings: dict[str, list[str]] = {}  # kind -> [node_ids]
    for m in memories or []:
        mid = f"mem:{m.get('id', '')}"
        kind = m.get("kind", "semantic")
        if add_node(mid, "memory", m.get("content", "")[:60] or "memory",
                    {"kind": kind, "importance": m.get("importance"),
                     "wing": kind}):
            wings.setdefault(kind, []).append(mid)

    # Wing hub nodes (rooms)
    for wing, members in wings.items():
        wing_id = f"wing:{wing}"
        if add_node(wing_id, "wing", f"{wing.title()} memories",
                    {"member_count": len(members)}):
            for mid in members:
                add_edge(wing_id, mid, "contains",
                         provenance="EXTRACTED", source="memory_kind")

    # Documents
    for d in documents or []:
        did = f"doc:{d.get('id', '')}"
        add_node(did, "document", d.get("filename", "document") or "document",
                 {"mime": d.get("mime_type"), "size": d.get("size")})

    # Code symbols
    if code_graph:
        for sym_id, sym in list(code_graph.get("symbols", {}).items())[:max_nodes // 2]:
            nid = f"code:{sym_id}"
            if add_node(nid, "code", sym.get("name", sym_id),
                        {"kind": sym.get("kind"), "file": sym.get("file")}):
                # Call edges (EXTRACTED from AST)
                for callee in sym.get("calls", [])[:10]:
                    cid = f"code:{callee}"
                    if cid in seen:
                        add_edge(nid, cid, "calls",
                                 provenance="EXTRACTED", source="code_ast")

    # Chats (as context hubs)
    for c in chats or []:
        cid = f"chat:{c.get('id', '')}"
        add_node(cid, "chat", c.get("title", "chat") or "chat",
                 {"model": c.get("model")})

    # Cross-links: memories mentioning document names, etc. (keyword-based)
    _link_by_keywords(nodes, edges, seen)

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "memories": sum(1 for n in nodes if n["type"] == "memory"),
            "documents": sum(1 for n in nodes if n["type"] == "document"),
            "code": sum(1 for n in nodes if n["type"] == "code"),
            "chats": sum(1 for n in nodes if n["type"] == "chat"),
        },
    }


def _link_by_keywords(nodes: list[dict], edges: list[dict], seen: set[str]):
    """Add 'related' edges between nodes sharing significant keywords."""
    import re
    stopwords = {"the", "a", "an", "and", "or", "in", "on", "to", "of", "for", "is", "it"}
    keywords: dict[str, set[str]] = {}
    for n in nodes:
        words = set(re.findall(r"[a-z]{4,}", n["label"].lower())) - stopwords
        keywords[n["id"]] = words
    ids = list(keywords)
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            shared = keywords[ids[i]] & keywords[ids[j]]
            if len(shared) >= 2 and len(edges) < 600:
                # INFERRED: keyword overlap is heuristic, not certain
                # AMBIGUOUS if only 2 shared words, INFERRED if 3+
                prov = "INFERRED" if len(shared) >= 3 else "AMBIGUOUS"
                edges.append({
                    "from": ids[i], "to": ids[j], "type": "related",
                    "provenance": prov, "source": "keyword_match",
                    "shared_keywords": sorted(shared)[:5],
                })
