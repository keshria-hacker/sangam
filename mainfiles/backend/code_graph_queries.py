"""Graft's six query tools as Sangam code-graph tools (+ blast radius,
diff, and graph export). Pure functions over the dict graph built by
:mod:`code_graph`; no NetworkX, no new dependency.

Tools (Graft's surface, Sangam-native):
  find_code      plain-words query, lexical rank + personalised
                 PageRank re-rank ("lexical proposes, graph disposes")
  file_api       file outline: symbols, signatures, spans, imports
  find_all       regex over symbol names / signatures / files
  repo_map       directory map with per-file symbol counts
  trace_calls    callers/callees BFS, in/out/both, depth-limited;
                 ``contains`` edges are excluded from walks (Graft's
                 relations rule — a file contains everything, so
                 walking it turns every file into a false hub)
  check_freshness fingerprint drift report (delegates to code_graph)

Plus (Graphify-shaped): ``affected`` blast radius (callers + the
file's ``defines``/``contains`` edge — without it a symbol query is
blind in exactly the languages where only the file defines the
symbol), ``graph_diff`` on id + body_hash, and JSON / standalone-HTML
exports (the Knowledge Export gap: it exported memories JSON only).
"""
from __future__ import annotations

import html as _html
import json
import math
import re
from collections import deque
from pathlib import Path
from typing import Any

from .code_graph import check_freshness as _check_freshness
from .code_graph import resolve_symbol

WALK_RELATIONS = {"calls", "imports"}
PAGERANK_ALPHA = 0.25
PAGERANK_ITERS = 25


# ------------------------------------------------------------------ helpers
def _call_adj(graph: dict) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    fwd: dict[str, list[str]] = {}
    rev: dict[str, list[str]] = {}
    for e in graph["edges"]:
        if e["type"] != "calls":
            continue
        fwd.setdefault(e["from"], []).append(e["to"])
        rev.setdefault(e["to"], []).append(e["from"])
    return fwd, rev


def _read_excerpt(root: Path | None, sym: dict, max_lines: int = 8) -> str:
    if root is None:
        return ""
    try:
        lines = (root / sym["file"]).read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError):
        return ""
    start = max(0, sym["line"] - 1)
    return "\n".join(lines[start:start + max_lines])


# ------------------------------------------------------------------ find_code
def _lexical_score(query: str, sym: dict) -> float:
    """Token overlap over name + qualname + signature + file."""
    qtok = set(re.findall(r"[a-z0-9_]+", query.lower()))
    if not qtok:
        return 0.0
    hay = " ".join([sym.get("name", ""), sym.get("qualname", ""),
                    sym.get("signature", ""), sym.get("file", "")]).lower()
    htok = set(re.findall(r"[a-z0-9_]+", hay))
    overlap = len(qtok & htok)
    if overlap == 0:
        return 0.0
    score = overlap / len(qtok)
    if sym.get("name", "").lower() in qtok:
        score += 0.5
    if sym.get("qualname", "").lower() == query.lower().strip():
        score += 1.0
    return score


def _personalised_pagerank(graph: dict, seeds: dict[str, float]) -> dict[str, float]:
    """Deterministic PageRank, restart alpha, fixed iterations, seeded
    by lexical scores. Nodes with no out-edges distribute to seeds."""
    nodes = list(graph["symbols"].keys())
    if not nodes:
        return {}
    fwd, _ = _call_adj(graph)
    total = sum(seeds.values()) or 1.0
    rank = {n: seeds.get(n, 0.0) / total for n in nodes}
    seed_vec = {n: seeds.get(n, 0.0) / total for n in nodes}
    for _ in range(PAGERANK_ITERS):
        nxt = {n: PAGERANK_ALPHA * seed_vec[n] for n in nodes}
        for n in nodes:
            outs = fwd.get(n, [])
            share = (1 - PAGERANK_ALPHA) * rank[n]
            if outs:
                for t in outs:
                    if t in nxt:
                        nxt[t] += share / len(outs)
            else:
                for m in nodes:
                    nxt[m] += share * seed_vec[m]
        rank = nxt
    return rank


def find_code(graph: dict, query: str, top_k: int = 10,
              root: Path | None = None) -> dict:
    """Plain-words code search: lexical rank proposes, PageRank disposes."""
    scored = []
    for sid, sym in graph["symbols"].items():
        lex = _lexical_score(query, sym)
        if lex > 0:
            scored.append((sid, lex))
    if not scored:
        return {"query": query, "results": []}
    pr = _personalised_pagerank(graph, {sid: lex for sid, lex in scored})
    results = []
    for sid, lex in scored:
        sym = graph["symbols"][sid]
        results.append({
            "symbol": sid, "name": sym["name"], "kind": sym["kind"],
            "file": sym["file"], "line": sym["line"],
            "end_line": sym["end_line"], "signature": sym["signature"],
            "lexical_score": round(lex, 4),
            "pagerank_score": round(pr.get(sid, 0.0), 6),
            "score": round(lex + pr.get(sid, 0.0), 6),
            "excerpt": _read_excerpt(root, sym) if root is not None else "",
        })
    results.sort(key=lambda r: r["score"], reverse=True)
    return {"query": query, "results": results[:top_k]}


# ------------------------------------------------------------------ file_api
def file_api(graph: dict, file: str) -> dict:
    """Outline/API of one file: its symbols, imports, outgoing calls."""
    rel = file[5:] if file.startswith("file:") else file
    syms = [dict({"symbol": sid}, **s)
            for sid, s in graph["symbols"].items() if s["file"] == rel]
    syms.sort(key=lambda s: s["line"])
    imports = [e for e in graph["edges"]
               if e["type"] == "imports" and e["file"] == rel]
    calls_out = [e for e in graph["edges"]
                 if e["type"] == "calls" and e["file"] == rel]
    if not syms and not imports and not calls_out:
        return {"error": f"No such file in graph: {file}"}
    return {"file": rel, "symbols": syms, "imports": imports,
            "call_count": len(calls_out),
            "calls": [{"from": e["from"], "to": e["to"],
                       "confidence": e["confidence"]} for e in calls_out]}


# ------------------------------------------------------------------ find_all
def find_all(graph: dict, pattern: str) -> dict:
    """Regex over symbol names, signatures, and file paths."""
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        return {"error": f"Invalid regex: {exc}", "results": []}
    results = []
    for sid, sym in graph["symbols"].items():
        hay = " ".join([sym["name"], sym["qualname"], sym["signature"], sym["file"]])
        if rx.search(hay):
            results.append({"symbol": sid, "name": sym["name"],
                            "kind": sym["kind"], "file": sym["file"],
                            "line": sym["line"], "signature": sym["signature"]})
    return {"pattern": pattern, "count": len(results), "results": results}


# ------------------------------------------------------------------ repo_map
def repo_map(graph: dict) -> dict:
    """Directory map: per-directory file counts and symbol counts."""
    tree: dict[str, Any] = {}
    for node in graph.get("file_nodes") or []:
        path = node["path"]
        parts = path.split("/")[:-1]
        cur = tree
        for part in parts:
            cur = cur.setdefault(part, {"__files__": []})
        cur.setdefault("__files__", []).append(path)
    sym_counts: dict[str, int] = {}
    for sym in graph["symbols"].values():
        sym_counts[sym["file"]] = sym_counts.get(sym["file"], 0) + 1

    def _summarize(node: dict, prefix: str) -> dict:
        files = node.get("__files__", [])
        out = {"files": len(files),
               "symbols": sum(sym_counts.get(f, 0) for f in files),
               "children": {}}
        for name, child in node.items():
            if name == "__files__":
                continue
            out["children"][name] = _summarize(
                child, f"{prefix}{name}/")
            out["files"] += out["children"][name]["files"]
            out["symbols"] += out["children"][name]["symbols"]
        return out

    return {"root": _summarize(tree, ""),
            "files": sorted(sym_counts.keys()),
            "total_symbols": len(graph["symbols"])}


# ------------------------------------------------------------------ trace
def trace_calls(graph: dict, symbol: str, direction: str = "out",
                depth: int | str = 1) -> dict:
    """Follow calls in/out/both from a symbol. ``depth`` is an int or
    ``"all"``. ``contains`` edges are never walked."""
    sid, cands = resolve_symbol(symbol, graph)
    if cands:
        return {"error": f"Ambiguous symbol: {symbol}", "candidates": cands}
    if not sid:
        return {"error": f"Symbol not found: {symbol}"}
    fwd, rev = _call_adj(graph)
    max_depth = math.inf if depth == "all" else int(depth)
    if direction not in ("in", "out", "both"):
        return {"error": f"direction must be in/out/both, got {direction!r}"}
    adj: dict[str, list[str]] = {}
    if direction in ("out", "both"):
        for k, v in fwd.items():
            adj.setdefault(k, []).extend(v)
    if direction in ("in", "both"):
        for k, v in rev.items():
            adj.setdefault(k, []).extend(v)
    seen = {sid}
    levels: dict[str, int] = {sid: 0}
    q = deque([(sid, 0)])
    while q:
        node, d = q.popleft()
        if d >= max_depth:
            continue
        for nxt in adj.get(node, []):
            if nxt not in seen:
                seen.add(nxt)
                levels[nxt] = d + 1
                q.append((nxt, d + 1))
    nodes = [{"symbol": n, **graph["symbols"][n], "distance": levels[n]}
             for n in seen if n in graph["symbols"]]
    nodes.sort(key=lambda n: (n["distance"], n["symbol"]))
    return {"symbol": sid, "direction": direction, "depth": depth,
            "nodes": nodes, "count": len(nodes)}


# ------------------------------------------------------------------ freshness
def check_freshness_tool(root: Path | str | None, graph: dict | None) -> dict:
    """Graft's ``check`` as a tool: added/removed/changed/stale."""
    return _check_freshness(root, graph)


# ------------------------------------------------------------------ affected
def affected(graph: dict, symbol: str) -> dict:
    """Blast radius: callers (transitive), the defining file, and
    importers of that file. Includes the ``defines``/``contains`` edge
    — without it, file-only relationships are invisible."""
    sid, cands = resolve_symbol(symbol, graph)
    if cands:
        return {"error": f"Ambiguous symbol: {symbol}", "candidates": cands}
    if not sid:
        return {"error": f"Symbol not found: {symbol}"}
    sym = graph["symbols"][sid]
    callers = trace_calls(graph, sid, direction="in", depth="all")
    caller_ids = [n["symbol"] for n in callers.get("nodes", [])
                  if n["symbol"] != sid]
    defining_file = f"file:{sym['file']}"
    importers = sorted({e["from"] for e in graph["edges"]
                        if e["type"] == "imports" and e["to"] == defining_file})
    return {"symbol": sid, "defining_file": sym["file"],
            "callers_transitive": caller_ids,
            "caller_count": len(caller_ids),
            "importers_of_defining_file": importers}


# ------------------------------------------------------------------ diff
def graph_diff(old: dict, new: dict) -> dict:
    """Diff on symbol id + body_hash (Graft's check shape):
    added / removed / changed / stale(summary outdated — here: any
    symbol whose body changed)."""
    old_syms, new_syms = old.get("symbols", {}), new.get("symbols", {})
    added = sorted(set(new_syms) - set(old_syms))
    removed = sorted(set(old_syms) - set(new_syms))
    changed = sorted(sid for sid in set(old_syms) & set(new_syms)
                     if old_syms[sid].get("body_hash") != new_syms[sid].get("body_hash"))
    return {"added": added, "removed": removed, "changed": changed,
            "counts": {"added": len(added), "removed": len(removed),
                       "changed": len(changed)}}


# ------------------------------------------------------------------ exports
def export_graph_json(graph: dict) -> dict:
    """JSON export: nodes + directed edges (direction is explicit in
    from/to — Graphify's directed-but-undirected JSON trap is NOT
    copied: no arc-order guessing on load)."""
    nodes = []
    for n in graph.get("file_nodes") or []:
        nodes.append({"id": n["id"], "type": "file", "label": n["path"],
                      "language": n.get("language")})
    for sid, s in graph["symbols"].items():
        nodes.append({"id": sid, "type": "symbol", "label": s["qualname"],
                      "kind": s["kind"], "file": s["file"],
                      "line": s["line"], "end_line": s["end_line"],
                      "signature": s["signature"]})
    edges = [{"from": e["from"], "to": e["to"], "type": e["type"],
              "confidence": e.get("confidence")} for e in graph["edges"]]
    return {"directed": True, "schema_version": graph.get("schema_version"),
            "stats": graph.get("stats"), "nodes": nodes, "edges": edges}


def export_graph_html(graph: dict, title: str = "Sangam code graph") -> str:
    """Standalone HTML viewer export (Graft viz --export pattern):
    CSS + JS + graph data inlined, ``file://``-openable, no external
    fetches. Node cap is surfaced, never silent."""
    data = export_graph_json(graph)
    total = len(data["nodes"])
    shown = data["nodes"][:2000]
    data["nodes"] = shown
    payload = json.dumps(data)
    note = (f"Showing {len(shown)} of {total} nodes."
            if total > len(shown) else f"{total} nodes.")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{_html.escape(title)}</title>
<style>body{{font-family:system-ui,sans-serif;margin:2em}}
table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:4px 8px}}
input{{width:100%;padding:6px;margin:8px 0}}</style></head>
<body><h1>{_html.escape(title)}</h1><p>{_html.escape(note)}</p>
<input id="q" placeholder="Filter symbols by name…">
<table><thead><tr><th>Symbol</th><th>Kind</th><th>File</th><th>Line</th></tr></thead>
<tbody id="rows"></tbody></table>
<script>const DATA = {payload};
const rows = document.getElementById('rows');
function render(filter) {{
  rows.innerHTML = '';
  for (const n of DATA.nodes) {{
    if (n.type !== 'symbol') continue;
    if (filter && !n.label.toLowerCase().includes(filter)) continue;
    const tr = document.createElement('tr');
    tr.innerHTML = '<td>' + n.label + '</td><td>' + n.kind + '</td><td>' + n.file + '</td><td>' + n.line + '</td>';
    rows.appendChild(tr);
  }}
}}
document.getElementById('q').addEventListener('input', e => render(e.target.value.toLowerCase()));
render('');
</script></body></html>"""


# ------------------------------------------------------------------ A5 additions
# Call-path tracing already exists as ``trace_calls`` / ``find_path``
# (in code_graph.py); the four functions below close the remaining
# Cluster-G gaps without touching the existing tools: circular imports,
# an architecture overview (directory + language + hubs), file/symbol
# change impact, and code search v2 (grep speed + graph intelligence).

def circular_imports(graph: dict) -> dict:
    """Cycles in the file->file import graph (module: targets ignored).

    Deterministic DFS; each cycle is reported once, in canonical
    rotation (smallest file id first), sorted.
    """
    adj: dict[str, list[str]] = {}
    for e in graph.get("edges") or []:
        if e["type"] != "imports":
            continue
        src, dst = e["from"], e["to"]
        if not dst.startswith("file:"):
            continue
        adj.setdefault(src, [])
        if dst not in adj[src]:
            adj[src].append(dst)
    for k in adj:
        adj[k].sort()
    cycles: set[tuple[str, ...]] = set()
    visited: set[str] = set()

    def _dfs(node: str, stack: list[str]) -> None:
        visited.add(node)
        stack.append(node)
        for nxt in adj.get(node, []):
            if nxt in stack:
                raw = stack[stack.index(nxt):]
                rot = min(range(len(raw)),
                          key=lambda i: raw[i:])
                cyc = tuple(raw[rot:] + raw[:rot])
                cycles.add(cyc)
            elif nxt not in visited:
                _dfs(nxt, stack)
        stack.pop()

    for start in sorted(adj):
        if start not in visited:
            _dfs(start, [])
    out = [list(c) for c in sorted(cycles)]
    return {"cycles": out, "count": len(out)}


def architecture_overview(graph: dict) -> dict:
    """Architecture overview: languages, directories, hubs, entry points.

    Hubs are symbols ranked by caller count; entry points are exported
    symbols with no callers (the public surface). No LLM, no guessing:
    every number is counted from the graph.
    """
    from collections import Counter
    callers: Counter = Counter()
    for e in graph.get("edges") or []:
        if e["type"] == "calls":
            callers[e["to"]] += 1
    syms = graph.get("symbols") or {}
    hubs = [{"symbol": sid, "callers": callers[sid],
             "kind": syms[sid]["kind"], "file": syms[sid]["file"]}
            for sid in sorted(callers, key=lambda s: (-callers[s], s))[:10]]
    entry = sorted(sid for sid, s in syms.items()
                   if s.get("exported") and callers.get(sid, 0) == 0)
    dirs: dict[str, dict] = {}
    for node in graph.get("file_nodes") or []:
        d = node["path"].rsplit("/", 1)[0] if "/" in node["path"] else "."
        dirs.setdefault(d, {"files": 0, "language": node.get("language")})
        dirs[d]["files"] += 1
    return {
        "files": graph.get("files", len(graph.get("file_nodes") or [])),
        "symbols": len(syms),
        "edges": len(graph.get("edges") or []),
        "languages": (graph.get("stats") or {}).get("languages", {}),
        "directories": dirs,
        "hubs": hubs,
        "entry_points": entry[:50],
        "entry_point_count": len(entry),
    }


def change_impact(graph: dict, target: str) -> dict:
    """Change impact for a symbol OR a whole file (``file:<relpath>``).

    Symbol: ``affected`` (transitive callers + importers of its file).
    File: every symbol defined in the file, their transitive callers,
    and every file importing this file. Freshness is NOT re-checked
    here; callers use ``ensure_fresh_graph`` first (routes do).
    """
    if target.startswith("file:"):
        rel = target[5:]
        syms = sorted(sid for sid, s in (graph.get("symbols") or {}).items()
                      if s["file"] == rel)
        callers: set[str] = set()
        for sid in syms:
            out = affected(graph, sid)
            callers.update(out.get("callers_transitive", []))
        importers = sorted({e["from"] for e in graph.get("edges") or []
                            if e["type"] == "imports" and e["to"] == target})
        return {"target": target, "symbols_in_file": syms,
                "callers_transitive": sorted(callers),
                "caller_count": len(callers),
                "importers_of_file": importers}
    out = affected(graph, target)
    out["target"] = target
    return out


def search_code_v2(graph: dict, query: str, root: Path | None = None,
                   regex: bool = False, top_k: int = 10) -> dict:
    """Code search v2: grep speed + graph intelligence.

    Grep scans file contents (substring, or regex when ``regex=True``);
    the graph ranks symbols (``find_code``). ``merged`` ranks graph
    symbols whose file also matched grep first, then remaining graph
    results, then grep-only file hits — so a hit is never graph-only
    guesswork and never grep-only noise. With ``root=None`` only the
    graph half runs (grep needs a filesystem root) and that is stated
    in the output instead of silently degrading.
    """
    graph_out = find_code(graph, query, top_k=top_k)
    grep_hits: list[dict] = []
    grep_files: set[str] = set()
    if root is not None:
        try:
            rx = re.compile(query) if regex else None
        except re.error as exc:
            return {"query": query, "error": f"Invalid regex: {exc}",
                    "graph": graph_out["results"], "grep": [], "merged": []}
        needle = query.lower()
        for node in graph.get("file_nodes") or []:
            path = root / node["path"]
            try:
                lines = path.read_text(encoding="utf-8").split("\n")
            except (OSError, UnicodeDecodeError):
                continue
            for i, line in enumerate(lines, 1):
                hit = bool(rx.search(line)) if rx else needle in line.lower()
                if hit:
                    grep_hits.append({"file": node["path"], "line": i,
                                      "text": line.strip()[:200]})
                    grep_files.add(node["path"])
    merged: list[dict] = []
    for r in graph_out["results"]:
        merged.append({**r, "source": "graph+grep"
                       if r["file"] in grep_files else "graph"})
    merged.sort(key=lambda r: (0 if r["source"] == "graph+grep" else 1,
                               -r["score"]))
    for h in grep_hits[:top_k]:
        if not any(m.get("file") == h["file"] and m.get("line") == h["line"]
                   for m in merged):
            merged.append({**h, "source": "grep", "score": 0.0})
    return {"query": query, "graph": graph_out["results"],
            "grep": grep_hits[:top_k * 5],
            "grep_file_count": len(grep_files),
            "merged": merged[:top_k],
            "grep_enabled": root is not None}
