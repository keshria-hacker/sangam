"""Non-destructive SVG annotation overlays (SketchVLM salvage).

SketchVLM's portable mechanism, read from its repo: a vision model
explains itself by producing an *editable SVG overlay* on top of an
input image — pointing, labelling and drawing — without modifying the
image itself. Sangam ports exactly that: validated annotations in
normalised (0..1) coordinates, rendered as a standalone SVG overlay
that sits over an image. No model is run here; the overlay is the
contract a model (or a user) fills in, and rendering is pure geometry.
"""
from __future__ import annotations

import html

ANNOTATION_TYPES = {"point", "label", "arrow", "rect", "circle", "path"}


def validate_annotations(annotations: object) -> list[dict]:
    errs: list[dict] = []

    def err(code: str, message: str, fix: str) -> dict:
        return {"code": code, "message": message, "supportedFixes": fix}

    if not isinstance(annotations, list) or not annotations:
        return [err("no-annotations", "annotations must be a non-empty list",
                    "Add at least one annotation.")]
    for i, ann in enumerate(annotations):
        path = f"annotations[{i}]"
        if not isinstance(ann, dict):
            errs.append(err("bad-annotation", f"{path} must be an object",
                            "Use {type, ...} with normalised coordinates."))
            continue
        atype = ann.get("type")
        if atype not in ANNOTATION_TYPES:
            errs.append(err("bad-type",
                            f"{path}.type must be one of {sorted(ANNOTATION_TYPES)}",
                            "Use point, label, arrow, rect, circle or path."))
            continue
        coords = []

        def _coord(name: str) -> None:
            value = ann.get(name)
            if not isinstance(value, (int, float)) or not (0.0 <= value <= 1.0):
                errs.append(err("bad-coordinate",
                                f"{path}.{name} must be a number in 0..1",
                                f"Set {name} to a normalised coordinate "
                                "(0 = left/top, 1 = right/bottom)."))
            else:
                coords.append(value)

        if atype in ("point", "label"):
            _coord("x")
            _coord("y")
            if atype == "label" and not (ann.get("text") or "").strip():
                errs.append(err("missing-label", f"{path}.text is required for labels",
                                "Add the label text."))
        elif atype == "arrow":
            _coord("x1")
            _coord("y1")
            _coord("x2")
            _coord("y2")
        elif atype == "rect":
            _coord("x")
            _coord("y")
            _coord("w")
            _coord("h")
        elif atype == "circle":
            _coord("cx")
            _coord("cy")
            _coord("r")
        elif atype == "path":
            points = ann.get("points")
            if not isinstance(points, list) or len(points) < 2:
                errs.append(err("bad-path", f"{path}.points needs >= 2 points",
                                "Supply [{x, y}, ...] in normalised coordinates."))
            else:
                for j, pt in enumerate(points):
                    if not isinstance(pt, dict) or not isinstance(pt.get("x"), (int, float)) \
                            or not isinstance(pt.get("y"), (int, float)) \
                            or not (0.0 <= pt["x"] <= 1.0) or not (0.0 <= pt["y"] <= 1.0):
                        errs.append(err("bad-coordinate",
                                        f"{path}.points[{j}] needs x/y in 0..1",
                                        "Fix the point coordinates."))
    return errs


def render_overlay_svg(annotations: list[dict], width: int = 1000,
                       height: int = 1000, accent: str = "#3A7BD5") -> str:
    """Render annotations as a standalone SVG overlay (viewBox 0 0
    width x height). The source image is never touched — the overlay
    is a separate layer. Raises ValueError on invalid annotations."""
    errs = validate_annotations(annotations)
    if errs:
        raise ValueError(f"invalid annotations: {errs[0]['message']}")
    W, H = int(width), int(height)

    def X(v: float) -> float:
        return round(v * W, 2)

    def Y(v: float) -> float:
        return round(v * H, 2)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
             f'width="{W}" height="{H}">',
             '<defs><marker id="ovArrow" viewBox="0 0 10 10" refX="9" refY="5" '
             'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
             f'<path d="M 0 1 L 9 5 L 0 9 z" fill="{accent}"/></marker></defs>']
    for ann in annotations:
        t = ann["type"]
        color = ann.get("color", accent)
        if t == "point":
            parts.append(f'<circle cx="{X(ann["x"])}" cy="{Y(ann["y"])}" r="10" '
                         f'fill="{color}"/>')
        elif t == "label":
            parts.append(f'<g><circle cx="{X(ann["x"])}" cy="{Y(ann["y"])}" r="6" '
                         f'fill="{color}"/><text x="{X(ann["x"]) + 12}" '
                         f'y="{Y(ann["y"]) + 4}" font-family="sans-serif" '
                         f'font-size="22" fill="{color}">'
                         f'{html.escape(str(ann["text"]))}</text></g>')
        elif t == "arrow":
            parts.append(f'<line x1="{X(ann["x1"])}" y1="{Y(ann["y1"])}" '
                         f'x2="{X(ann["x2"])}" y2="{Y(ann["y2"])}" '
                         f'stroke="{color}" stroke-width="3" '
                         'marker-end="url(#ovArrow)"/>')
        elif t == "rect":
            parts.append(f'<rect x="{X(ann["x"])}" y="{Y(ann["y"])}" '
                         f'width="{X(ann["w"])}" height="{Y(ann["h"])}" '
                         f'fill="none" stroke="{color}" stroke-width="3"/>')
        elif t == "circle":
            parts.append(f'<circle cx="{X(ann["cx"])}" cy="{Y(ann["cy"])}" '
                         f'r="{X(ann["r"])}" fill="none" stroke="{color}" '
                         'stroke-width="3"/>')
        elif t == "path":
            d = " ".join(f"{'M' if i == 0 else 'L'} {X(p['x'])} {Y(p['y'])}"
                         for i, p in enumerate(ann["points"]))
            parts.append(f'<path d="{d}" fill="none" stroke="{color}" '
                         'stroke-width="3" stroke-linejoin="round"/>')
    parts.append("</svg>")
    return "\n".join(parts)
