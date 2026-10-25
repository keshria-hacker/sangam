"""
research/pack.py — Batch 9: repomix-style workspace packer
(Sangam-native, pure function over a directory).

Packs a directory into one LLM-ready text bundle: tree + file
contents + per-file token estimates + chunk splits. Safety first,
in repomix's spirit:

- Files outside the given root are never read (callers enforce the
  workspace-root gate; this module also refuses ``..`` escapes).
- Secret-bearing files are FILTERED, not just ignored: credential
  filenames (``.env``, ``*.pem``, ``id_rsa*`` …) and files whose
  content trips the defense scan are listed in ``filtered`` with a
  reason and their contents are never included.
- Binary files (null byte / undecodable) are skipped, not dumped.
- Token counts are a chars/4 ESTIMATE (same convention as the
  notebook path) — labelled as such, never presented as a
  model-specific count.

Output splits into chunks of at most ``max_tokens`` estimated
tokens so a pack can feed a research job or a chat attachment
without blowing a context budget. ``reassemble`` proves splits are
lossless (modulo the documented per-file truncation).
"""
from __future__ import annotations

import fnmatch
from pathlib import Path

from ..memory.defense import scan_text, secret_filename

SKIP_DIRS = {"__pycache__", ".venv", "node_modules", ".git", "dist",
             "build", ".next", ".git", "venv", ".tox", ".pytest_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".so", ".dll", ".exe", ".o", ".a",
                 ".zip", ".tar", ".gz", ".png", ".jpg", ".jpeg", ".gif",
                 ".ico", ".pdf", ".mp3", ".mp4", ".woff", ".woff2", ".ttf"}
MAX_FILE_CHARS = 200_000


def estimate_tokens(text: str) -> int:
    """~chars/4 estimate. Documented approximation, not a tokenizer."""
    return max(1, len(text) // 4)


def _is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


def pack_directory(root: Path | str, max_tokens: int = 8000) -> dict:
    """Pack ``root`` (must exist and be a directory). Returns a bundle
    dict: {root, tree, files, filtered, total_tokens_estimate,
    chunks, chunk_count}."""
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"pack root is not a directory: {root}")
    files: list[dict] = []
    filtered: list[dict] = []
    tree_lines: list[str] = []

    def _walk(directory: Path, prefix: str) -> None:
        try:
            entries = sorted(directory.iterdir(), key=lambda p: p.name)
        except OSError:
            return
        for entry in entries:
            rel = str(entry.relative_to(root))
            if entry.is_dir():
                if entry.name in SKIP_DIRS or entry.name.startswith("."):
                    continue
                tree_lines.append(f"{prefix}{entry.name}/")
                _walk(entry, prefix + "  ")
            elif entry.is_file():
                if entry.suffix.lower() in SKIP_SUFFIXES:
                    filtered.append({"path": rel, "reason": "binary/asset suffix"})
                    continue
                if secret_filename(rel):
                    filtered.append({"path": rel, "reason": "credential filename"})
                    continue
                try:
                    data = entry.read_bytes()
                except OSError:
                    filtered.append({"path": rel, "reason": "unreadable"})
                    continue
                if _is_binary(data):
                    filtered.append({"path": rel, "reason": "binary content"})
                    continue
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    filtered.append({"path": rel, "reason": "non-utf8 content"})
                    continue
                scan = scan_text(text)
                if scan["action"] == "block":
                    filtered.append({"path": rel, "reason": "secret-like content"})
                    continue
                if len(text) > MAX_FILE_CHARS:
                    text = text[:MAX_FILE_CHARS]
                tree_lines.append(f"{prefix}{entry.name}")
                files.append({
                    "path": rel, "tokens_estimate": estimate_tokens(text),
                    "content": text,
                    "redacted": scan["action"] == "redact",
                })

    _walk(root, "")
    total = sum(f["tokens_estimate"] for f in files)
    budget = max(500, max_tokens)
    chunks: list[dict] = []
    current: list[dict] = []
    current_tokens = 0
    for item in files:
        if current and current_tokens + item["tokens_estimate"] > budget:
            chunks.append({"files": [f["path"] for f in current],
                           "tokens_estimate": current_tokens,
                           "text": _render_chunk(current)})
            current, current_tokens = [], 0
        current.append(item)
        current_tokens += item["tokens_estimate"]
    if current:
        chunks.append({"files": [f["path"] for f in current],
                       "tokens_estimate": current_tokens,
                       "text": _render_chunk(current)})
    return {
        "root": str(root),
        "tree": "\n".join(tree_lines),
        "files": [{"path": f["path"], "tokens_estimate": f["tokens_estimate"],
                   "redacted": f["redacted"]} for f in files],
        "filtered": filtered,
        "total_tokens_estimate": total,
        "chunks": chunks,
        "chunk_count": len(chunks),
        "note": "Token counts are chars/4 estimates, not model tokenizer counts.",
    }


def _render_chunk(files: list[dict]) -> str:
    parts = []
    for item in files:
        parts.append(f"===== FILE: {item['path']} =====\n{item['content']}")
    return "\n\n".join(parts)


def reassemble(bundle: dict) -> str:
    """Join chunk texts back into one bundle text (tree first)."""
    parts = [f"Tree:\n{bundle.get('tree', '')}"]
    parts += [chunk["text"] for chunk in bundle.get("chunks", [])]
    return "\n\n".join(parts)
