"""Merge fragmented test variant files into one module per domain.

Structure of each merged file (order matters — env setup must precede the
backend imports that read it):

1. Docstring listing sources
2. Canonical prologue: sys.path + TEST_MODE + MASTER_KEY (replaces each
   source's ad-hoc setup; idempotent and process-global)
3. Union of all source imports (deduped, first-seen order)
4. Body: each source's remaining top-level statements in order, deduped by
   normalized content; same-name/different-content segments renamed with a
   source-derived suffix (test_auth_unit.py -> ``...Unit``).

Usage:
    python scripts/merge_tests.py --inventory              # report renames
    python scripts/merge_tests.py --apply [GROUP GROUP...] # write merged files
"""
from __future__ import annotations

import ast
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"

GROUPS: dict[str, list[str]] = {
    "test_auth.py": ["test_auth.py", "test_auth_unit.py", "test_auth_lockout.py", "test_auth_coverage.py"],
    "test_document.py": ["test_document.py", "test_document_new.py", "test_document_coverage.py"],
    "test_rag.py": ["test_rag_coverage.py", "test_rag_new.py"],
    "test_websearch.py": ["test_websearch.py", "test_websearch_new.py"],
    "test_api.py": ["test_api.py", "test_api_coverage.py"],
    "test_main.py": ["test_main_coverage.py", "test_main_coverage_new.py"],
    "test_models.py": ["test_model_selection.py", "test_model_fetch.py"],
    "test_providers.py": ["test_providers.py", "test_providers_init_coverage.py"],
}

SUFFIX_BY_TOKEN = {
    "new": "New",
    "coverage": "Coverage",
    "unit": "Unit",
    "lockout": "Lockout",
}

CANONICAL_PROLOGUE = '''import os
import sys
from pathlib import Path

# --- Test environment (must run before backend imports) ---------------------
ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "mainfiles")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ["TEST_MODE"] = "1"

from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("MASTER_KEY", Fernet.generate_key().decode())'''

ENV_MARKERS = ("os.environ", "sys.path", "TEST_MODE", "MASTER_KEY", "ROOT =", "_MAINFILES", "sys.path.insert")


def source_suffix(filename: str) -> str:
    parts = Path(filename).stem.split("_")[1:]  # drop leading "test"
    for part in reversed(parts):
        if part in SUFFIX_BY_TOKEN:
            return SUFFIX_BY_TOKEN[part]
    return "".join(p.capitalize() for p in parts)


def seg_text(src_lines: list[str], node: ast.AST) -> str:
    start = node.lineno
    decorators = getattr(node, "decorator_list", None)
    if decorators:
        start = min(start, min(d.lineno for d in decorators))
    return "".join(src_lines[start - 1 : node.end_lineno])


def norm(text: str) -> str:
    return hashlib.md5(re.sub(r"\s+", " ", text.strip()).encode()).hexdigest()


def is_env_statement(node: ast.AST, text: str) -> bool:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return False
    if any(marker in text for marker in ENV_MARKERS):
        return True
    # import statements that exist purely to serve env setup
    if isinstance(node, ast.Import) and "cryptography" in text:
        return True
    return False


def parse_file(path: Path) -> dict:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)
    out: dict = {"imports": [], "env": [], "segments": []}
    first = True
    for node in tree.body:
        text = seg_text(lines, node)
        if first and isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            first = False
            continue  # module docstring — replaced by merged header
        first = False
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if not is_env_statement(node, text):
                out["imports"].append(text)
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out["segments"].append((node.name, text))
            continue
        if isinstance(node, ast.If) and "module" in ast.dump(node.test) and "__main__" in ast.dump(node):
            continue
        if is_env_statement(node, text):
            out["env"].append(text)
        else:
            # module-level assignments/fixtures kept in body order
            out["segments"].append((None, text))
    return out


def merge(target: str, sources: list[str], apply: bool) -> None:
    parsed = [(name, parse_file(TESTS / name)) for name in sources]
    seen: dict[str, str] = {}
    rename_report: dict[str, dict[str, str]] = {}
    body_parts: list[str] = []
    imports: list[str] = []
    env_lines: list[str] = []

    for src_name, data in parsed:
        suffix = "" if src_name == sources[0] else source_suffix(src_name)
        local_map: dict[str, str] = {}
        for name, text in data["segments"]:
            if name is None:
                continue
            h = norm(text)
            if name in seen:
                if seen[name] != h:
                    local_map[name] = f"{name}{suffix}"
            else:
                seen[name] = h
        rename_report[src_name] = local_map

        for name, text in data["segments"]:
            final = text
            if local_map:
                for old, new in local_map.items():
                    final = re.sub(rf"\b{re.escape(old)}\b", new, final)
            body_parts.append("\n\n" + final.rstrip() + "\n")
        for text in data["env"]:
            if text not in env_lines:
                env_lines.append(text)
        for imp in data["imports"]:
            if imp not in imports:
                imports.append(imp)

    header = [f'"""{Path(target).stem} — consolidated tests.', ""]
    header.append("Merged from:")
    header.extend(f"- {s}" for s in sources)
    header.append('"""')

    body = "".join(body_parts)
    merged = "\n".join(header) + "\n\n" + CANONICAL_PROLOGUE + "\n\n# --- imports ---\n" + "\n".join(imports) + "\n\n# --- tests ---" + body

    if apply:
        (TESTS / target).write_text(merged, encoding="utf-8")
        print(f"wrote {TESTS / target} ({len(merged.splitlines())} lines)")
    else:
        total_renames = sum(len(v) for v in rename_report.values())
        print(f"[dry] {target}: {len(sources)} sources, {total_renames} renames, {len(merged.splitlines())} lines")
        for s, m in rename_report.items():
            if m:
                print(f"  {s}: {sorted(m)}")


if __name__ == "__main__":
    args = sys.argv[1:]
    apply = "--apply" in args
    groups = [a for a in args if not a.startswith("--")] or list(GROUPS)
    for g in groups:
        merge(g, GROUPS[g], apply)
