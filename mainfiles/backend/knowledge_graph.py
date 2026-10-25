"""
knowledge_graph.py — unified knowledge graph (Sangam-native, Phase 3).

Combines memories, documents, code symbols, and chats into one graph:
  nodes: [{id, type, label, metadata}]
  edges: [{from, to, type}]

Types: memory | document | code | chat
Edge types: mentions | defines | calls | contains | related
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


def _parse_as_of(as_of) -> datetime | None:
    """Parse an as-of instant (datetime or ISO string) or None."""
    if as_of is None:
        return None
    if isinstance(as_of, datetime):
        return as_of
    try:
        return datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
    except ValueError:
        return None


def _valid_at(rel: dict[str, Any], instant: datetime | None) -> bool:
    """Half-open interval check: valid_from <= t < valid_to (NULL = open)."""
    if instant is None:
        return True
    vf = rel.get("valid_from")
    vt = rel.get("valid_to")
    if isinstance(vf, str):
        vf = datetime.fromisoformat(vf.replace("Z", "+00:00"))
    if isinstance(vt, str):
        vt = datetime.fromisoformat(vt.replace("Z", "+00:00"))
    if vf is not None and instant < vf:
        return False
    if vt is not None and instant >= vt:
        return False
    return True


def build_knowledge_graph(
    memories: list[dict[str, Any]] | None = None,
    documents: list[dict[str, Any]] | None = None,
    code_graph: dict[str, Any] | None = None,
    chats: list[dict[str, Any]] | None = None,
    max_nodes: int = 200,
    relations: list[dict[str, Any]] | None = None,
    as_of=None,
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
                 provenance: str = "EXTRACTED", source: str | None = None,
                 confidence: float | None = None,
                 source_ref: str | None = None):
        """Add an edge with provenance tracking.

        Provenance: EXTRACTED (from actual data), INFERRED (from heuristics),
                    AMBIGUOUS (uncertain match).
        Source: where this edge came from (e.g. 'code_ast', 'keyword_match').
        Confidence/source_ref (memory relations) are surfaced on the
        edge when present, never invented when absent.
        """
        if frm in seen and to in seen and len(edges) < max_nodes * 3:
            edge: dict[str, Any] = {
                "from": frm, "to": to, "type": etype,
                "provenance": provenance,
                "source": source,
            }
            if confidence is not None:
                edge["confidence"] = confidence
            if source_ref:
                edge["source_ref"] = source_ref
            edges.append(edge)

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

    # Code symbols — consumes the code graph's RESOLVED edge list.
    # (Previously this branch read sym.get("calls")/sym.get("name"),
    # which code_graph never emitted, so call edges never materialised
    # — a dead branch. Symbols now carry "name"; edges carry resolved
    # targets + confidence, so provenance is real, not a label mirage.)
    if code_graph:
        for sym_id, sym in list(code_graph.get("symbols", {}).items())[:max_nodes // 2]:
            nid = f"code:{sym_id}"
            if add_node(nid, "code", sym.get("name", sym_id),
                        {"kind": sym.get("kind"), "file": sym.get("file"),
                         "line": sym.get("line"),
                         "signature": sym.get("signature")}):
                pass
        # Call edges from the resolved edge list (preferred path).
        code_edges = [e for e in code_graph.get("edges", [])
                      if e.get("type") == "calls"]
        if code_edges:
            for e in code_edges:
                frm, to = f"code:{e['from']}", f"code:{e['to']}"
                if frm in seen and to in seen:
                    add_edge(frm, to, "calls",
                             provenance=e.get("confidence", "INFERRED"),
                             source="code_graph")
        else:
            # Legacy fallback: symbols carrying their own calls list.
            for sym_id, sym in list(code_graph.get("symbols", {}).items()):
                nid = f"code:{sym_id}"
                for callee in sym.get("calls", [])[:10]:
                    cid = f"code:{callee}"
                    if cid in seen:
                        add_edge(nid, cid, "calls",
                                 provenance="EXTRACTED", source="code_ast")

    # Memory relations (entity graph, hardened): entity nodes joined
    # by predicate edges carrying confidence + source_ref, honoured
    # only for the as-of instant when one is given (half-open
    # intervals; superseded relations are outside their window).
    instant = _parse_as_of(as_of)
    for rel in relations or []:
        if not _valid_at(rel, instant):
            continue
        subj, obj = rel.get("subject", ""), rel.get("object", "")
        if not subj or not obj:
            continue
        sid, oid = f"ent:{subj}", f"ent:{obj}"
        add_node(sid, "entity", subj, {})
        add_node(oid, "entity", obj, {})
        add_edge(sid, oid, rel.get("predicate", "related"),
                 provenance="EXTRACTED", source="memory_graph",
                 confidence=rel.get("confidence"),
                 source_ref=rel.get("source_ref"))

    # Chats (as context hubs)
    for c in chats or []:
        cid = f"chat:{c.get('id', '')}"
        add_node(cid, "chat", c.get("title", "chat") or "chat",
                 {"model": c.get("model")})

    # Cross-links: memories mentioning document names, etc. (keyword-based)
    _link_by_keywords(nodes, edges, seen)

    # Backlinks visibility (cheap reverse index over the edges above):
    # backlinks[node_id] = ids of nodes that link TO it, so a node
    # detail view can show "linked from" without rebuilding the graph.
    backlinks: dict[str, list[str]] = {}
    for edge in edges:
        backlinks.setdefault(edge["to"], []).append(edge["from"])
    for node_id in backlinks:
        backlinks[node_id] = sorted(set(backlinks[node_id]))

    return {
        "backlinks": backlinks,
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "memories": sum(1 for n in nodes if n["type"] == "memory"),
            "documents": sum(1 for n in nodes if n["type"] == "document"),
            "code": sum(1 for n in nodes if n["type"] == "code"),
            "chats": sum(1 for n in nodes if n["type"] == "chat"),
            "entities": sum(1 for n in nodes if n["type"] == "entity"),
            "relations": sum(1 for e in edges if e.get("source") == "memory_graph"),
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
