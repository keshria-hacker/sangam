"""JS/TS extraction for Sangam's code graph (Graphify-shaped, Sangam-native).

Pure-Python extractor — no tree-sitter dependency. Rationale, stated
honestly: the venv has no ``tree_sitter`` wheel and pip cannot fetch one
in this environment (PyPI SSL failure at build time), so JS/TS parsing
here is a hand-written scanner (comment/string masking + brace matching)
that emits exactly the same node/edge schema as the Python ``ast``
extractor. The cache namespace records the extractor id
(``JS_EXTRACTOR_ID``), so swapping in a real tree-sitter grammar later
invalidates every cached graph automatically instead of silently
mixing extractor outputs.

Coverage (deliberately the common shapes, not the whole language):
function declarations, ``const`` arrow/function expressions, class
declarations + methods (incl. ``static``/``async``/``get``/``set``),
``interface``/``type`` declarations (TS, kind ``type``), ``import`` /
``require`` statements, and call expressions (``name(...)``,
``obj.method(...)``, ``this.method(...)``). JSX markup is ignored
(it contains no definitions); calls inside JSX attribute expressions
are still found because masking only removes strings/comments.

Output shape (per file)::

    defs:  [{name, qualname, kind, line, end_line, signature,
             exported, body_hash}]
    calls: [(caller_qualname_or_<module>, callee_dotted, line)]
    imports: [{module, names, line}]
"""
from __future__ import annotations

import hashlib
import re

JS_EXTRACTOR_ID = "py-js-regex-v1"

_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "typeof",
    "new", "delete", "void", "in", "of", "instanceof", "await",
    "yield", "else", "do", "try", "finally", "throw", "case",
    "function", "class", "extends", "super", "this", "console",
}

_CLASS_RE = re.compile(
    r"(?:export\s+(?:default\s+)?)?class\s+([A-Za-z_$][\w$]*)\s*"
    r"(?:extends\s+[A-Za-z_$][\w$.]*)?\s*\{"
)
_FUNC_RE = re.compile(
    r"(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s*\*?\s*"
    r"([A-Za-z_$][\w$]*)\s*\("
)
_ARROW_RE = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:async\s+)?(?:\((?:[^()]|\([^()]*\))*\)|[A-Za-z_$][\w$]*)\s*=>"
)
_FUNC_EXPR_RE = re.compile(
    r"(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
    r"(?:async\s+)?function\s*\*?\s*(?:[A-Za-z_$][\w$]*)?\s*\("
)
_TYPE_RE = re.compile(
    r"(?:export\s+)?(?:interface\s+([A-Za-z_$][\w$]*)|type\s+([A-Za-z_$][\w$]*)\s*=)"
)
_METHOD_RE = re.compile(
    r"^\s*(?:(?:public|private|protected|static|async|get|set)\s+|\*\s*)*"
    r"([A-Za-z_$][\w$]*)\s*\("
)
_IMPORT_FROM_RE = re.compile(
    r"import\s+(?:type\s+)?(.+?)\s+from\s+['\"]([^'\"]+)['\"]", re.DOTALL
)
_IMPORT_SIDE_RE = re.compile(r"import\s+['\"]([^'\"]+)['\"]")
_REQUIRE_RE = re.compile(r"require\s*\(\s*['\"]([^'\"]+)['\"]\s*\)")
_EXPORT_FROM_RE = re.compile(
    r"export\s+(?:\*\s+as\s+\w+\s+)?(?:\{[^}]*\}\s+)?from\s+['\"]([^'\"]+)['\"]"
)
_CALL_RE = re.compile(r"([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\(")


def _mask_strings_and_comments(text: str) -> str:
    """Replace string/comment contents with spaces, preserving newlines
    and positions so line numbers and offsets stay valid."""
    out: list[str] = []
    i, n = 0, len(text)
    state = None  # None | "line" | "block" | quote char
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state is None:
            if ch == "/" and nxt == "/":
                state, out = "line", out + [" ", " "]
                i += 2
            elif ch == "/" and nxt == "*":
                state, out = "block", out + [" ", " "]
                i += 2
            elif ch in ("'", '"', "`"):
                state, out = ch, out + [" "]
                i += 1
            else:
                out.append(ch)
                i += 1
        elif state == "line":
            if ch == "\n":
                state = None
                out.append(ch)
            else:
                out.append(" ")
            i += 1
        elif state == "block":
            if ch == "*" and nxt == "/":
                state, out = None, out + [" ", " "]
                i += 2
            else:
                out.append("\n" if ch == "\n" else " ")
                i += 1
        else:  # inside a string/template literal
            if ch == "\\" and i + 1 < n:
                out.append("\n" if text[i + 1] == "\n" else " ")
                out.append(" ")
                i += 2
            elif ch == state:
                state = None
                out.append(" ")
                i += 1
            else:
                out.append("\n" if ch == "\n" else " ")
                i += 1
    return "".join(out)


def _strip_comments_only(text: str) -> str:
    """Remove comments but keep strings (used for import parsing)."""
    out: list[str] = []
    i, n = 0, len(text)
    state = None
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state is None:
            if ch == "/" and nxt == "/":
                state = "line"
                i += 2
            elif ch == "/" and nxt == "*":
                state = "block"
                i += 2
            elif ch in ("'", '"', "`"):
                state = ch
                out.append(ch)
                i += 1
            else:
                out.append(ch)
                i += 1
        elif state == "line":
            if ch == "\n":
                state = None
                out.append(ch)
            i += 1
        elif state == "block":
            if ch == "*" and nxt == "/":
                state = None
                i += 2
            else:
                if ch == "\n":
                    out.append(ch)
                i += 1
        else:
            if ch == "\\" and i + 1 < n:
                out.append(ch)
                out.append(text[i + 1])
                i += 2
            elif ch == state:
                state = None
                out.append(ch)
                i += 1
            else:
                out.append(ch)
                i += 1
    return "".join(out)


def _matching_brace(masked: str, open_idx: int) -> int:
    depth = 0
    for i in range(open_idx, len(masked)):
        if masked[i] == "{":
            depth += 1
        elif masked[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(masked) - 1


def _line_of(masked: str, idx: int) -> int:
    return masked.count("\n", 0, idx) + 1


def _body_hash(lines: list[str], start: int, end: int) -> str:
    body = "\n".join(lines[start - 1:end])
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _exported_at(masked: str, m: re.Match) -> bool:
    """Exported if the statement starts with `export` — either before
    the match or consumed by the match itself (the def regexes
    optionally include the `export` prefix)."""
    line_start = masked.rfind("\n", 0, m.start()) + 1
    before = masked[line_start:m.start()].strip()
    if before.startswith("export"):
        return True
    return masked[m.start():m.start() + 7] == "export "


def extract_js_file(rel: str, text: str) -> dict:
    """Extract defs/calls/imports from one JS/TS source file."""
    lines = text.split("\n")
    masked = _mask_strings_and_comments(text)
    no_comments = _strip_comments_only(text)
    defs: list[dict] = []
    seen: set[tuple[str, int]] = set()
    # Start offsets of definition-name tokens, so call scanning can skip
    # a definition's own name (e.g. the `render` in `render() {`).
    def_name_offsets: set[int] = set()

    def _add(name: str, qualname: str, kind: str, line: int, end_line: int,
             signature: str, exported: bool, name_offset: int | None = None) -> dict | None:
        key = (qualname, line)
        if key in seen:
            return None
        seen.add(key)
        if name_offset is not None:
            def_name_offsets.add(name_offset)
        d = {
            "name": name, "qualname": qualname, "kind": kind,
            "line": line, "end_line": max(end_line, line),
            "signature": signature.strip()[:300],
            "exported": exported,
            "body_hash": _body_hash(lines, line, max(end_line, line)),
        }
        defs.append(d)
        return d

    # --- classes ---
    class_ranges: list[tuple[str, int, int]] = []  # name, brace idx, end idx
    for m in _CLASS_RE.finditer(masked):
        name = m.group(1)
        start_line = _line_of(masked, m.start())
        brace = masked.find("{", m.start())
        end_idx = _matching_brace(masked, brace) if brace >= 0 else m.end()
        end_line = _line_of(masked, end_idx)
        name_offset = m.start(1)
        _add(name, name, "class", start_line, end_line,
             f"class {name}", _exported_at(masked, m), name_offset)
        class_ranges.append((name, brace, end_idx))

    def _in_class(idx: int) -> str | None:
        for name, brace, end_idx in class_ranges:
            if brace < idx < end_idx:
                return name
        return None

    # --- top-level functions / arrows / function expressions ---
    for m in _FUNC_RE.finditer(masked):
        if _in_class(m.start()):
            continue
        name = m.group(1)
        line = _line_of(masked, m.start())
        brace = masked.find("{", m.end())
        end_line = _line_of(masked, _matching_brace(masked, brace)) if brace >= 0 else line
        sig_end = masked.find("{", m.start())
        _add(name, name, "function", line, end_line,
             masked[m.start():sig_end if sig_end >= 0 else m.end()],
             _exported_at(masked, m), m.start(1))
    for m in _ARROW_RE.finditer(masked):
        if _in_class(m.start()):
            continue
        name = m.group(1)
        line = _line_of(masked, m.start())
        brace = masked.find("{", m.end())
        if brace >= 0 and masked[m.end():brace].strip() in ("", ";"):
            end_line = _line_of(masked, _matching_brace(masked, brace))
        else:
            end_line = line  # expression-bodied arrow
        _add(name, name, "function", line, end_line,
             masked[m.start():m.end()],
             _exported_at(masked, m), m.start(1))
    for m in _FUNC_EXPR_RE.finditer(masked):
        if _in_class(m.start()):
            continue
        name = m.group(1)
        line = _line_of(masked, m.start())
        brace = masked.find("{", m.end())
        end_line = _line_of(masked, _matching_brace(masked, brace)) if brace >= 0 else line
        _add(name, name, "function", line, end_line,
             masked[m.start():m.end()],
             _exported_at(masked, m), m.start(1))

    # --- methods inside class bodies (line scan within each class range) ---
    line_starts = [0]
    for ln in lines:
        line_starts.append(line_starts[-1] + len(ln) + 1)
    for cls, brace, end_idx in class_ranges:
        start_line = _line_of(masked, brace)
        end_line_no = _line_of(masked, end_idx)
        for ln in range(start_line, end_line_no + 1):
            raw = lines[ln - 1] if ln - 1 < len(lines) else ""
            if re.match(r"\s*class\s", raw):
                continue
            mm = _METHOD_RE.match(_mask_strings_and_comments(raw))
            if not mm:
                continue
            mname = mm.group(1)
            if mname in _KEYWORDS and mname != "constructor":
                continue
            if "=" in raw.split("(")[0] and "=>" in raw:
                continue  # class field holding an arrow function
            line_start_idx = line_starts[ln - 1]
            brace_idx = masked.find("{", line_start_idx)
            if brace_idx < 0 or brace_idx > end_idx:
                continue
            m_end = _line_of(masked, _matching_brace(masked, brace_idx))
            if m_end < ln:
                continue
            name_offset = line_start_idx + mm.start(1)
            _add(mname, f"{cls}.{mname}", "method", ln, m_end,
                 raw.strip()[:300], False, name_offset)

    # --- TS interfaces / types ---
    for m in _TYPE_RE.finditer(masked):
        name = m.group(1) or m.group(2)
        line = _line_of(masked, m.start())
        _add(name, name, "type", line, line, masked[m.start():m.end()],
             _exported_at(masked, m), m.start(1) if m.group(1) else m.start(2))

    defs.sort(key=lambda d: (d["line"], d["qualname"]))

    # --- imports ---
    imports: list[dict] = []
    for m in _IMPORT_FROM_RE.finditer(no_comments):
        clause, mod = m.group(1), m.group(2)
        names = [n.strip().split(" as ")[-1].strip()
                 for n in clause.replace("{", "").replace("}", "").split(",")
                 if n.strip() and n.strip() != "type"]
        imports.append({"module": mod, "names": names,
                        "line": _line_of(no_comments, m.start())})
    for m in _IMPORT_SIDE_RE.finditer(no_comments):
        imports.append({"module": m.group(1), "names": [],
                        "line": _line_of(no_comments, m.start())})
    for m in _EXPORT_FROM_RE.finditer(no_comments):
        imports.append({"module": m.group(1), "names": [],
                        "line": _line_of(no_comments, m.start())})
    for m in _REQUIRE_RE.finditer(no_comments):
        imports.append({"module": m.group(1), "names": [],
                        "line": _line_of(no_comments, m.start())})

    # --- calls: innermost enclosing def (latest start line) is caller ---
    def _caller(line: int) -> str:
        best = None
        for d in defs:
            if d["line"] <= line <= d["end_line"]:
                if best is None or d["line"] >= best["line"]:
                    best = d
        return best["qualname"] if best else "<module>"

    calls: list[tuple[str, str, int]] = []
    for m in _CALL_RE.finditer(masked):
        callee = m.group(1)
        if callee.split(".")[0] in _KEYWORDS:
            continue
        if m.start(1) in def_name_offsets:
            continue  # a definition's own name token, not a call
        before = masked[max(0, m.start() - 20):m.start()]
        if re.search(r"(function|class)\s*$", before):
            continue
        calls.append((_caller(_line_of(masked, m.start())), callee,
                      _line_of(masked, m.start())))

    seen_calls: set[tuple[str, str, int]] = set()
    uniq_calls = []
    for c in calls:
        if c not in seen_calls:
            seen_calls.add(c)
            uniq_calls.append(c)
    return {"defs": defs, "calls": uniq_calls, "imports": imports}
