"""api_routes/code_graph_routes.py — code-graph check/query/export endpoints.

Parent wiring: import this module from api.py (it registers onto the
shared router from .common, like the other route modules); no api.py
edit is made by the code-graph worker.

Endpoints (all read-only, filesystem-rooted, no DB dependency):
  GET /knowledge/graph/check   fingerprint drift vs the cached graph
  GET /code-graph/export       ?format=json|html (graph export)
  GET /code-graph/find-code    ?q=&top_k=
  GET /code-graph/file-api     ?file=
  GET /code-graph/find-all     ?pattern=
  GET /code-graph/repo-map
  GET /code-graph/trace        ?symbol=&direction=&depth=
  GET /code-graph/affected     ?symbol=
  GET /code-graph/diagram      architecture diagram IR from the graph

``root`` (optional, workspace-relative subdirectory) scopes the graph;
paths escaping the workspace root are rejected.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..auth import get_current_user
from ..code_graph import cached_graph, ensure_fresh_graph
from ..code_graph_queries import (
    affected,
    check_freshness_tool,
    explain_change,
    export_graph_html,
    export_graph_json,
    file_api,
    find_all,
    find_code,
    find_orphans,
    impact_analysis,
    layering_check,
    repo_map,
    trace_calls,
)
from ..diagram_ir import diagram_from_code_graph, validate_diagram
from .common import router


def _resolve_root(root: str | None) -> Path:
    from ..tools.builtin import _get_workspace_root
    base = _get_workspace_root()
    if not root:
        return base
    cand = (base / root).resolve()
    try:
        cand.relative_to(base)
    except ValueError:
        raise ValueError(f"root escapes workspace: {root!r}")
    return cand


def _graph_or_error(root: str | None):
    try:
        base = _resolve_root(root)
    except ValueError as exc:
        return None, None, {"error": str(exc)}
    graph, warning = ensure_fresh_graph(base)
    if graph is None:
        return None, warning, {"error": warning or "code graph unavailable"}
    return graph, warning, None


@router.get("/knowledge/graph/check")
async def graph_check(root: str | None = Query(default=None),
                      user=Depends(get_current_user)):
    """Freshness gate: added/removed/changed/stale of the live tree
    vs the last BUILT graph. This endpoint never rebuilds — it diffs
    against the cached graph (building a baseline only when no graph
    has ever been built for this root), so drift is actually visible
    instead of being rebuilt away before the diff."""
    try:
        base = _resolve_root(root)
    except ValueError as exc:
        return {"error": str(exc), "fresh": False}
    graph = cached_graph(base)
    baseline = False
    if graph is None:
        graph, warning = ensure_fresh_graph(base)
        baseline = True
        if graph is None:
            return {"fresh": False, "error": warning}
    drift = check_freshness_tool(base, graph)
    drift["baseline_built"] = baseline
    return drift


@router.get("/code-graph/export")
async def graph_export(format: str = Query(default="json"),
                       root: str | None = Query(default=None),
                       user=Depends(get_current_user)):
    """Graph export (closes the Knowledge Export gap: it exported
    memories JSON only). JSON is the directed node/edge dump; HTML is
    a standalone file://-openable viewer with everything inlined."""
    graph, warning, err = _graph_or_error(root)
    if err:
        return err
    if format == "html":
        return HTMLResponse(content=export_graph_html(graph))
    out = export_graph_json(graph)
    out["warning"] = warning
    return out


@router.get("/code-graph/find-code")
async def graph_find_code(q: str = Query(min_length=1),
                          top_k: int = Query(default=10, ge=1, le=50),
                          root: str | None = Query(default=None),
                          user=Depends(get_current_user)):
    graph, warning, err = _graph_or_error(root)
    if err:
        return err
    base = _resolve_root(root)
    out = find_code(graph, q, top_k=top_k, root=base)
    out["warning"] = warning
    return out


@router.get("/code-graph/file-api")
async def graph_file_api(file: str = Query(min_length=1),
                         root: str | None = Query(default=None),
                         user=Depends(get_current_user)):
    graph, _warning, err = _graph_or_error(root)
    if err:
        return err
    return file_api(graph, file)


@router.get("/code-graph/find-all")
async def graph_find_all(pattern: str = Query(min_length=1),
                         root: str | None = Query(default=None),
                         user=Depends(get_current_user)):
    graph, _warning, err = _graph_or_error(root)
    if err:
        return err
    return find_all(graph, pattern)


@router.get("/code-graph/repo-map")
async def graph_repo_map(root: str | None = Query(default=None),
                         user=Depends(get_current_user)):
    graph, _warning, err = _graph_or_error(root)
    if err:
        return err
    return repo_map(graph)


@router.get("/code-graph/trace")
async def graph_trace(symbol: str = Query(min_length=1),
                      direction: str = Query(default="out"),
                      depth: str = Query(default="1"),
                      root: str | None = Query(default=None),
                      user=Depends(get_current_user)):
    graph, _warning, err = _graph_or_error(root)
    if err:
        return err
    return trace_calls(graph, symbol, direction=direction,
                       depth=depth if depth == "all" else int(depth))


@router.get("/code-graph/affected")
async def graph_affected(symbol: str = Query(min_length=1),
                         root: str | None = Query(default=None),
                         user=Depends(get_current_user)):
    graph, _warning, err = _graph_or_error(root)
    if err:
        return err
    return affected(graph, symbol)


@router.get("/code-graph/impact")
async def graph_impact(symbol: str = Query(min_length=1),
                       root: str | None = Query(default=None),
                       user=Depends(get_current_user)):
    """Cross-file impact analysis for one symbol (callers, files
    touched, risk note, evidence block)."""
    graph, warning, err = _graph_or_error(root)
    if err:
        return err
    out = impact_analysis(graph, symbol)
    out["warning"] = warning
    return out


@router.get("/code-graph/orphans")
async def graph_orphans(root: str | None = Query(default=None),
                        user=Depends(get_current_user)):
    """Dead-code candidates: symbols with no caller, not exported,
    not a main entry point. Candidates only — nothing is deleted."""
    graph, warning, err = _graph_or_error(root)
    if err:
        return err
    out = find_orphans(graph)
    out["warning"] = warning
    return out


class ExplainChangeIn(BaseModel):
    diff: str
    root: str | None = None


@router.post("/code-graph/explain-change")
async def graph_explain_change(payload: ExplainChangeIn,
                               user=Depends(get_current_user)):
    """Explain a unified diff via the graph: files touched, symbols
    in those files, and each mentioned symbol's impact. Read-only
    over the graph; the diff itself is never applied."""
    graph, warning, err = _graph_or_error(payload.root)
    if err:
        return err
    out = explain_change(graph, payload.diff)
    out["warning"] = warning
    return out


@router.get("/code-graph/diagram")
async def graph_diagram(root: str | None = Query(default=None),
                        user=Depends(get_current_user)):
    """Architecture diagram IR generated FROM the code graph, so it
    is measured by default (pinned to the workspace git revision
    when the workspace is a git checkout)."""
    graph, warning, err = _graph_or_error(root)
    if err:
        return err
    base = _resolve_root(root)
    doc = diagram_from_code_graph(graph, repo_root=base)
    return {"diagram": doc, "validation": validate_diagram(doc),
            "warning": warning}
