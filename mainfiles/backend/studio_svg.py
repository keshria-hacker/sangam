"""
backend/studio_svg.py — self-contained HTML+SVG diagram rendering
(spec/a6-studio-skills, Cluster H diagrams).

Renders a node/edge spec (the shape produced by diagrams.import_*)
as a standalone SVG document, optionally wrapped in a standalone HTML
page. Layout is deterministic (grid columns, 4px grid, one accent),
stdlib only, no Mermaid and no browser needed — so the output can be
parsed back in tests (xml.etree) instead of merely asserted present.

PNG export is deliberately NOT offered here: no raster renderer
(cairosvg / headless browser) is available in this environment, and a
fake PNG would violate the no-fabrication rule. The endpoint reports
svg|html only; PNG remains a browser-side (Mermaid) export.
"""
from __future__ import annotations

import html as _html
import re

from xml.sax.saxutils import escape

_HEX = re.compile(r"^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$")

DEFAULT_ACCENT = "#3A7BD5"
DEFAULT_FONT = "Inter, system-ui, sans-serif"


def _valid_accent(value: str | None) -> str:
    if value and _HEX.match(value.strip()):
        return value.strip()
    return DEFAULT_ACCENT


def render_svg(nodes: list[dict], edges: list[dict], title: str = "Diagram",
               accent: str | None = None, font: str | None = None) -> str:
    """Render nodes/edges to a standalone SVG string.

    nodes: [{id, label, shape?}] — shape in rect|ellipse|diamond|text.
    edges: [{from, to, label?}]. Unknown node refs in edges are dropped
    (never rendered as invented nodes); the drop count is in the
    companion render_report().
    """
    accent = _valid_accent(accent)
    font = font or DEFAULT_FONT
    nodes = [n for n in (nodes or []) if n.get("id")]
    # De-duplicate by id, first wins.
    seen: set[str] = set()
    uniq: list[dict] = []
    for node in nodes:
        if node["id"] not in seen:
            seen.add(node["id"])
            uniq.append(node)
    nodes = uniq
    cols = 3
    box_w, box_h, gap_x, gap_y, pad = 160, 56, 32, 40, 24
    width = pad * 2 + cols * box_w + (cols - 1) * gap_x
    rows = max(1, (len(nodes) + cols - 1) // cols)
    height = pad * 2 + rows * box_h + (rows - 1) * gap_y + (24 if title else 0)
    pos: dict[str, tuple[int, int]] = {}
    parts: list[str] = []
    for i, node in enumerate(nodes):
        col, row = i % cols, i // cols
        x = pad + col * (box_w + gap_x)
        y = pad + (24 if title else 0) + row * (box_h + gap_y)
        pos[node["id"]] = (x + box_w // 2, y + box_h // 2)
        label = escape(str(node.get("label") or node["id"]))[:120]
        shape = str(node.get("shape") or "rect").lower()
        if shape == "ellipse":
            parts.append(
                f'<ellipse cx="{x + box_w // 2}" cy="{y + box_h // 2}" rx="{box_w // 2}" '
                f'ry="{box_h // 2}" fill="none" stroke="{accent}" stroke-width="1"/>')
        elif shape == "diamond":
            cx, cy = x + box_w // 2, y + box_h // 2
            parts.append(
                f'<polygon points="{cx},{y} {x + box_w},{cy} {cx},{y + box_h} {x},{cy}" '
                f'fill="none" stroke="{accent}" stroke-width="1"/>')
        else:
            parts.append(
                f'<rect x="{x}" y="{y}" width="{box_w}" height="{box_h}" '
                f'fill="none" stroke="{accent}" stroke-width="1"/>')
        parts.append(
            f'<text x="{x + box_w // 2}" y="{y + box_h // 2 + 5}" '
            f'text-anchor="middle" font-family="{escape(font)}" font-size="13" '
            f'fill="#111827">{label}</text>')
    dropped = 0
    for edge in edges or []:
        src, dst = edge.get("from"), edge.get("to")
        if src not in pos or dst not in pos:
            dropped += 1
            continue
        x1, y1 = pos[src]
        x2, y2 = pos[dst]
        parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{accent}" stroke-width="1"/>')
        if edge.get("label"):
            parts.append(
                f'<text x="{(x1 + x2) // 2}" y="{(y1 + y2) // 2 - 4}" '
                f'text-anchor="middle" font-family="{escape(font)}" font-size="11" '
                f'fill="#374151">{escape(str(edge["label"]))[:80]}</text>')
    title_el = (
        f'<text x="{pad}" y="20" font-family="{escape(font)}" font-size="16" '
        f'font-weight="600" fill="#111827">{escape(str(title))[:120]}</text>'
        if title else ""
    )
    body = "\n".join([title_el] + parts) if title_el else "\n".join(parts)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(str(title))}">\n'
        f"{body}\n</svg>"
    )
    return svg


def render_html(nodes: list[dict], edges: list[dict], title: str = "Diagram",
                accent: str | None = None, font: str | None = None) -> str:
    """Standalone HTML page embedding the SVG (no external assets)."""
    svg = render_svg(nodes, edges, title=title, accent=accent, font=font)
    safe_title = _html.escape(str(title))
    return (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>{safe_title}</title>\n</head>\n<body>\n{svg}\n</body>\n</html>\n"
    )


def render_report(nodes: list[dict], edges: list[dict]) -> dict:
    """Counts + dropped-edge count for one render (no invented nodes)."""
    ids = {n.get("id") for n in (nodes or []) if n.get("id")}
    dropped = sum(1 for e in (edges or []) if e.get("from") not in ids or e.get("to") not in ids)
    return {"nodes": len(ids), "edges": len(edges or []),
            "rendered_edges": len(edges or []) - dropped, "dropped_edges": dropped}
