"""Extra-language extraction for Sangam's code graph (A5, perfect-flow).

Honest breadth: this module adds exactly three language families on top
of the existing Python (stdlib ``ast``) and JS/TS (``code_extract_js``)
extractors — Go, Rust, and Java. It does NOT claim tree-sitter or
160+ languages. Like the JS extractor it is a hand-written,
comment/string-masked regex scanner emitting exactly the same
node/edge schema (``defs`` / ``calls`` / ``imports``), so the graph's
resolution, freshness, and schema gates apply unchanged.

Coverage (common shapes only, stated so tests can pin it):
  Go:   ``func`` (plain + receiver methods), ``type X struct|interface``,
        ``import`` (single + block), call expressions ``name(...)`` /
        ``obj.method(...)``.
  Rust: ``fn`` (plain + ``impl`` methods, qualname ``Type.name``),
        ``struct`` / ``enum`` / ``trait`` (kind ``type``/``class``),
        ``use`` imports, call expressions.
  Java: ``class`` / ``interface`` / ``enum``, methods (incl.
        constructors, qualname ``Class.method``), ``import`` statements,
        call expressions. Annotation lines are ignored for definitions.

Calls are attributed to the nearest preceding definition in the same
file (line order); a call before any definition is attributed to
``<module>``, matching the Python/JS extractors' convention. Keywords
that look like calls (``if``, ``for``, ``while``, ``return``, ...) are
excluded. End lines are brace-matched from the definition line where
a body brace exists, else the definition line itself.
"""
from __future__ import annotations

import hashlib
import re

EXTRA_EXTRACTOR_ID = "py-regex-extra-v1"

_KEYWORDS = {
    "if", "for", "while", "switch", "catch", "return", "typeof", "new",
    "delete", "in", "of", "instanceof", "await", "yield", "else", "do",
    "try", "finally", "throw", "case", "func", "fn", "class", "struct",
    "enum", "impl", "pub", "let", "mut", "match", "loop", "where",
    "super", "self", "Self", "this", "println", "print",
}
_CALL_RE = re.compile(r"([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)\s*\(")


def _mask(text: str) -> str:
    """Mask string/comment contents, preserving newlines/positions."""
    out: list[str] = []
    i, n = 0, len(text)
    state = None  # None | "line" | "block" | quote char
    while i < n:
        ch, nxt = text[i], text[i + 1] if i + 1 < n else ""
        if state is None:
            if ch == "/" and nxt == "/":
                state, out, i = "line", out + [" ", " "], i + 2
            elif ch == "/" and nxt == "*":
                state, out, i = "block", out + [" ", " "], i + 2
            elif ch in ("'", '"', "`"):
                state, out, i = ch, out + [" "], i + 1
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
                state, out, i = None, out + [" ", " "], i + 2
            else:
                out.append("\n" if ch == "\n" else " ")
                i += 1
        else:
            if ch == "\\" and i + 1 < n:
                out.append(" " if text[i + 1] != "\n" else "\n")
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


def _brace_end(lines: list[str], start: int) -> int:
    """1-based end line of the brace block opened at/after ``start``."""
    depth = 0
    seen = False
    for idx in range(start, len(lines)):
        for ch in lines[idx]:
            if ch == "{":
                depth += 1
                seen = True
            elif ch == "}":
                depth -= 1
        if seen and depth <= 0:
            return idx + 1
    return start + 1


def _finish(rel: str, defs: list[dict], calls: list[tuple],
            imports: list[dict], lines: list[str]) -> dict:
    out_defs = []
    for d in defs:
        end = _brace_end(lines, d["line"] - 1) if d.get("has_body") else d["line"]
        segment = "\n".join(lines[d["line"] - 1:end])
        out_defs.append({
            "name": d["name"], "qualname": d["qualname"], "kind": d["kind"],
            "line": d["line"], "end_line": end,
            "signature": d["signature"][:300],
            "exported": d.get("exported", True),
            "body_hash": hashlib.sha256(segment.encode("utf-8")).hexdigest(),
        })
    return {"defs": out_defs, "calls": calls, "imports": imports}


def _calls_for(lines: list[str], defs: list[dict]) -> list[tuple]:
    """Attribute each call to the nearest preceding definition."""
    calls: list[tuple] = []
    for idx, line in enumerate(lines):
        lineno = idx + 1
        caller = "<module>"
        for d in defs:
            if d["line"] <= lineno:
                caller = d["qualname"]
            else:
                break
        for m in _CALL_RE.finditer(line):
            callee = m.group(1)
            head = callee.split(".")[0]
            if head in _KEYWORDS or callee.split(".")[-1] in _KEYWORDS:
                continue
            # Skip the definition's own name on its definition line.
            if lineno in {d["line"] for d in defs} and callee.split(".")[-1] in {
                    d["name"] for d in defs if d["line"] == lineno}:
                continue
            calls.append((caller, callee, lineno))
    return calls


# --------------------------------------------------------------------- Go
_GO_FUNC_RE = re.compile(
    r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*\(")
_GO_TYPE_RE = re.compile(
    r"^\s*type\s+([A-Za-z_]\w*)\s+(?:struct|interface)\b")
_GO_IMPORT_RE = re.compile(r'^\s*import\s+"([^"]+)"')
_GO_IMPORT_BLOCK_RE = re.compile(r'"([^"]+)"')


def extract_go_file(rel: str, text: str) -> dict:
    masked = _mask(text)
    lines = masked.split("\n")
    orig_lines = text.split("\n")
    defs: list[dict] = []
    imports: list[dict] = []
    in_block = False
    for idx, line in enumerate(orig_lines):
        # Imports are parsed from the ORIGINAL line: masking blanks
        # the quoted module path, so the masked line carries nothing.
        if re.match(r"^\s*import\s*\(", line):
            in_block = True
            continue
        if in_block:
            if ")" in line:
                in_block = False
            for m in _GO_IMPORT_BLOCK_RE.finditer(line):
                imports.append({"module": m.group(1), "names": [m.group(1)],
                                "line": idx + 1})
            continue
        m = _GO_IMPORT_RE.match(line)
        if m:
            imports.append({"module": m.group(1), "names": [m.group(1)],
                            "line": idx + 1})
    for idx, line in enumerate(lines):
        m = _GO_FUNC_RE.match(line)
        if m:
            name = m.group(1)
            recv = re.search(r"func\s+\(([^)]*)\)", line)
            qualname = name
            kind = "function"
            if recv:
                # Receiver type is the last word of "(r *Type)" / "(r Type)".
                rtype = recv.group(1).strip().split()[-1].strip("*[]")
                qualname, kind = f"{rtype}.{name}", "method"
            defs.append({"name": name, "qualname": qualname, "kind": kind,
                         "line": idx + 1, "has_body": "{" in line,
                         "signature": line.strip(),
                         "exported": name[:1].isupper()})
            continue
        m = _GO_TYPE_RE.match(line)
        if m:
            defs.append({"name": m.group(1), "qualname": m.group(1),
                         "kind": "type", "line": idx + 1,
                         "has_body": "{" in line, "signature": line.strip(),
                         "exported": m.group(1)[:1].isupper()})
    defs.sort(key=lambda d: d["line"])
    return _finish(rel, defs, _calls_for(lines, defs), imports, lines)


# ------------------------------------------------------------------- Rust
_RS_FN_RE = re.compile(
    r"(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_]\w*)\s*[<(]")
_RS_TYPE_RE = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?(struct|enum|trait)\s+([A-Za-z_]\w*)")
_RS_USE_RE = re.compile(r"^\s*use\s+([^;]+);")


def extract_rust_file(rel: str, text: str) -> dict:
    masked = _mask(text)
    lines = masked.split("\n")
    defs: list[dict] = []
    imports: list[dict] = []
    impl_stack: list[tuple[str, int]] = []  # (type, brace depth at open)
    depth = 0
    for idx, line in enumerate(lines):
        m = _RS_USE_RE.match(line)
        if m:
            mod = m.group(1).strip().replace("::", ".")
            imports.append({"module": mod, "names": [mod], "line": idx + 1})
        m = re.match(r"^\s*impl(?:<[^>]*>)?\s+([A-Za-z_]\w*)", line)
        if m:
            impl_stack.append((m.group(1), depth))
        m = _RS_TYPE_RE.match(line)
        if m:
            defs.append({"name": m.group(2), "qualname": m.group(2),
                         "kind": "type", "line": idx + 1,
                         "has_body": "{" in line, "signature": line.strip(),
                         "exported": line.strip().startswith("pub")})
            continue
        for m in _RS_FN_RE.finditer(line):
            name = m.group(1)
            owner = impl_stack[-1][0] if impl_stack else None
            qualname = f"{owner}.{name}" if owner else name
            defs.append({"name": name, "qualname": qualname,
                         "kind": "method" if owner else "function",
                         "line": idx + 1, "has_body": "{" in line,
                         "signature": line.strip(),
                         "exported": "pub" in line})
        depth += line.count("{") - line.count("}")
        while impl_stack and depth <= impl_stack[-1][1]:
            impl_stack.pop()
    defs.sort(key=lambda d: d["line"])
    return _finish(rel, defs, _calls_for(lines, defs), imports, lines)


# ------------------------------------------------------------------- Java
_JAVA_CLASS_RE = re.compile(
    r"^\s*(?:public\s+|private\s+|protected\s+|abstract\s+|final\s+)*"
    r"(class|interface|enum)\s+([A-Za-z_]\w*)")
_JAVA_METHOD_RE = re.compile(
    r"^\s*(?:(public|private|protected|static|final|abstract|"
    r"synchronized|native)\s+)+"
    r"(?:([A-Za-z_][\w<>\[\]., ?]*)\s+)?([A-Za-z_]\w*)\s*\([^;]*\)")
_JAVA_IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([^;]+);")
_JAVA_KEYWORDS = {"if", "for", "while", "switch", "catch", "return",
                  "new", "super", "this", "else", "do", "try"}


def extract_java_file(rel: str, text: str) -> dict:
    masked = _mask(text)
    lines = masked.split("\n")
    defs: list[dict] = []
    imports: list[dict] = []
    class_stack: list[tuple[str, int]] = []
    depth = 0
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("@"):
            depth += line.count("{") - line.count("}")
            continue
        m = _JAVA_IMPORT_RE.match(line)
        if m:
            imports.append({"module": m.group(1).strip(),
                            "names": [m.group(1).strip().split(".")[-1]],
                            "line": idx + 1})
        m = _JAVA_CLASS_RE.match(line)
        if m:
            class_stack.append((m.group(2), depth))
            defs.append({"name": m.group(2), "qualname": m.group(2),
                         "kind": "class", "line": idx + 1,
                         "has_body": "{" in line, "signature": line.strip(),
                         "exported": "public" in line or not class_stack[:-1]})
            depth += line.count("{") - line.count("}")
            continue
        m = _JAVA_METHOD_RE.match(line)
        if m and class_stack and m.group(3) not in _JAVA_KEYWORDS:
            name = m.group(3)
            owner = class_stack[-1][0]
            # A constructor has no return type and its name == class name.
            kind = "method"
            defs.append({"name": name, "qualname": f"{owner}.{name}",
                         "kind": kind, "line": idx + 1,
                         "has_body": "{" in line, "signature": line.strip(),
                         "exported": "public" in line})
        depth += line.count("{") - line.count("}")
        while class_stack and depth <= class_stack[-1][1]:
            class_stack.pop()
    defs.sort(key=lambda d: d["line"])
    return _finish(rel, defs, _calls_for(lines, defs), imports, lines)


EXTRACTORS = {".go": extract_go_file, ".rs": extract_rust_file,
              ".java": extract_java_file}
LANGUAGE_FOR_SUFFIX = {".go": "go", ".rs": "rust", ".java": "java"}
