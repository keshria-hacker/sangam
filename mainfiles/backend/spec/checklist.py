"""Checklist stage: a checkable list derived from the spec's FRs.

Format (one item per line)::

    - [ ] C1 — <what to verify> — verifies: FR-001, FR-002 — method: pytest tests/test_x.py -q

Rules enforced in code, not by prompt:
  * sequential C-ids (C1, C2, ...);
  * every item names at least one FR and a non-empty verification method;
  * every FR in the spec is verified by at least one item (a checklist
    that silently drops a requirement is rejected).
"""
from __future__ import annotations

import re

from ..spec_chain import spec_frs

_ITEM_RE = re.compile(
    r"^-\s*\[ \]\s*(C\d+)\s*—\s*(.+)$", re.MULTILINE)
_FR_RE = re.compile(r"FR-(\d{3})")


def render_checklist(items: list[dict]) -> str:
    lines = ["# Checklist"]
    for i, item in enumerate(items, 1):
        verifies = ", ".join(item.get("verifies") or [])
        lines.append(
            f"- [ ] C{i} — {item.get('title', '')} "
            f"— verifies: {verifies} — method: {item.get('method', '')}")
    return "\n".join(lines) + "\n"


def parse_checklist(text: str) -> list[dict]:
    out = []
    for m in _ITEM_RE.finditer(text or ""):
        rest = m.group(2)
        verifies = sorted({f"FR-{n}" for n in _FR_RE.findall(rest)})
        method = ""
        mm = re.search(r"method:\s*(.+)$", rest)
        if mm:
            method = mm.group(1).strip()
        title = re.split(r"\s—\sverifies:", rest)[0].strip()
        out.append({"id": m.group(1), "title": title,
                    "verifies": verifies, "method": method})
    return out


def validate_checklist(text: str, spec: str) -> list[dict]:
    """Validate a checklist against a spec. Returns parsed items."""
    items = parse_checklist(text or "")
    if not items:
        raise ValueError("checklist requires at least one C-id item line")
    for i, item in enumerate(items, 1):
        if item["id"] != f"C{i}":
            raise ValueError(
                f"checklist must use sequential C-ids: expected C{i}, "
                f"got {item['id']}")
        if not item["verifies"]:
            raise ValueError(
                f"checklist item {item['id']} must name at least one FR "
                f"(— verifies: FR-001, ...)")
        if not item["method"]:
            raise ValueError(
                f"checklist item {item['id']} must name a verification "
                f"method (— method: ...)")
    covered = {fr for item in items for fr in item["verifies"]}
    missing = [fr for fr in spec_frs(spec or "") if fr not in covered]
    if missing:
        raise ValueError(
            "checklist does not verify requirement(s): "
            + ", ".join(missing))
    return items
