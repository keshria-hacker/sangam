"""
Code map — multi-language codebase knowledge graph (Graphify-shaped,
Sangam-native; Graft's resolver rule + fingerprint gate).

Pipeline (Graphify's shape, not its code — no NetworkX):
``extract -> validate -> build``, with a cache namespaced by
extractor version + schema version + grammar fingerprint.

Languages: Python via stdlib ``ast``; JS/TS via the pure-Python
scanner in :mod:`code_extract_js`; Go, Rust, and Java via the
hand-written regex scanners in :mod:`code_extract_extra`. No
tree-sitter, no 160-language claim: exactly Python, JavaScript /
TypeScript, Go, Rust, and Java are extracted, each with a test
(see tests/test_a5_spec_qa.py). The cache namespace records the
extractor ids so a grammar swap invalidates.

Build-time resolution (Graft's rule, never guessed):
  same-file unique match  -> EXTRACTED
  cross-file unique match -> INFERRED
  ambiguous (2+ candidates) or unresolvable -> DROPPED + counted
  (``stats.dropped_ambiguous`` / ``stats.dropped_unresolved``,
  capped detail list in ``stats.dropped``)

Every symbol carries: kind, file, line, end_line (span), signature,
short name, qualname, ``exported``, ``body_hash`` (sha256 of the
definition text), and ``calls`` (resolved target symbol ids — this is
what the unified graph consumes; the old dead branch read
``sym["calls"]``/``sym["name"]`` that the old extractor never emitted).

Freshness (Graft's fingerprint gate): ``fingerprint_for`` records
``{file: [size, mtime, sha256]}``. ``ensure_fresh_graph`` probes on
every call (stat only; only changed files are re-hashed) and rebuilds
on drift. A rebuild failure NEVER fails a query: the stale graph is
served with a warning string.

Backward compatibility: ``build_graph`` / ``explain`` / ``find_path``
keep their old signatures. Symbol ids changed from bare qualnames to
``<relpath>#<qualname>`` (the old keys collapsed same-name symbols
across files); ``explain``/``find_path`` resolve by exact id, unique
qualname, or unique suffix — and return the candidate list instead
of silently collapsing when a name is ambiguous.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from .code_extract_extra import EXTRA_EXTRACTOR_ID, EXTRACTORS, LANGUAGE_FOR_SUFFIX
from .code_extract_js import JS_EXTRACTOR_ID, extract_js_file

SCHEMA_VERSION = 1
EXTRACTOR_VERSION = "codegraph-v3"
CACHE_NAMESPACE = (f"v{SCHEMA_VERSION}-{EXTRACTOR_VERSION}-js:{JS_EXTRACTOR_ID}"
                     f"-extra:{EXTRA_EXTRACTOR_ID}")
VALID_CONFIDENCES = {"EXTRACTED", "INFERRED", "AMBIGUOUS"}

JS_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
PY_SUFFIXES = {".py"}
EXTRA_SUFFIXES = set(EXTRACTORS)
SKIP_DIRS = {"__pycache__", ".venv", "node_modules", ".git", "dist", "build", ".next"}

MODULE_CALLER = "<module>"


def _workspace() -> Path:
    from .tools.builtin import _get_workspace_root
    return _get_workspace_root()


def _symbol_id(rel: str, qualname: str) -> str:
    return f"{rel}#{qualname}"


def _file_id(rel: str) -> str:
    return f"file:{rel}"


# ------------------------------------------------------------------ Python
class _PyVisitor(ast.NodeVisitor):
    def __init__(self, file: str, lines: list[str], tree: ast.AST):
        self.file = file
        self.lines = lines
        self.tree = tree
        self.defs: list[dict] = []
        self.calls: list[tuple[str, str, int]] = []  # (caller, callee, line)
        self.imports: list[dict] = []
        self._stack: list[str] = []
        self._all: set[str] | None = None

    def _name(self, node) -> str:
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))

    def _signature(self, node) -> str:
        try:
            args = ast.unparse(node.args)
        except Exception:
            args = ""
        sig = f"{node.name}({args})"
        try:
            if node.returns is not None:
                sig += f" -> {ast.unparse(node.returns)}"
        except Exception:
            pass
        return sig[:300]

    def _record(self, node, kind: str):
        qn = ".".join([*self._stack, node.name])
        top_level = len(self._stack) == 0
        segment = None
        try:
            segment = ast.get_source_segment("\n".join(self.lines), node)
        except Exception:
            segment = None
        if segment is None:
            segment = "\n".join(self.lines[node.lineno - 1:getattr(node, "end_lineno", node.lineno) or node.lineno])
        exported = top_level and not node.name.startswith("_")
        self.defs.append({
            "name": node.name, "qualname": qn, "kind": kind,
            "line": node.lineno,
            "end_line": getattr(node, "end_lineno", None) or node.lineno,
            "signature": self._signature(node) if kind in ("function", "method") else f"class {node.name}",
            "exported": exported,
            "body_hash": hashlib.sha256(segment.encode("utf-8")).hexdigest(),
        })

    def visit_FunctionDef(self, node):
        kind = "method" if self._stack else "function"
        self._record(node, kind)
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self._record(node, "class")
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_Call(self, node):
        callee = self._name(node.func)
        caller = ".".join(self._stack) or MODULE_CALLER
        if callee:
            self.calls.append((caller, callee, node.lineno))
        self.generic_visit(node)

    def visit_Import(self, node):
        for a in node.names:
            self.imports.append({"module": a.name,
                                 "names": [a.asname or a.name.split(".")[0]],
                                 "line": node.lineno})

    def visit_ImportFrom(self, node):
        if node.module:
            names = [a.asname or a.name for a in node.names]
            self.imports.append({"module": node.module, "names": names,
                                 "line": node.lineno, "level": node.level or 0})


def _extract_python(rel: str, text: str) -> dict:
    lines = text.split("\n")
    tree = ast.parse(text)
    v = _PyVisitor(rel, lines, tree)
    v.visit(tree)
    # __all__ marks exports explicitly.
    all_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__all__" \
                        and isinstance(node.value, (ast.List, ast.Tuple)):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            all_names.add(elt.value)
    if all_names:
        for d in v.defs:
            if d["qualname"] in all_names:
                d["exported"] = True
    return {"defs": v.defs, "calls": v.calls,
            "imports": [{k: imp[k] for k in ("module", "names", "line") if k in imp}
                        for imp in v.imports]}


# ------------------------------------------------------------------ discovery
def discover_files(root: Path) -> list[Path]:
    """Source files under root, sorted, skipping vendored/build dirs."""
    found: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix in PY_SUFFIXES or p.suffix in JS_SUFFIXES \
                or p.suffix in EXTRA_SUFFIXES:
            found.append(p)
    return found


def _extract_file(path: Path, rel: str) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        if path.suffix in PY_SUFFIXES:
            return _extract_python(rel, text)
        if path.suffix in EXTRA_SUFFIXES:
            return EXTRACTORS[path.suffix](rel, text)
        return extract_js_file(rel, text)
    except (SyntaxError, ValueError, RecursionError):
        return None


# ------------------------------------------------------------------ resolution
def _resolve_call(caller_file: str, callee: str, by_short: dict, by_qual: dict,
                  file_symbols: dict) -> tuple[str | None, str | None]:
    """Graft's rule. Returns (target_id, confidence) or (None, reason).

    Owner-qualified exact match in the same file wins first; then
    same-file unique short-name (EXTRACTED); then cross-file unique
    (INFERRED); anything else is dropped, never guessed.
    """
    parts = callee.split(".")
    short = parts[-1]
    cands = by_short.get(short, [])
    if not cands:
        return None, "unresolved"
    # Owner-qualified: qualname == dotted callee, same file first.
    if len(parts) >= 2:
        exact = [c for c in cands if c["qualname"] == callee]
        if exact:
            same = [c for c in exact if c["file"] == caller_file]
            if len(same) == 1:
                return same[0]["id"], "EXTRACTED"
            if len(exact) == 1:
                return exact[0]["id"], "INFERRED"
            return None, "ambiguous"
        suffix = [c for c in cands if c["qualname"].endswith("." + callee)]
        if suffix:
            same = [c for c in suffix if c["file"] == caller_file]
            if len(same) == 1:
                return same[0]["id"], "EXTRACTED"
            if len(suffix) == 1:
                return suffix[0]["id"], "INFERRED"
            return None, "ambiguous"
    same_file = [c for c in cands if c["file"] == caller_file]
    if len(same_file) == 1:
        return same_file[0]["id"], "EXTRACTED"
    if len(same_file) > 1:
        return None, "ambiguous"
    if len(cands) == 1:
        return cands[0]["id"], "INFERRED"
    return None, "ambiguous"


def _resolve_import(module: str, importer_file: str, file_index: dict) -> str | None:
    """Map an imported module string to a scanned file id, or None.

    Handles relative imports (./x, ../x), bare stems, and dotted
    paths (a.b -> a/b.py or a/b/__init__.py / index.js).
    """
    import posixpath
    if module.startswith("."):
        base = posixpath.dirname(importer_file)
        cand = posixpath.normpath(posixpath.join(base, module))
        for tail in ("", "/__init__", "/index"):
            for ext in (".py", ".js", ".ts", ".tsx", ".jsx", ".mjs",
                        ".go", ".rs", ".java"):
                hit = file_index.get(cand + tail + ext)
                if hit:
                    return hit
        return None
    dotted = module.replace(".", "/")
    for tail in ("", "/__init__", "/index"):
        for ext in (".py", ".js", ".ts", ".tsx", ".jsx", ".mjs",
                    ".go", ".rs", ".java"):
            hit = file_index.get(dotted + tail + ext)
            if hit:
                return hit
    stem = module.split(".")[-1]
    hits = [fid for rel, fid in file_index.items()
            if rel.rsplit("/", 1)[-1].rsplit(".", 1)[0] == stem]
    if len(hits) == 1:
        return hits[0]
    return None


# ------------------------------------------------------------------ build
def build_graph(root: Path | str | None = None, max_files: int = 500) -> dict:
    """Build the symbol graph for Python + JS/TS + Go/Rust/Java files under root.

    Extract -> validate -> build. Raises ValueError only if the
    finished graph fails the schema gate (a bug, not a data problem:
    unparseable files are skipped, never fatal).
    """
    root = Path(root) if root is not None else _workspace()
    all_files = discover_files(root)
    capped = len(all_files) > max_files
    files = all_files[:max_files]

    raw: dict[str, dict] = {}  # rel -> extraction
    for p in files:
        rel = str(p.relative_to(root))
        ext = _extract_file(p, rel)
        if ext is not None:
            raw[rel] = ext

    symbols: dict[str, dict] = {}
    file_nodes: list[dict] = []
    by_short: dict[str, list[dict]] = {}
    file_symbols: dict[str, list[str]] = {}
    for rel, ext in raw.items():
        lang = ("python" if rel.endswith(".py") else
                LANGUAGE_FOR_SUFFIX.get(Path(rel).suffix, "javascript"))
        file_nodes.append({"id": _file_id(rel), "path": rel, "language": lang})
        for d in ext["defs"]:
            sid = _symbol_id(rel, d["qualname"])
            rec = {"name": d["name"], "qualname": d["qualname"],
                   "kind": d["kind"], "file": rel, "line": d["line"],
                   "end_line": d["end_line"], "signature": d["signature"],
                   "exported": d["exported"], "body_hash": d["body_hash"],
                   "calls": []}
            symbols[sid] = rec
            by_short.setdefault(d["name"], []).append({**rec, "id": sid})
            file_symbols.setdefault(rel, []).append(sid)

    file_index = {rel: _file_id(rel) for rel in raw}
    edges: list[dict] = []
    dropped: list[dict] = []
    dropped_ambiguous = 0
    dropped_unresolved = 0
    for rel, ext in raw.items():
        for d in ext["defs"]:
            edges.append({"from": _file_id(rel), "to": _symbol_id(rel, d["qualname"]),
                          "type": "contains", "confidence": "EXTRACTED", "file": rel})
        for caller_qn, callee, line in ext["calls"]:
            caller_id = _symbol_id(rel, caller_qn) if caller_qn != MODULE_CALLER \
                else f"{_file_id(rel)}#{MODULE_CALLER}"
            target, conf = _resolve_call(rel, callee, by_short, {}, file_symbols)
            if target is None:
                if conf == "ambiguous":
                    dropped_ambiguous += 1
                else:
                    dropped_unresolved += 1
                if len(dropped) < 200:
                    dropped.append({"caller": caller_id, "callee": callee,
                                    "file": rel, "line": line, "reason": conf})
                continue
            edges.append({"from": caller_id, "to": target, "type": "calls",
                          "confidence": conf, "file": rel, "line": line})
            if caller_qn != MODULE_CALLER and target not in symbols[caller_id]["calls"]:
                symbols[caller_id]["calls"].append(target)
        for imp in ext["imports"]:
            mod = imp["module"]
            target_file = _resolve_import(mod, rel, file_index)
            if target_file:
                edges.append({"from": _file_id(rel), "to": target_file,
                              "type": "imports", "confidence": "EXTRACTED",
                              "file": rel, "line": imp.get("line")})
            else:
                edges.append({"from": _file_id(rel), "to": f"module:{mod}",
                              "type": "imports", "confidence": "INFERRED",
                              "file": rel, "line": imp.get("line")})

    languages: dict[str, int] = {}
    for rel in raw:
        _lang = ("python" if rel.endswith(".py") else
                 LANGUAGE_FOR_SUFFIX.get(Path(rel).suffix, "javascript"))
        languages[_lang] = languages.get(_lang, 0) + 1

    graph = {
        "files": len(raw),
        "symbols": symbols,
        "edges": edges,
        "file_nodes": file_nodes,
        "schema_version": SCHEMA_VERSION,
        "extractor_version": EXTRACTOR_VERSION,
        "cache_namespace": CACHE_NAMESPACE,
        "fingerprint": fingerprint_for(root, files),
        "stats": {
            "files_scanned": len(all_files),
            "files_capped": capped,
            "symbols": len(symbols),
            "edges": len(edges),
            "dropped_ambiguous": dropped_ambiguous,
            "dropped_unresolved": dropped_unresolved,
            "dropped": dropped,
            "languages": languages,
        },
    }
    validate_graph(graph)
    return graph


# ------------------------------------------------------------------ validate
def validate_graph(graph: dict) -> None:
    """Graphify-style schema gate. Raises ValueError listing every
    violation; an invalid confidence is an error, not a warning."""
    errors: list[str] = []
    for sid, sym in (graph.get("symbols") or {}).items():
        for field in ("name", "kind", "file", "line", "signature", "body_hash"):
            if field not in sym:
                errors.append(f"symbol {sid}: missing {field}")
        if sym.get("kind") not in ("function", "method", "class", "type", "constant", "variable"):
            errors.append(f"symbol {sid}: bad kind {sym.get('kind')!r}")
    sym_ids = set((graph.get("symbols") or {}).keys())
    file_ids = {n["id"] for n in graph.get("file_nodes") or []}
    for i, e in enumerate(graph.get("edges") or []):
        for field in ("from", "to", "type", "confidence"):
            if field not in e:
                errors.append(f"edge {i}: missing {field}")
        if e.get("confidence") not in VALID_CONFIDENCES:
            errors.append(f"edge {i}: invalid confidence {e.get('confidence')!r}")
        if e.get("type") not in ("calls", "imports", "contains"):
            errors.append(f"edge {i}: bad type {e.get('type')!r}")
        if e.get("type") == "calls" and e.get("to") not in sym_ids:
            errors.append(f"edge {i}: calls target not a symbol: {e.get('to')!r}")
        if e.get("type") == "contains" and e.get("from") not in file_ids:
            errors.append(f"edge {i}: contains source not a file node: {e.get('from')!r}")
    if errors:
        raise ValueError("code graph failed schema gate: " + "; ".join(errors[:20]))


# ------------------------------------------------------------------ fingerprint
def _file_fingerprint(path: Path) -> list:
    st = path.stat()
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return [st.st_size, int(st.st_mtime), h]


def fingerprint_for(root: Path, files: list[Path] | None = None) -> dict:
    """{rel: [size, mtime, sha256]} for every discovered source file."""
    root = Path(root)
    fp: dict[str, list] = {}
    for p in files if files is not None else discover_files(root):
        try:
            rel = str(p.relative_to(root))
            fp[rel] = _file_fingerprint(p)
        except OSError:
            continue
    return fp


def probe_fingerprint(root: Path, old_fp: dict | None = None) -> tuple[dict, dict]:
    """Stat-only probe; only size/mtime-moved files are re-hashed
    (Graft's ~3ms probe shape). Returns (new_fp, drift)."""
    root = Path(root)
    old_fp = old_fp or {}
    new_fp: dict[str, list] = {}
    added, removed, changed = [], [], []
    for p in discover_files(root):
        rel = str(p.relative_to(root))
        try:
            st = p.stat()
        except OSError:
            continue
        old = old_fp.get(rel)
        if old and old[0] == st.st_size and old[1] == int(st.st_mtime):
            new_fp[rel] = old
        else:
            try:
                new_fp[rel] = _file_fingerprint(p)
            except OSError:
                continue
            if old is None:
                added.append(rel)
            else:
                changed.append(rel)
    removed = [rel for rel in old_fp if rel not in new_fp]
    return new_fp, {"added": sorted(added), "removed": sorted(removed),
                    "changed": sorted(changed)}


def check_freshness(root: Path | str | None, graph: dict | None) -> dict:
    """Diff the live tree against a graph's stored fingerprint.

    Never builds; never raises on a missing/unreadable tree (reports
    ``error`` and ``fresh=False`` instead).
    """
    if graph is None:
        return {"fresh": False, "added": [], "removed": [], "changed": [],
                "error": "no graph to check against"}
    try:
        root = Path(root) if root is not None else _workspace()
        _new_fp, drift = probe_fingerprint(root, graph.get("fingerprint") or {})
    except Exception as exc:  # noqa: BLE001 — freshness must never crash callers
        return {"fresh": False, "added": [], "removed": [], "changed": [],
                "error": str(exc)}
    drift["fresh"] = not (drift["added"] or drift["removed"] or drift["changed"])
    drift["stale"] = not drift["fresh"]
    return drift


# ------------------------------------------------------------------ cache
_CACHE: dict[str, dict] = {}


def _cache_key(root: Path) -> str:
    return f"{CACHE_NAMESPACE}::{root.resolve()}"


def ensure_fresh_graph(root: Path | str | None = None, max_files: int = 500):
    """(graph, warning|None). Rebuilds on fingerprint drift; on ANY
    rebuild failure the stale graph is served with a warning — a
    rebuild failure must never fail a query (Graft's 'never fatal')."""
    root = Path(root) if root is not None else _workspace()
    key = _cache_key(root)
    cached = _CACHE.get(key)
    if cached is None:
        try:
            graph = build_graph(root, max_files=max_files)
        except Exception as exc:  # noqa: BLE001
            return None, f"code graph build failed and no cached graph exists: {exc}"
        _CACHE[key] = graph
        return graph, None
    drift = check_freshness(root, cached)
    if drift.get("fresh"):
        return cached, None
    try:
        graph = build_graph(root, max_files=max_files)
    except Exception as exc:  # noqa: BLE001
        return cached, (f"code graph rebuild failed ({exc}); serving stale "
                        f"graph ({len(drift['added'])} added, "
                        f"{len(drift['removed'])} removed, "
                        f"{len(drift['changed'])} changed)")
    _CACHE[key] = graph
    return graph, None


def invalidate_cache(root: Path | str | None = None) -> None:
    if root is None:
        _CACHE.clear()
    else:
        _CACHE.pop(_cache_key(Path(root)), None)


def cached_graph(root: Path | str | None = None) -> dict | None:
    """The last built graph for this root, or None — WITHOUT probing
    or rebuilding. This is what graph/check diffs against."""
    root = Path(root) if root is not None else _workspace()
    return _CACHE.get(_cache_key(root))


# ------------------------------------------------------------------ queries
def resolve_symbol(name: str, graph: dict) -> tuple[str | None, list[str] | None]:
    """Resolve a user-supplied name to a symbol id.

    Returns (id, None) on success; (None, [candidates]) when ambiguous;
    (None, None) when not found. Never silently picks first match.
    """
    syms = graph["symbols"]
    if name in syms:
        return name, None
    exact_qn = [k for k, s in syms.items() if s["qualname"] == name]
    if len(exact_qn) == 1:
        return exact_qn[0], None
    if len(exact_qn) > 1:
        return None, sorted(exact_qn)
    suffix = [k for k in syms
              if syms[k]["qualname"] == name
              or syms[k]["qualname"].endswith("." + name)
              or syms[k]["name"] == name]
    if len(suffix) == 1:
        return suffix[0], None
    if len(suffix) > 1:
        return None, sorted(suffix)
    return None, None


def explain(symbol: str, graph: dict) -> dict:
    """What is X, what calls it, what does it use?"""
    sid, cands = resolve_symbol(symbol, graph)
    if cands:
        return {"error": f"Ambiguous symbol: {symbol}",
                "candidates": cands}
    if not sid:
        return {"error": f"Symbol not found: {symbol}"}
    info = dict(graph["symbols"][sid])
    callers = sorted({e["from"] for e in graph["edges"]
                      if e["type"] == "calls" and e["to"] == sid})
    callees = sorted({e["to"] for e in graph["edges"]
                      if e["type"] == "calls" and e["from"] == sid})
    return {"symbol": sid, **info,
            "called_by": callers[:20], "call_count": len(callers),
            "calls": callees[:20], "call_out_count": len(callees)}


def find_path(a: str, b: str, graph: dict, max_depth: int = 4) -> dict:
    """Trace how symbol A connects to symbol B (BFS over resolved call
    edges only — ``contains`` edges are deliberately excluded, or
    every file becomes a false hub)."""
    from collections import deque
    sa, ca = resolve_symbol(a, graph)
    sb, cb = resolve_symbol(b, graph)
    if ca:
        return {"error": f"Ambiguous symbol: {a}", "candidates": ca}
    if cb:
        return {"error": f"Ambiguous symbol: {b}", "candidates": cb}
    if not sa or not sb:
        return {"error": f"Could not resolve: {a} -> {b}"}
    adj: dict[str, list[str]] = {}
    for e in graph["edges"]:
        if e["type"] == "calls":
            adj.setdefault(e["from"], []).append(e["to"])
    q = deque([(sa, [sa])])
    seen = {sa}
    while q:
        node, path = q.popleft()
        if node == sb:
            return {"path": path, "hops": len(path) - 1}
        if len(path) > max_depth:
            continue
        for nxt in adj.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                q.append((nxt, [*path, nxt]))
    return {"path": [], "message": f"No path found within {max_depth} hops"}
