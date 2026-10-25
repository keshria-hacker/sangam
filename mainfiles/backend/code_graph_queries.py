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
# Batch 13: Graft's lexical half — IDF + BM25 over the symbol text
# (name + qualname + signature + file) plus a test-path de-rank.
# Honest scope note: full definition bodies are NOT stored in the
# graph (only body_hash), so the "body field" here is the symbol
# text above, not the function body — BM25 length normalisation
# still stops a sprawling signature/file path from outranking a
# tight name match by word count alone.
BM25_K1 = 1.2
BM25_B = 0.75
TEST_DERANK = 0.35
_TEST_PATH = re.compile(r"(^|/)(test_|tests?/|.*_test\.py|.*\.test\.[a-z]+)$")


def _symbol_tokens(sym: dict) -> list[str]:
    hay = " ".join([sym.get("name", ""), sym.get("qualname", ""),
                    sym.get("signature", ""), sym.get("file", "")]).lower()
    return re.findall(r"[a-z0-9_]+", hay)


def _is_test_path(file: str) -> bool:
    f = (file or "").replace("\\", "/")
    return bool(_TEST_PATH.search(f)) or "/test/" in f or f.startswith("test_")


def _bm25_scores(graph: dict, query: str) -> dict[str, float]:
    """IDF + BM25 per symbol id. Returns {} when the query has no tokens."""
    qtok = re.findall(r"[a-z0-9_]+", query.lower())
    if not qtok:
        return {}
    docs: dict[str, list[str]] = {}
    df: dict[str, int] = {}
    for sid, sym in graph["symbols"].items():
        toks = _symbol_tokens(sym)
        docs[sid] = toks
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    n_docs = len(docs) or 1
    avg_len = sum(len(t) for t in docs.values()) / n_docs
    scores: dict[str, float] = {}
    for sid, toks in docs.items():
        if not toks:
            continue
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        score = 0.0
        for term in set(qtok):
            if term not in tf:
                continue
            idf = math.log(1 + n_docs / (1 + df.get(term, 0)))
            denom = tf[term] + BM25_K1 * (1 - BM25_B + BM25_B * len(toks) / max(avg_len, 1))
            score += idf * tf[term] * (BM25_K1 + 1) / denom
        if score > 0:
            sym = graph["symbols"][sid]
            if sym.get("name", "").lower() in qtok:
                score += 0.5
            if sym.get("qualname", "").lower() == query.lower().strip():
                score += 1.0
            if _is_test_path(sym.get("file", "")):
                score *= TEST_DERANK
            scores[sid] = score
    return scores


def _lexical_score(query: str, sym: dict) -> float:
    """Back-compat wrapper: plain token overlap for a single symbol
    (used by older callers/tests); find_code uses _bm25_scores."""
    qtok = set(re.findall(r"[a-z0-9_]+", query.lower()))
    if not qtok:
        return 0.0
    htok = set(_symbol_tokens(sym))
    overlap = len(qtok & htok)
    if overlap == 0:
        return 0.0
    score = overlap / len(qtok)
    if sym.get("name", "").lower() in qtok:
        score += 0.5
    if sym.get("qualname", "").lower() == query.lower().strip():
        score += 1.0
    return score


def evidence_block(graph: dict, results: list[dict] | None = None) -> dict:
    """REA evidence discipline for code answers: sources with
    file:line + body_hash, what was NOT searched (skipped dirs,
    dropped ambiguous/unresolved calls, dropped extends, file cap),
    and a freshness pointer. Unknown coverage is stated as unknown:
    this block never claims the whole repo was searched when the
    graph was capped or files were skipped."""
    stats = graph.get("stats") or {}
    sources = []
    for r in results or []:
        sym = graph["symbols"].get(r.get("symbol", ""), {}) if isinstance(r, dict) else {}
        sources.append({"symbol": r.get("symbol") if isinstance(r, dict) else None,
                        "file": r.get("file") if isinstance(r, dict) else None,
                        "line": r.get("line") if isinstance(r, dict) else None,
                        "body_hash": sym.get("body_hash")})
    return {"sources": sources,
            "limitations": {
                "dropped_ambiguous_calls": stats.get("dropped_ambiguous", 0),
                "dropped_unresolved_calls": stats.get("dropped_unresolved", 0),
                "dropped_extends": stats.get("dropped_extends", 0),
                "skipped_dirs": ["__pycache__", ".venv", "node_modules", ".git",
                               "dist", "build", ".next"],
                "files_scanned": stats.get("files_scanned"),
                "files_capped": stats.get("files_capped", False),
                "note": ("Symbols that were ambiguous or unresolvable were "
                         "dropped, never guessed. Use /knowledge/graph/check "
                         "for fingerprint drift vs this graph."),
            },
            "freshness": ("Graph fingerprint is stored on the graph; "
                          "drift is reported by /knowledge/graph/check, "
                          "not claimed here.")}


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
    """Plain-words code search: BM25/IDF lexical rank proposes,
    PageRank disposes. ``lexical_score`` is now the BM25 score
    (test paths de-ranked 0.35x); results carry an evidence block."""
    bm25 = _bm25_scores(graph, query)
    if not bm25:
        return {"query": query, "results": [], "evidence": evidence_block(graph, [])}
    pr = _personalised_pagerank(graph, bm25)
    results = []
    for sid, lex in bm25.items():
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
    results = results[:top_k]
    return {"query": query, "results": results, "evidence": evidence_block(graph, results)}


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
            "importers_of_defining_file": importers,
            "evidence": evidence_block(graph, [{"symbol": sid, "file": sym["file"],
                                                "line": sym["line"]}])}


# ------------------------------------------------- Batch 13: impact/orphans
def find_orphans(graph: dict) -> dict:
    """Dead-code candidates (gstack deslop + code-graph depth): symbols
    with no incoming ``calls`` edge, not exported, not a ``main``
    entry point. Candidates only — a symbol can be a real entry
    point (CLI, handler, test) without a caller in the graph, so
    nothing here is deleted automatically."""
    called = {e["to"] for e in graph["edges"] if e["type"] == "calls"}
    orphans = []
    for sid, sym in graph["symbols"].items():
        if sid in called:
            continue
        if sym.get("exported"):
            continue
        if sym.get("name") in ("main", "__main__"):
            continue
        if sym.get("kind") not in ("function", "method"):
            continue
        orphans.append({"symbol": sid, "name": sym["name"], "kind": sym["kind"],
                        "file": sym["file"], "line": sym["line"],
                        "note": "No caller in the graph and not exported — "
                                "verify it is not an entry point before removing."})
    orphans.sort(key=lambda o: (o["file"], o["line"]))
    return {"count": len(orphans), "orphans": orphans,
            "evidence": evidence_block(graph, orphans)}


def impact_analysis(graph: dict, symbol: str) -> dict:
    """Cross-file impact analysis for one symbol: blast radius plus
    the files touched and a plain-language risk note. This is the
    'explain this code change' building block: call it for each
    symbol a diff touches (see explain_change)."""
    base = affected(graph, symbol)
    if base.get("error"):
        base["evidence"] = evidence_block(graph, [])
        return base
    caller_files = sorted({graph["symbols"][c]["file"]
                           for c in base["callers_transitive"]
                           if c in graph["symbols"]})
    files_touched = sorted({base["defining_file"]} | set(caller_files))
    count = base["caller_count"]
    if count == 0:
        risk = "No callers in the graph — change is locally contained (but see orphans: it may be dead code)."
    elif len(files_touched) == 1:
        risk = f"{count} caller(s) in the same file — change needs those call sites checked."
    else:
        risk = (f"{count} caller(s) across {len(files_touched)} files — "
                "change needs every listed call site checked before merge.")
    base["files_touched"] = files_touched
    base["risk_note"] = risk
    base["evidence"] = evidence_block(
        graph, [{"symbol": base["symbol"], "file": base["defining_file"],
                 "line": graph["symbols"][base["symbol"]]["line"]}])
    return base


def explain_change(graph: dict, diff_text: str) -> dict:
    """Explain a code change from a unified diff: files touched,
    symbols in those files, and each symbol's impact (callers).
    Symbols are found by file, never guessed from diff prose: a file
    with no graph symbols reports an empty symbol list with a
    limitation note, not invented symbols. Added-line identifiers
    that match a symbol name in a touched file are listed as
    ``mentioned_symbols`` (candidates, not proof of change)."""
    diff_text = diff_text or ""
    files: list[str] = []
    for m in re.finditer(r"^\+{3}\s+b/(.+)$", diff_text, re.MULTILINE):
        files.append(m.group(1).strip())
    files = sorted(set(files))
    symbols_by_file: dict[str, list[str]] = {}
    for sid, sym in graph["symbols"].items():
        if sym["file"] in files:
            symbols_by_file.setdefault(sym["file"], []).append(sid)
    added_names: set[str] = set()
    for m in re.finditer(r"^\+[^+].*$", diff_text, re.MULTILINE):
        added_names.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", m.group(0)))
    mentioned: list[str] = []
    for sid, sym in graph["symbols"].items():
        if sym["file"] in files and sym["name"] in added_names:
            mentioned.append(sid)
    impacts = {}
    for sid in mentioned:
        impacts[sid] = impact_analysis(graph, sid)
    return {"files": files, "symbols_in_touched_files": symbols_by_file,
            "mentioned_symbols": sorted(mentioned), "impacts": impacts,
            "limitations": ("Only symbols already in the graph are reported. "
                            "New symbols added by this diff are not in the graph "
                            "until it is rebuilt; mentioned_symbols matches "
                            "added-line identifiers against existing symbols only."),
            "evidence": evidence_block(graph, [])}


def layering_check(graph: dict, layers: list[str]) -> dict:
    """Layering violations for a caller-supplied layer order.

    ``layers`` is ordered high -> low (e.g. ["app/", "domain/",
    "infra/"]). A call is a violation when the callee sits in a
    HIGHER layer than the caller (a lower layer depending upward).
    Same-layer and downward calls are fine. Files matching no layer
    are reported as unlayered, never assigned a layer by guessing."""
    layers = [str(layer) for layer in (layers or [])]
    if not layers:
        return {"error": "layers must be a non-empty ordered list (high -> low)"}

    def _layer_of(file: str) -> int | None:
        for i, prefix in enumerate(layers):
            if file.startswith(prefix):
                return i
        return None

    violations: list[dict] = []
    unlayered: set[str] = set()
    for e in graph["edges"]:
        if e["type"] != "calls":
            continue
        caller = graph["symbols"].get(e["from"], {})
        callee = graph["symbols"].get(e["to"], {})
        if not caller or not callee:
            continue
        cl, el = _layer_of(caller.get("file", "")), _layer_of(callee.get("file", ""))
        if cl is None:
            unlayered.add(caller.get("file", ""))
        if el is None:
            unlayered.add(callee.get("file", ""))
        if cl is not None and el is not None and el < cl:
            violations.append({"from": e["from"], "to": e["to"],
                               "caller_file": caller["file"],
                               "callee_file": callee["file"],
                               "note": "Lower layer calls a higher layer."})
    return {"layers": layers, "violations": violations,
            "violation_count": len(violations),
            "unlayered_files": sorted(unlayered),
            "evidence": evidence_block(graph, [])}


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
