"""
backend/diagrams.py — editorial diagram catalogue, style guide, brand
profiles, and best-effort import (cathrynlavery/diagram-design analogue).

Style guide, as code:
- ONE accent color per diagram (the one or two things that matter);
- 1px hairline strokes, no shadows, coordinates on a 4px grid (a guide
  for the author, not an automated check — overlap/clipping checks are
  VISUAL: this module cannot detect overlapping nodes or clipped labels
  from Mermaid source alone, and never claims to).
- Templates ship with the guide defaults applied: a single accent
  (__ACCENT__ placeholder) and hairline styling via a Mermaid init
  directive.

Lint (POST /api/diagrams/lint) checks only what IS statically
checkable from source: more than one accent hex color, node count > 60,
any label > 60 chars, missing title. Everything else is a visual check.

Brands: stored in a small SQL table (Batch 2 precedent). Applying a
brand substitutes __ACCENT__ (and __FONT__ where the template's init
directive supports it).

Import is BEST-EFFORT, always: Mermaid passes through + lint; draw.io
XML (stdlib xml) maps basic shapes (rect/ellipse/diamond/text) to
nodes and connectors to edges; Excalidraw JSON maps rectangles/
ellipses/diamonds/text to nodes and arrows to edges. Anything else
becomes a warning — never an invented node. Both converters say so in
their warnings and the UI repeats it.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

DEFAULT_ACCENT = "#3A7BD5"
DEFAULT_FONT = "Inter, system-ui, sans-serif"

_INIT = (
    "%%{init: {'theme': 'base', 'themeVariables': "
    "{'primaryColor': '__ACCENT__', 'primaryBorderColor': '__ACCENT__', "
    "'lineColor': '__ACCENT__', 'fontFamily': '__FONT__'}}}%%\n"
)

# id, name, one-line use, mermaid template ({{label}} style placeholders
# are plain text the user edits; __ACCENT__/__FONT__ are brand slots).
CATALOGUE: list[dict] = [
    {"id": "flowchart", "name": "Flowchart", "use": "Steps and decisions in a process.",
     "template": _INIT + "flowchart TD\n    A[Start] --> B{Decision?}\n    B -- Yes --> C[Done]\n    B -- No --> A"},
    {"id": "sequence", "name": "Sequence diagram", "use": "Messages between actors over time.",
     "template": _INIT + "sequenceDiagram\n    actor User\n    participant App\n    User->>App: Request\n    App-->>User: Response"},
    {"id": "class", "name": "Class diagram", "use": "Classes, fields, and relationships.",
     "template": _INIT + "classDiagram\n    class Order {\n        +String id\n        +total()\n    }\n    Order --> Customer"},
    {"id": "er", "name": "ER diagram", "use": "Entities and their relationships.",
     "template": _INIT + "erDiagram\n    CUSTOMER ||--o{ ORDER : places\n    ORDER ||--|{ LINE-ITEM : contains"},
    {"id": "state", "name": "State diagram", "use": "States and transitions of one thing.",
     "template": _INIT + "stateDiagram-v2\n    [*] --> Idle\n    Idle --> Running : start\n    Running --> Idle : stop"},
    {"id": "gantt", "name": "Gantt chart", "use": "Tasks on a timeline.",
     "template": _INIT + "gantt\n    title Project plan\n    dateFormat YYYY-MM-DD\n    section Build\n    Design : 2026-01-05, 5d\n    Implement : 10d"},
    {"id": "pie", "name": "Pie chart", "use": "Shares of a whole.",
     "template": _INIT + "pie title Share\n    \"Alpha\" : 45\n    \"Beta\" : 35\n    \"Other\" : 20"},
    {"id": "journey", "name": "User journey", "use": "How a person feels across steps.",
     "template": _INIT + "journey\n    title Buying a ticket\n    section Discover\n      Search : 4: User\n      Compare : 3: User"},
    {"id": "mindmap", "name": "Mind map", "use": "Ideas branching from a central topic.",
     "template": _INIT + "mindmap\n  root((Topic))\n    Idea one\n    Idea two"},
    {"id": "git-graph", "name": "Git graph", "use": "Branches, merges, and releases.",
     "template": _INIT + "gitGraph\n    commit\n    branch feature\n    checkout feature\n    commit\n    checkout main\n    merge feature"},
    {"id": "quadrant", "name": "Quadrant chart", "use": "Two-by-two prioritisation (impact vs effort).",
     "template": _INIT + "quadrantChart\n    title Impact vs effort\n    x-axis Low effort --> High effort\n    y-axis Low impact --> High impact\n    quadrant-1 Do first\n    \"Quick win\": [0.2, 0.8]"},
    {"id": "timeline", "name": "Timeline", "use": "Events in chronological order.",
     "template": _INIT + "timeline\n    title Product history\n    2024 : Launch\n    2025 : Version two"},
    {"id": "sankey", "name": "Sankey diagram", "use": "Flows between stages, sized by volume.",
     "template": _INIT + "sankey-beta\n\n    Source A, Stage One, 10\n    Stage One, Done, 8\n    Source A, Done, 2"},
    # --- spec/a6-studio-skills: catalogue extended 13 -> 44. Templates are
    # Mermaid starters the user edits (same convention as the original 13);
    # self-contained HTML+SVG rendering for node/edge specs lives in
    # backend/studio_svg.py + POST /api/diagrams/export.
    {"id": "org-chart", "name": "Org chart", "use": "Reporting lines in a team or company.",
     "template": _INIT + "flowchart TD\n    CEO[Chief executive] --> CTO[Technology]\n    CEO --> CFO[Finance]\n    CTO --> Eng[Engineering]"},
    {"id": "decision-tree", "name": "Decision tree", "use": "A choice and its outcomes, branch by branch.",
     "template": _INIT + "flowchart TD\n    Q{Ship now?} -- Yes --> Ship[Ship]\n    Q -- No --> Fix[Fix first] --> Q"},
    {"id": "swimlane", "name": "Swimlane process", "use": "Who does each step, across lanes.",
     "template": _INIT + "flowchart TD\n    subgraph User\n    A[Request] --> B[Confirm]\n    end\n    subgraph System\n    B --> C[Process] --> D[Reply]\n    end"},
    {"id": "fishbone", "name": "Fishbone (Ishikawa)", "use": "Possible causes grouped by category.",
     "template": _INIT + "flowchart LR\n    Problem[Problem] --- People\n    Problem --- Process\n    Problem --- Tools\n    People --- Training"},
    {"id": "pyramid", "name": "Pyramid (flowchart starter)", "use": "Layers from base to peak, e.g. needs or priorities.",
     "template": _INIT + "flowchart TD\n    Base[Base layer] --> Mid[Middle layer] --> Peak[Peak]"},
    {"id": "funnel", "name": "Funnel (flowchart starter)", "use": "Stages that narrow, e.g. signup or sales.",
     "template": _INIT + "flowchart TD\n    Visit[Visit] --> SignUp[Sign up] --> Trial[Trial] --> Paid[Paid]"},
    {"id": "cycle", "name": "Cycle / loop", "use": "A repeating loop of stages.",
     "template": _INIT + "flowchart LR\n    A[Plan] --> B[Build] --> C[Measure] --> A"},
    {"id": "pros-cons", "name": "Pros and cons", "use": "Arguments for and against one decision.",
     "template": _INIT + "flowchart TD\n    D[Decision] --> P[Pros]\n    D --> C[Cons]\n    P --> P1[Pro one]\n    C --> C1[Con one]"},
    {"id": "roadmap", "name": "Roadmap", "use": "Phases across quarters or releases.",
     "template": _INIT + "flowchart LR\n    Q1[Now] --> Q2[Next] --> Q3[Later]\n    Q1 --- A[Milestone one]"},
    {"id": "kanban", "name": "Kanban board", "use": "Work moving across columns.",
     "template": _INIT + "kanban\n    Todo\n      Task one\n    Doing\n      Task two\n    Done\n      Task three"},
    {"id": "sitemap", "name": "Sitemap", "use": "Pages and their hierarchy on a site.",
     "template": _INIT + "flowchart TD\n    Home --> About\n    Home --> Products\n    Products --> Pricing"},
    {"id": "user-flow", "name": "User flow", "use": "Screens a person passes through to a goal.",
     "template": _INIT + "flowchart TD\n    Landing --> SignIn{Account?} -- Yes --> Dashboard\n    SignIn -- No --> Register --> Dashboard"},
    {"id": "wireframe", "name": "Wireframe (block starter)", "use": "Layout blocks for a page or screen.",
     "template": _INIT + "block-beta\n    columns 2\n    Header[\"Header\"]\n    Nav[\"Nav\"]\n    Main[\"Main\"]\n    Footer[\"Footer\"]"},
    {"id": "network", "name": "Network diagram", "use": "Nodes and links in a system or network.",
     "template": _INIT + "flowchart LR\n    Client --> LB[Load balancer] --> S1[Server one]\n    LB --> S2[Server two]\n    S1 --> DB[(Database)]\n    S2 --> DB"},
    {"id": "architecture", "name": "System architecture", "use": "Services and data stores at a glance.",
     "template": _INIT + "architecture-beta\n    group app(cloud)[App]\n    service web(internet)[Web] in app\n    service api(server)[API] in app\n    web:R -- L:api"},
    {"id": "bar-chart", "name": "Bar chart", "use": "Values compared across categories.",
     "template": _INIT + "xychart-beta\n    title \"Sales by month\"\n    x-axis [\"Jan\", \"Feb\", \"Mar\"]\n    bar [12, 19, 9]"},
    {"id": "line-chart", "name": "Line chart", "use": "A value changing over time.",
     "template": _INIT + "xychart-beta\n    title \"Growth\"\n    x-axis [\"Jan\", \"Feb\", \"Mar\"]\n    line [2, 5, 9]"},
    {"id": "radar-chart", "name": "Radar chart", "use": "Several dimensions scored at once.",
     "template": _INIT + "radar-beta\n    axis speed, quality, cost, scope\n    curve now{4, 3, 5, 2}\n    curve goal{5, 5, 4, 4}"},
    {"id": "packet", "name": "Packet / protocol diagram", "use": "Fields of a packet or message format.",
     "template": _INIT + "packet-beta\n    0-7: \"Version\"\n    8-15: \"Type\"\n    16-31: \"Length\""},
    {"id": "block-diagram", "name": "Block diagram", "use": "Functional blocks and signal flow.",
     "template": _INIT + "block-beta\n    columns 3\n    In[\"Input\"] --> Proc[\"Process\"] --> Out[\"Output\"]"},
    {"id": "hierarchy", "name": "Hierarchy tree", "use": "A tree from a root to leaves.",
     "template": _INIT + "flowchart TD\n    Root --> A[Branch one]\n    Root --> B[Branch two]\n    A --> A1[Leaf]"},
    {"id": "brainstorm", "name": "Brainstorm map", "use": "Raw ideas grouped after a prompt.",
     "template": _INIT + "mindmap\n  root((Prompt))\n    Theme one\n    Theme two"},
    {"id": "affinity", "name": "Affinity grouping", "use": "Notes clustered into themes.",
     "template": _INIT + "flowchart TD\n    subgraph Theme one\n    N1[Note one]\n    end\n    subgraph Theme two\n    N2[Note two]\n    end"},
    {"id": "storyboard", "name": "Storyboard", "use": "Scenes in order for a story or video.",
     "template": _INIT + "flowchart LR\n    S1[Scene one] --> S2[Scene two] --> S3[Scene three]"},
    {"id": "gauge", "name": "Gauge (pie starter)", "use": "One value against a target, as a share.",
     "template": _INIT + "pie title Progress\n    \"Done\" : 70\n    \"Left\" : 30"},
    {"id": "donut", "name": "Donut chart (pie starter)", "use": "Shares of a whole with a centre label.",
     "template": _INIT + "pie showData title Share\n    \"Alpha\" : 45\n    \"Beta\" : 35\n    \"Other\" : 20"},
    {"id": "venn", "name": "Venn (flowchart starter)", "use": "Overlap between two or three sets.",
     "template": _INIT + "flowchart TD\n    A[Set A] --- AB[Overlap] --- B[Set B]"},
    {"id": "dependency", "name": "Dependency graph", "use": "What blocks what, in build order.",
     "template": _INIT + "flowchart TD\n    A[Task A] --> B[Task B]\n    A --> C[Task C]\n    B --> D[Task D]\n    C --> D"},
    {"id": "data-flow", "name": "Data-flow diagram", "use": "Data moving through processes and stores.",
     "template": _INIT + "flowchart LR\n    User --> P1[Validate] --> DB[(Store)]\n    DB --> P2[Report] --> User"},
    {"id": "entity-tree", "name": "Entity tree", "use": "Nested parts of one thing, e.g. a bill of materials.",
     "template": _INIT + "flowchart TD\n    Whole --> PartA[Part A]\n    Whole --> PartB[Part B]\n    PartA --> Sub[Sub-part]"},
    {"id": "checklist-flow", "name": "Checklist flow", "use": "Steps that must all pass, with a fail path.",
     "template": _INIT + "flowchart TD\n    S1[Step one] --> S2{Pass?} -- Yes --> S3[Step two]\n    S2 -- No --> Fix[Fix and retry] --> S1"},
]

_CATALOGUE_BY_ID = {e["id"]: e for e in CATALOGUE}


def get_template(diagram_id: str) -> dict | None:
    return _CATALOGUE_BY_ID.get(diagram_id)


# ------------------------------------------------------------------ lint

_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_NODE_RE = re.compile(r"\b([A-Za-z0-9_]+)\s*[\[{(]")
_LABEL_RE = re.compile(r"[\[{(]([^\]})]{1,})[\]})]")


def lint_mermaid(mermaid: str) -> list[dict]:
    """Statically checkable style-guide issues only."""
    issues: list[dict] = []
    text = mermaid or ""
    accents = sorted({h.lower() for h in _HEX_RE.findall(text)})
    if len(accents) > 1:
        issues.append({
            "level": "warn", "rule": "multiple-accent-colors",
            "message": f"More than one accent hex color found ({', '.join(accents)}); the style guide allows one.",
        })
    nodes = {m.group(1) for m in _NODE_RE.finditer(text)}
    # Sequence/ER/git lines also define participants; count them loosely.
    if len(nodes) > 60:
        issues.append({
            "level": "warn", "rule": "too-many-nodes",
            "message": f"{len(nodes)} nodes found; keep diagrams at or under 60 nodes.",
        })
    for m in _LABEL_RE.finditer(text):
        label = m.group(1).strip()
        if len(label) > 60:
            issues.append({
                "level": "warn", "rule": "label-too-long",
                "message": f"Label over 60 chars: {label[:60]}…",
            })
            break
    if not re.search(r"(?m)^\s*(title|accTitle)\b", text) and "title" not in text.lower():
        issues.append({
            "level": "hint", "rule": "missing-title",
            "message": "No title found — add one so the diagram stands alone.",
        })
    return issues


# ----------------------------------------------------------------- brands

class DiagramBrand(Base):
    """A saved brand profile: one accent, one font, optional logo text."""

    __tablename__ = "diagram_brands"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    accent: Mapped[str] = mapped_column(String(32), default=DEFAULT_ACCENT)
    font: Mapped[str] = mapped_column(String(256), default=DEFAULT_FONT)
    logo_text: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


def apply_brand(template: str, accent: str, font: str | None = None) -> str:
    """Substitute brand slots in a template. Unknown slots stay as-is."""
    out = template.replace("__ACCENT__", accent or DEFAULT_ACCENT)
    out = out.replace("__FONT__", font or DEFAULT_FONT)
    return out


# ----------------------------------------------------------------- import

def _safe_label(raw: str) -> str:
    label = re.sub(r"\s+", " ", (raw or "").strip())
    return label.replace("[", "(").replace("]", ")").replace("{", "(").replace("}", ")") or "Untitled"


def import_mermaid(content: str) -> dict:
    return {"mermaid": content, "warnings": ["Mermaid import is a pass-through: lint results below are the only checks applied."] + [
        f"{i['rule']}: {i['message']}" for i in lint_mermaid(content)
    ]}


def import_drawio(content: str) -> dict:
    """Parse .drawio XML (stdlib xml) -> flowchart. Best-effort."""
    warnings = ["Draw.io import is best-effort: only basic shapes and connectors are converted."]
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        return {"mermaid": "flowchart TD\n", "warnings": warnings + [f"Could not parse draw.io XML: {exc}"]}
    nodes: dict[str, tuple[str, str]] = {}  # cell id -> (node id, shape)
    edges: list[tuple[str, str, str]] = []
    order: list[tuple[str, str, str]] = []
    cells = [c for c in root.iter("mxCell")
             if c.get("vertex") == "1" or c.get("edge") == "1"]
    # Pass 1: vertices (edges are resolved in pass 2, whatever the order).
    for cell in cells:
        if cell.get("vertex") != "1":
            continue
        value = (cell.get("value") or "").strip()
        style = cell.get("style") or ""
        if not value:
            warnings.append("Skipped a shape with no label text.")
            continue
        node_id = f"N{len(order) + 1}"
        if "ellipse" in style:
            shape = "round"
        elif "rhombus" in style or "diamond" in style:
            shape = "diamond"
        elif "image" in style or "swimlane" in style:
            warnings.append(f"Shape '{value[:40]}' uses an unsupported style; rendered as a plain box.")
            shape = "box"
        else:
            shape = "box"
        nodes[cell.get("id", node_id)] = (node_id, shape)
        order.append((node_id, shape, _safe_label(value)))
    # Pass 2: edges.
    for cell in cells:
        if cell.get("edge") != "1":
            continue
        value = (cell.get("value") or "").strip()
        src, tgt = cell.get("source"), cell.get("target")
        if not src or not tgt or src not in nodes or tgt not in nodes:
            warnings.append("Skipped a connector without both ends mapped to shapes.")
            continue
        label = _safe_label(value)
        edges.append((nodes[src][0], nodes[tgt][0], label))
    lines = ["flowchart TD"]
    for node_id, shape, label in order:
        if shape == "diamond":
            lines.append(f"    {node_id}{{{label}}}")
        elif shape == "round":
            lines.append(f"    {node_id}({label})")
        else:
            lines.append(f"    {node_id}[{label}]")
    for src, tgt, label in edges:
        lines.append(f"    {src} --> {tgt}" if not label or label == "Untitled" else f"    {src} -- {label} --> {tgt}")
    return {"mermaid": "\n".join(lines) + "\n", "warnings": warnings}


def import_excalidraw(content: str) -> dict:
    """Parse Excalidraw JSON -> flowchart. Best-effort."""
    warnings = ["Excalidraw import is best-effort: only rectangles, ellipses, diamonds, text, and arrows are converted."]
    try:
        data = json.loads(content)
    except ValueError as exc:
        return {"mermaid": "flowchart TD\n", "warnings": warnings + [f"Could not parse Excalidraw JSON: {exc}"]}
    elements = data.get("elements", []) if isinstance(data, dict) else []
    # First pass: text bound to a shape becomes that shape's label.
    shape_labels: dict[str, str] = {}
    for el in elements:
        if isinstance(el, dict) and el.get("type") == "text" and el.get("containerId"):
            shape_labels[el["containerId"]] = _safe_label(str(el.get("text", "")))
    nodes: dict[str, tuple[str, str]] = {}
    order: list[tuple[str, str, str]] = []
    arrows: list[dict] = []
    for el in elements:
        if not isinstance(el, dict):
            continue
        etype = el.get("type")
        if etype in ("rectangle", "ellipse", "diamond"):
            node_id = f"N{len(order) + 1}"
            label = shape_labels.get(el.get("id"), _safe_label(str(el.get("name") or el.get("id") or "Shape")))
            shape = {"rectangle": "box", "ellipse": "round", "diamond": "diamond"}[etype]
            nodes[el.get("id")] = (node_id, shape)
            order.append((node_id, shape, label))
        elif etype == "text" and not el.get("containerId"):
            node_id = f"N{len(order) + 1}"
            nodes[el.get("id")] = (node_id, "box")
            order.append((node_id, "box", _safe_label(str(el.get("text", "")))))
        elif etype == "arrow":
            arrows.append(el)
        elif etype in ("line", "freedraw", "image", "frame", "selection"):
            warnings.append(f"Skipped unsupported element of type '{etype}'.")
    lines = ["flowchart TD"]
    for node_id, shape, label in order:
        if shape == "diamond":
            lines.append(f"    {node_id}{{{label}}}")
        elif shape == "round":
            lines.append(f"    {node_id}({label})")
        else:
            lines.append(f"    {node_id}[{label}]")
    for arrow in arrows:
        start = (arrow.get("startBinding") or {}).get("elementId")
        end = (arrow.get("endBinding") or {}).get("elementId")
        if not start or not end or start not in nodes or end not in nodes:
            warnings.append("Skipped an arrow without both ends bound to shapes.")
            continue
        lines.append(f"    {nodes[start][0]} --> {nodes[end][0]}")
    return {"mermaid": "\n".join(lines) + "\n", "warnings": warnings}


def import_diagram(fmt: str, content: str) -> dict:
    fmt = (fmt or "").lower()
    if fmt == "mermaid":
        return import_mermaid(content)
    if fmt == "drawio":
        return import_drawio(content)
    if fmt == "excalidraw":
        return import_excalidraw(content)
    raise ValueError(f"Unsupported import format: {fmt} (expected mermaid, drawio, or excalidraw)")
