"""
Code map — AST-based codebase knowledge graph (Graphify-style, Sangam-native).

Deterministic static analysis over Python files: no LLM cost for code parsing.
Answers: "what calls X?", "what does X depend on?", "how do A and B connect?".

Exposed to the Code Agent as the ``code_map`` tool.
"""
from __future__ import annotations

import ast
from pathlib import Path


def _workspace() -> Path:
    from .tools.builtin import _get_workspace_root
    return _get_workspace_root()


class _Visitor(ast.NodeVisitor):
    def __init__(self, file: str):
        self.file = file
        self.defs: dict[str, dict] = {}   # qualname -> {kind, file, line}
        self.calls: list[tuple[str, str]] = []  # (caller, callee)
        self.imports: list[str] = []
        self._stack: list[str] = []

    def _name(self, node) -> str:
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))

    def visit_FunctionDef(self, node):
        qn = ".".join([*self._stack, node.name])
        self.defs[qn] = {"kind": "function", "file": self.file, "line": node.lineno}
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        qn = ".".join([*self._stack, node.name])
        self.defs[qn] = {"kind": "class", "file": self.file, "line": node.lineno}
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    def visit_Call(self, node):
        callee = self._name(node.func)
        caller = ".".join(self._stack) or "<module>"
        if callee:
            self.calls.append((caller, callee))
        self.generic_visit(node)

    def visit_Import(self, node):
        for a in node.names:
            self.imports.append(a.name)

    def visit_ImportFrom(self, node):
        if node.module:
            self.imports.append(node.module)


def build_graph(root: Path | None = None, max_files: int = 500) -> dict:
    """Build the symbol graph for Python files under root."""
    root = root or _workspace()
    defs: dict[str, dict] = {}
    edges: list[dict] = []
    files = 0
    for py in sorted(root.rglob("*.py")):
        if "__pycache__" in py.parts or ".venv" in py.parts:
            continue
        if files >= max_files:
            break
        files += 1
        rel = str(py.relative_to(root))
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        v = _Visitor(rel)
        v.visit(tree)
        defs.update(v.defs)
        for caller, callee in v.calls:
            edges.append({"from": caller, "to": callee, "type": "calls", "file": rel})
        for imp in v.imports:
            edges.append({"from": rel, "to": imp, "type": "imports"})
    return {"files": files, "symbols": defs, "edges": edges}


def explain(symbol: str, graph: dict) -> dict:
    """What is X, what calls it, what does it use?"""
    syms = graph["symbols"]
    match = [k for k in syms if k == symbol or k.endswith("." + symbol) or k.endswith(symbol)]
    if not match:
        return {"error": f"Symbol not found: {symbol}"}
    key = match[0]
    info = dict(syms[key])
    callers = [e["from"] for e in graph["edges"]
               if e["type"] == "calls" and (e["to"] == key or e["to"].endswith("." + symbol))]
    return {
        "symbol": key, **info,
        "called_by": sorted(set(callers))[:20],
        "call_count": len(set(callers)),
    }


def find_path(a: str, b: str, graph: dict, max_depth: int = 4) -> dict:
    """Trace how symbol A connects to symbol B (BFS over call edges)."""
    from collections import deque
    # Normalize to defined symbols
    def resolve(s):
        return next((k for k in graph["symbols"] if k == s or k.endswith("." + s)), None)
    sa, sb = resolve(a), resolve(b)
    if not sa or not sb:
        return {"error": f"Could not resolve: {a} -> {b}"}
    adj: dict[str, set[str]] = {}
    for e in graph["edges"]:
        if e["type"] == "calls":
            adj.setdefault(e["from"], set()).add(e["to"])
    q = deque([(sa, [sa])])
    seen = {sa}
    while q:
        node, path = q.popleft()
        if node == sb or node.endswith("." + b):
            return {"path": path, "hops": len(path) - 1}
        if len(path) > max_depth:
            continue
        for nxt in adj.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                q.append((nxt, [*path, nxt]))
    return {"path": [], "message": f"No path found within {max_depth} hops"}
