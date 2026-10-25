"""
memory/markdown_notes.py — Batch 9: Memory-as-Markdown contract
(iwe-inspired: agent memory as human-readable, human-correctable
Markdown, not an opaque store).

Rule: every agent/skill memory write that goes through this module
also produces a dated, typed Markdown note under ONE browsable
directory, so a user can read and correct memory in plain files:

  <notes_dir>/YYYY-MM-DD-<slug>.md

Frontmatter (typed, iwe-style schema):

  ---
  type: fact | decision | preference | correction | note
  title: <title>
  created: YYYY-MM-DD
  source: <free-text source id, e.g. memory id or chat id>
  ---

``normalize`` merges duplicates (same type + normalized title):
bodies are concatenated under dated headings, the earliest file
survives, the rest are deleted, and a report is returned — nothing
is silently dropped.

The notes directory defaults to ``<workspace>/sangam-memory-notes``
and is overridable with ``SANGAM_MEMORY_NOTES_DIR`` (tests point it
at tmp). Writes run the retain-time defense scan: a blocked write
raises ValueError and stores nothing.
"""
from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path

from .defense import scan_text

NOTE_TYPES = ("fact", "decision", "preference", "correction", "note")


def notes_dir() -> Path:
    override = os.environ.get("SANGAM_MEMORY_NOTES_DIR", "").strip()
    if override:
        return Path(override)
    try:
        from ..config import settings
        base = Path(settings.WORKSPACE_ROOT)
    except Exception:  # noqa: BLE001 — fall back to cwd-adjacent dir
        base = Path.cwd()
    return base / "sangam-memory-notes"


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "note").strip().lower()).strip("-")
    return slug or "note"


def _frontmatter(body: str) -> tuple[dict, str]:
    """Parse the typed frontmatter; returns (fields, body_without)."""
    if not body.startswith("---\n"):
        return {}, body
    end = body.find("\n---", 4)
    if end == -1:
        return {}, body
    fields: dict[str, str] = {}
    for line in body[4:end].strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields, body[end + 4:].lstrip("\n")


def write_memory_note(
    kind: str, title: str, body: str, source: str = "",
    created: datetime | None = None,
) -> dict:
    """Write one dated, typed note. Returns {path, title, type,
    redacted, findings}. Blocked (secret-bearing) writes raise
    ValueError and store nothing."""
    kind = kind if kind in NOTE_TYPES else "note"
    scan = scan_text(body or "")
    if scan["action"] == "block":
        raise ValueError(
            "Note refused: text looks like it contains a credential or "
            "private key; remove it and try again.")
    text = scan["redacted_text"]
    day = (created or datetime.now(UTC)).strftime("%Y-%m-%d")
    directory = notes_dir()
    directory.mkdir(parents=True, exist_ok=True)
    slug = slugify(title)
    path = directory / f"{day}-{slug}.md"
    n = 2
    while path.exists():
        path = directory / f"{day}-{slug}-{n}.md"
        n += 1
    content = (
        f"---\ntype: {kind}\ntitle: {title.strip() or 'Untitled'}\n"
        f"created: {day}\nsource: {source}\n---\n\n{text.strip()}\n"
    )
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "filename": path.name, "type": kind,
            "title": title.strip() or "Untitled",
            "redacted": scan["action"] == "redact",
            "findings": scan["findings"]}


def list_memory_notes() -> list[dict]:
    """All notes in the directory, newest first, with frontmatter."""
    directory = notes_dir()
    if not directory.exists():
        return []
    notes = []
    for path in sorted(directory.glob("*.md"), reverse=True):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fields, body = _frontmatter(text)
        notes.append({
            "filename": path.name, "path": str(path),
            "type": fields.get("type", "note"),
            "title": fields.get("title", path.stem),
            "created": fields.get("created", ""),
            "source": fields.get("source", ""),
            "preview": body.strip()[:300],
        })
    return notes


def read_memory_note(filename: str) -> dict | None:
    """Read one note by filename. Refuses path traversal."""
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return None
    path = notes_dir() / filename
    if not path.exists() or path.suffix != ".md":
        return None
    text = path.read_text(encoding="utf-8")
    fields, body = _frontmatter(text)
    return {"filename": path.name, "type": fields.get("type", "note"),
            "title": fields.get("title", path.stem),
            "created": fields.get("created", ""),
            "source": fields.get("source", ""),
            "content": body.strip()}


def normalize_memory_notes() -> dict:
    """Merge duplicates (same type + normalized title). The earliest
    file keeps the merged body; later duplicates are deleted. Returns
    {merged_groups, removed_files, kept_files} — never silent."""
    directory = notes_dir()
    if not directory.exists():
        return {"merged_groups": 0, "removed_files": [], "kept_files": []}
    groups: dict[tuple[str, str], list[Path]] = {}
    for path in sorted(directory.glob("*.md")):
        try:
            fields, _ = _frontmatter(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        key = (fields.get("type", "note"),
               re.sub(r"\s+", " ", fields.get("title", path.stem)).strip().lower())
        groups.setdefault(key, []).append(path)
    removed: list[str] = []
    kept: list[str] = []
    merged_groups = 0
    for paths in groups.values():
        if len(paths) < 2:
            continue
        merged_groups += 1
        keeper = paths[0]  # sorted() => earliest dated filename first
        bodies: list[str] = []
        for path in paths:
            fields, body = _frontmatter(path.read_text(encoding="utf-8"))
            bodies.append(f"### From {path.name}\n\n{body.strip()}")
        keeper_text = keeper.read_text(encoding="utf-8")
        fields, _ = _frontmatter(keeper_text)
        header = (
            f"---\ntype: {fields.get('type', 'note')}\n"
            f"title: {fields.get('title', keeper.stem)}\n"
            f"created: {fields.get('created', '')}\n"
            f"source: {fields.get('source', '')}\n---\n\n"
        )
        keeper.write_text(header + "\n\n".join(bodies) + "\n", encoding="utf-8")
        kept.append(keeper.name)
        for extra in paths[1:]:
            extra.unlink()
            removed.append(extra.name)
    return {"merged_groups": merged_groups, "removed_files": removed,
            "kept_files": kept}
