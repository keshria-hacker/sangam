"""Note graph (iwe's graph model, not its server).

Sangam's notebooks previously had regex-level wiki-links/backlinks
(O(notes) scan, one notebook, no rename propagation, dangling links
invisible). This module ports iwe's model in order:

  (a) link-index table, built on note write: [[WikiLink]],
      [[WikiLink|piped]], and Markdown links resolve via a title
      index; unresolved links are stored with target_note_id NULL so
      dangling links are visible, not silently dropped.
  (b) rename propagation: renaming a note rewrites [[Old Title]] in
      every linking doc (iwe's rename.rs algorithm) — no orphaned
      [[Old Title]].
  (c) header-tree + Extract-section: headers own blocks until the
      next equal/higher header (iwe's sections_builder rule).
  (d) graph-expansion retrieval: seeds expand along references /
      referenced_by with a token budget, periphery trimmed first.

Deliberately out of scope: iwe's LSP server (Sangam has no in-app
editor for it to attach to), Djot support, locale collation.

Storage: the ``note_link_index`` table lives in THIS module file,
following the lan_pairing pattern (importing this module registers
it on Base.metadata). The pure functions below operate on plain
dicts so they are testable without a database; the route layer
(parent wiring) persists rows via :func:`index_note_rows` and
applies rename :func:`rename_note_propagate` results.
"""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

__all__ = [
    "NoteLinkIndex", "parse_note_links", "resolve_links",
    "build_link_index", "backlinks_for", "rename_note_propagate",
    "parse_header_tree", "extract_section", "expand_retrieval",
    "index_note_rows",
]

WIKI_RE = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _now() -> datetime:
    return datetime.now(UTC)


class NoteLinkIndex(Base):
    """One row per link occurrence in a note. target_note_id NULL
    means dangling (no note with that title exists yet)."""
    __tablename__ = "note_link_index"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    notebook_id: Mapped[str] = mapped_column(String(32), index=True)
    source_note_id: Mapped[str] = mapped_column(String(32), index=True)
    target_title: Mapped[str] = mapped_column(String(200), index=True)
    target_note_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # wikilink | piped | markdown
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


def _new_id(prefix: str = "nli") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ------------------------------------------------------------------ parsing
def parse_note_links(content: str) -> list[dict]:
    """All links in a note, order-preserved, deduped by (target, kind).

    Markdown links to http(s)/mailto/anchors are NOT note links and
    are skipped; ``[text](Title.md)`` and ``[text](Title)`` are.
    """
    links: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for m in WIKI_RE.finditer(content or ""):
        target = m.group(1).strip()
        piped = m.group(2)
        kind = "piped" if piped is not None else "wikilink"
        if target and (target, kind) not in seen:
            seen.add((target, kind))
            links.append({"target": target,
                          "display": piped.strip() if piped else target,
                          "kind": kind})
    for m in MD_LINK_RE.finditer(content or ""):
        target = m.group(2).strip()
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = target[:-3] if target.endswith(".md") else target
        target = target.rsplit("/", 1)[-1].strip()
        if target and (target, "markdown") not in seen:
            seen.add((target, "markdown"))
            links.append({"target": target, "display": m.group(1).strip(),
                          "kind": "markdown"})
    return links


def resolve_links(links: list[dict], notes_by_title: dict[str, str]) -> list[dict]:
    """Attach target_note_id via the title index (exact match, then
    case-insensitive unique match). Unresolved -> None (dangling)."""
    lower_index: dict[str, list[str]] = {}
    for title, nid in notes_by_title.items():
        lower_index.setdefault(title.lower(), []).append(nid)
    rows = []
    for link in links:
        nid = notes_by_title.get(link["target"])
        if nid is None:
            cands = lower_index.get(link["target"].lower(), [])
            nid = cands[0] if len(cands) == 1 else None
        rows.append({**link, "target_note_id": nid})
    return rows


def build_link_index(notes: list[dict]) -> list[dict]:
    """notes: [{id, notebook_id, title, content}] -> index rows."""
    by_title = {n["title"]: n["id"] for n in notes}
    rows: list[dict] = []
    for n in notes:
        for link in resolve_links(parse_note_links(n.get("content", "")), by_title):
            rows.append({"id": _new_id(), "notebook_id": n["notebook_id"],
                         "source_note_id": n["id"], "target_title": link["target"],
                         "target_note_id": link["target_note_id"],
                         "kind": link["kind"]})
    return rows


def index_note_rows(note: dict, notes_by_title: dict[str, str]) -> list[dict]:
    """Index rows for a single note write (the on-write hook input)."""
    rows = []
    for link in resolve_links(parse_note_links(note.get("content", "")),
                              notes_by_title):
        rows.append({"id": _new_id(), "notebook_id": note["notebook_id"],
                     "source_note_id": note["id"], "target_title": link["target"],
                     "target_note_id": link["target_note_id"],
                     "kind": link["kind"]})
    return rows


def backlinks_for(rows: list[dict], note_id: str) -> list[str]:
    """Backlinks are an index lookup, not a grep (iwe's RefIndex)."""
    return sorted({r["source_note_id"] for r in rows
                   if r.get("target_note_id") == note_id})


# ------------------------------------------------------------------ rename
def _rewrite_links_in_text(content: str, old: str, new: str) -> str:
    """Rewrite links pointing at ``old`` to ``new``, preserving piped
    display text and markdown link text. Exact-title match only —
    guessing across case variants would rewrite the wrong links."""
    def _wiki(m: re.Match) -> str:
        target, piped = m.group(1).strip(), m.group(2)
        if target != old:
            return m.group(0)
        return f"[[{new}|{piped}]]" if piped is not None else f"[[{new}]]"

    out = WIKI_RE.sub(_wiki, content or "")

    def _md(m: re.Match) -> str:
        text, target = m.group(1), m.group(2)
        base = target[:-3] if target.endswith(".md") else target
        base = base.rsplit("/", 1)[-1]
        if base != old:
            return m.group(0)
        suffix = ".md" if target.endswith(".md") else ""
        return f"[{text}]({new}{suffix})"

    return MD_LINK_RE.sub(_md, out)


def rename_note_propagate(notes: list[dict], note_id: str, new_title: str) -> dict:
    """Rename a note AND rewrite every linking doc.

    Returns {"renamed": {id, old_title, new_title},
             "updates": [{note_id, old_content, new_content}]}
    — computation and writes are separate (iwe's Changes struct), so
    the caller can dry-run or apply. Notes whose content does not
    mention the old title are never touched.
    """
    by_id = {n["id"]: n for n in notes}
    note = by_id.get(note_id)
    if note is None:
        return {"error": f"Note not found: {note_id}", "updates": []}
    old_title = note["title"]
    if old_title == new_title:
        return {"renamed": {"id": note_id, "old_title": old_title,
                            "new_title": new_title}, "updates": []}
    updates = []
    for n in notes:
        if n["id"] == note_id:
            continue
        new_content = _rewrite_links_in_text(n.get("content", ""), old_title, new_title)
        if new_content != n.get("content", ""):
            updates.append({"note_id": n["id"], "old_content": n["content"],
                            "new_content": new_content})
    return {"renamed": {"id": note_id, "old_title": old_title,
                        "new_title": new_title}, "updates": updates}


# ------------------------------------------------------------------ sections
def parse_header_tree(content: str) -> list[dict]:
    """Header tree: each header owns blocks until the next header of
    equal-or-higher level (iwe's sections_builder rule). Pre-header
    blocks attach to a synthetic level-0 root section."""
    lines = (content or "").split("\n")
    root = {"level": 0, "title": "", "line_start": 1,
            "line_end": len(lines), "children": [], "content_lines": []}
    stack = [root]
    current_body_owner = root
    for i, line in enumerate(lines, start=1):
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m:
            level, title = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1]["level"] >= level:
                closed = stack.pop()
                closed["line_end"] = i - 1
            section = {"level": level, "title": title, "line_start": i,
                       "line_end": len(lines), "children": [],
                       "content_lines": []}
            stack[-1]["children"].append(section)
            stack.append(section)
            current_body_owner = section
        else:
            current_body_owner["content_lines"].append((i, line))
    for sec in stack:
        sec["line_end"] = len(lines)
    return root["children"]


def _find_section(sections: list[dict], title: str) -> dict | None:
    for sec in sections:
        if sec["title"] == title:
            return sec
        found = _find_section(sec["children"], title)
        if found:
            return found
    return None


def extract_section(content: str, header_title: str, new_title: str) -> dict:
    """Extract a section into a new note (iwe's extract op): the new
    note gets the section subtree; the source keeps the header with a
    [[NewTitle]] link in place of the body. Errors, never partial
    rewrites, when the header is missing or ambiguous."""
    sections = parse_header_tree(content)
    matches: list[dict] = []

    def _collect(secs: list[dict]) -> None:
        for sec in secs:
            if sec["title"] == header_title:
                matches.append(sec)
            _collect(sec["children"])

    _collect(sections)
    if not matches:
        return {"error": f"Section not found: {header_title!r}"}
    if len(matches) > 1:
        return {"error": f"Ambiguous section title: {header_title!r} "
                         f"({len(matches)} matches)"}
    sec = matches[0]
    lines = (content or "").split("\n")
    # Section body = lines after the header up to line_end, excluding
    # child-section header lines is wrong: the subtree INCLUDES
    # children, so take the raw slice and drop nothing.
    body = lines[sec["line_start"]:sec["line_end"]]
    # Trim trailing blank lines of the extracted body.
    while body and not body[-1].strip():
        body.pop()
    new_note = f"# {new_title}\n\n" + "\n".join(body) + ("\n" if body else "")
    header_line = lines[sec["line_start"] - 1]
    updated = lines[:sec["line_start"]] + [f"[[{new_title}]]"] + \
        lines[sec["line_end"]:]
    # Keep the header line itself: lines[:line_start] includes it.
    _ = header_line
    return {"new_note_title": new_title, "new_note_content": new_note,
            "updated_source_content": "\n".join(updated)}


# ------------------------------------------------------------------ retrieval
def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def expand_retrieval(notes_by_id: dict[str, dict], rows: list[dict],
                     seeds: list[str], depth: int = 2,
                     max_tokens: int = 4000) -> dict:
    """Graph-expansion retrieval (iwe's retrieve shape): seeds expand
    along references + referenced_by (backlinks) to ``depth`` levels.
    A token budget trims periphery first — seeds are never trimmed."""
    adjacency: dict[str, set[str]] = {}
    for r in rows:
        tgt = r.get("target_note_id")
        if not tgt:
            continue
        adjacency.setdefault(r["source_note_id"], set()).add(tgt)
        adjacency.setdefault(tgt, set()).add(r["source_note_id"])
    order: list[str] = []
    seen = set()
    frontier = [s for s in seeds if s in notes_by_id]
    for s in frontier:
        seen.add(s)
        order.append(s)
    for _ in range(max(depth, 0)):
        nxt = []
        for node in frontier:
            for nb in sorted(adjacency.get(node, ())):
                if nb not in seen and nb in notes_by_id:
                    seen.add(nb)
                    nxt.append(nb)
        order.extend(nxt)
        frontier = nxt
        if not frontier:
            break
    docs = [{"note_id": nid, "title": notes_by_id[nid].get("title", ""),
             "content": notes_by_id[nid].get("content", ""),
             "tokens": _approx_tokens(notes_by_id[nid].get("content", "")),
             "seed": nid in seeds} for nid in order]
    total = sum(d["tokens"] for d in docs)
    trimmed = False
    while total > max_tokens and len(docs) > len(seeds):
        # Trim periphery first: drop the last non-seed document.
        for i in range(len(docs) - 1, -1, -1):
            if not docs[i]["seed"]:
                total -= docs[i]["tokens"]
                docs.pop(i)
                trimmed = True
                break
        else:
            break
    return {"documents": docs, "total_tokens": total, "trimmed": trimmed,
            "depth": depth}
