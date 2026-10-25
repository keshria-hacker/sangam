"""
research/code_memory.py — Batch 9: code memory (codebase-memory-mcp +
graphify patterns, Sangam-native, over the existing code graph).

Three genuinely-missing pieces, nothing else:

1. Refresh on file change — ``refresh_if_stale`` diffs the stored
   fingerprint (``code_graph.probe_fingerprint``) against the live
   tree and rebuilds ONLY when something changed. The UI can show
   the returned ``stale`` flag instead of silently serving an old
   map (Understand-Anything's staleness-as-signal, without a React
   dashboard).
2. Change impact — ``change_impact`` maps a symbol (or a changed
   file) to its callers, its tests (files whose path or imports
   look like tests for it), and its architecture layer (top-level
   directory of each touched file). This is the
   ``review_change_impact`` question, answered from the graph Sangam
   already builds.
3. Graph analysis — ``detect_hubs`` (graphify god-nodes: symbols
   with the most incoming calls) and ``surprising_links`` (call
   edges that cross top-level layers, i.e. bridges between parts of
   the codebase that rarely talk). Both cite their endpoints.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .. import code_graph


def refresh_if_stale(root: Path | str | None = None) -> dict:
    """Rebuild the code graph only when the fingerprint changed.
    The cache is populated by ``ensure_fresh_graph`` (``build_graph``
    alone does not cache), so freshness is always judged against
    the last served graph. Returns {stale, rebuilt, changed_files,
    files, symbols}."""
    root = Path(root) if root is not None else code_graph._workspace()
    cached = code_graph.cached_graph(root)
    if cached is None:
        graph, _warning = code_graph.ensure_fresh_graph(root)
        if graph is None:
            return {"stale": True, "rebuilt": False, "changed_files": [],
                    "files": 0, "symbols": 0, "error": "graph build failed"}
        return {"stale": True, "rebuilt": True,
                "changed_files": sorted((graph.get("fingerprint") or {}).keys()),
                "files": graph.get("files", 0),
                "symbols": len(graph.get("symbols") or {})}
    drift = code_graph.check_freshness(root, cached)
    if drift.get("fresh"):
        return {"stale": False, "rebuilt": False, "changed_files": [],
                "files": cached.get("files", 0),
                "symbols": len(cached.get("symbols") or {})}
    graph, _warning = code_graph.ensure_fresh_graph(root)
    if graph is None:
        return {"stale": True, "rebuilt": False,
                "changed_files": sorted(set(drift.get("added", []))
                                        | set(drift.get("removed", []))
                                        | set(drift.get("changed", []))),
                "files": cached.get("files", 0),
                "symbols": len(cached.get("symbols") or {}),
                "error": "rebuild failed; stale graph retained"}
    return {"stale": True, "rebuilt": True,
            "changed_files": sorted(set(drift.get("added", []))
                                    | set(drift.get("removed", []))
                                    | set(drift.get("changed", []))),
            "files": graph.get("files", 0),
            "symbols": len(graph.get("symbols") or {})}


def _layer(path: str) -> str:
    parts = Path(path).parts
    return parts[0] if parts else ""


def _is_test_file(path: str) -> bool:
    name = Path(path).name.lower()
    return name.startswith("test_") or name.endswith("_test.py") \
        or "/tests/" in path.replace("\\", "/") or name.startswith("test.")


def change_impact(symbol: str, graph: dict) -> dict:
    """Changed symbol (or file path) -> callers, tests, layers.

    ``symbol`` may be a qualified symbol id (``file.py#Class.method``)
    or a bare name matched by suffix; a file path matches every
    symbol defined in that file. Unknown symbols return empty lists
    with ``found: False`` — never invented callers."""
    symbols = graph.get("symbols") or {}
    edges = graph.get("edges") or []
    target_ids: set[str] = set()
    if symbol in symbols:
        target_ids.add(symbol)
    else:
        for sid, sym in symbols.items():
            if sid.endswith(f"#{symbol}") or sym.get("name") == symbol \
                    or (sym.get("file") == symbol):
                target_ids.add(sid)
    if not target_ids:
        return {"found": False, "symbol": symbol, "callers": [],
                "tests": [], "layers": []}
    callers: set[str] = set()
    caller_files: set[str] = set()
    for edge in edges:
        if edge.get("type") == "calls" and edge.get("to") in target_ids:
            callers.add(edge.get("from"))
            caller_files.add(edge.get("file", ""))
    tests = sorted({f for f in caller_files if f and _is_test_file(f)})
    layers = sorted({_layer(f) for f in caller_files if f})
    return {"found": True, "symbol": symbol,
            "callers": sorted(callers), "tests": tests, "layers": layers}


def detect_hubs(graph: dict, top_n: int = 5) -> list[dict]:
    """God-nodes: symbols ranked by incoming call count."""
    incoming: Counter = Counter()
    for edge in graph.get("edges") or []:
        if edge.get("type") == "calls" and edge.get("to"):
            incoming[edge["to"]] += 1
    symbols = graph.get("symbols") or {}
    hubs = []
    for symbol_id, count in incoming.most_common(top_n):
        sym = symbols.get(symbol_id) or {}
        hubs.append({"symbol": symbol_id,
                     "name": sym.get("name", symbol_id),
                     "file": sym.get("file", ""),
                     "incoming_calls": count})
    return hubs


def surprising_links(graph: dict, top_n: int = 10) -> list[dict]:
    """Call edges whose endpoints live in different top-level layers
    — bridges worth a second look. Each cites both endpoints."""
    links = []
    symbols = graph.get("symbols") or {}
    for edge in graph.get("edges") or []:
        if edge.get("type") != "calls":
            continue
        from_file = (symbols.get(edge.get("from")) or {}).get("file", "")
        to_file = (symbols.get(edge.get("to")) or {}).get("file", "")
        if from_file and to_file and _layer(from_file) != _layer(to_file):
            links.append({"from": edge.get("from"), "to": edge.get("to"),
                          "from_file": from_file, "to_file": to_file,
                          "from_layer": _layer(from_file),
                          "to_layer": _layer(to_file)})
        if len(links) >= top_n:
            break
    return links
