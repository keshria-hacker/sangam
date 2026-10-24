"""
workflows.py — Phase 3 (all-in-one plan): visual DAG workflow runtime.

A workflow is a directed acyclic graph of typed nodes. There is no
arbitrary-code node by design (the plan's non-goal: arbitrary
third-party code execution); the closed node set is:

* ``text`` — render a template. ``{{input.<key>}}`` interpolates the
  run input; ``{{nodes.<node_id>}}`` interpolates a previous node's
  output (stringified). Missing keys render as ``""``.
* ``transform`` — ``op`` in {upper, lower, reverse, trim, title} over
  the previous node's output (or the run input's ``text``).
* ``retrieve`` — hybrid retrieval (Phase 2) over ``file_ids`` with
  ``query`` templated like ``text``; output is the list of citations.
* ``memory_save`` — save the templated ``content`` as a memory
  (kind from config, default semantic).
* ``http_fetch`` — fetch a public URL (SSRF-guarded, same guard as
  URL ingestion) and return its stripped text (truncated to 4000 chars).

Guarantees, all unit-tested:
* Validation: unique node ids, known types, edges only between known
  nodes, no cycles (Kahn topological sort; a cycle is a 422, not a hang).
* Timeouts: every node runs under ``asyncio.wait_for`` (default 30s,
  per-node ``timeout_seconds`` 1..300).
* Retries: per-node ``retries`` 0..2; a node that fails after its
  retries fails the run, marks every unexecuted node ``skipped``,
  and records the failure (node id, error, attempts) as the run's
  dead letter — the run row is kept, never deleted.
* Idempotency: a run requested with an ``idempotency_key`` that
  already has a finished run for the same workflow returns that run
  without re-executing.
* Replay: re-running a finished run with the same input creates a
  new run row linked via ``replay_of``.
* Scheduling: ``next_run`` is computed with the existing automation
  schedule parser; the scheduler loop in this module (opt-in via
  ``SANGAM_WORKFLOW_SCHEDULER=1``) ticks every 30s and runs due
  enabled workflows. It is off by default so tests never get
  surprise executions.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import datetime, UTC
from typing import Any

NODE_TYPES = {"text", "transform", "retrieve", "memory_save", "http_fetch"}
TRANSFORM_OPS = {"upper", "lower", "reverse", "trim", "title"}
DEFAULT_TIMEOUT_SECONDS = 30
MAX_RETRIES = 2

_TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


class WorkflowError(ValueError):
    """Validation or execution failure; message is safe to return."""


def validate_definition(definition: dict) -> list[str]:
    """Validate a workflow definition. Returns node ids in topo order.

    Raises WorkflowError on: non-dict definition, empty/missing nodes,
    duplicate node ids, unknown node type, edge to an unknown node,
    self-edge, or a cycle.
    """
    if not isinstance(definition, dict):
        raise WorkflowError("definition must be an object")
    nodes = definition.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise WorkflowError("definition.nodes must be a non-empty list")
    edges = definition.get("edges") or []
    if not isinstance(edges, list):
        raise WorkflowError("definition.edges must be a list")
    seen: set[str] = set()
    by_id: dict[str, dict] = {}
    for node in nodes:
        if not isinstance(node, dict) or not node.get("id"):
            raise WorkflowError("every node needs an id")
        if node["id"] in seen:
            raise WorkflowError(f"duplicate node id: {node['id']}")
        if node.get("type") not in NODE_TYPES:
            raise WorkflowError(f"unknown node type: {node.get('type')!r}")
        retries = node.get("retries", 0)
        if not isinstance(retries, int) or not 0 <= retries <= MAX_RETRIES:
            raise WorkflowError(f"node {node['id']}: retries must be 0..{MAX_RETRIES}")
        timeout = node.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        if not isinstance(timeout, (int, float)) or not 1 <= timeout <= 300:
            raise WorkflowError(f"node {node['id']}: timeout_seconds must be 1..300")
        if node["type"] == "transform" and node.get("config", {}).get("op") not in TRANSFORM_OPS:
            raise WorkflowError(f"node {node['id']}: transform op must be one of {sorted(TRANSFORM_OPS)}")
        seen.add(node["id"])
        by_id[node["id"]] = node
    indegree: dict[str, int] = {nid: 0 for nid in seen}
    outgoing: dict[str, list[str]] = {nid: [] for nid in seen}
    for edge in edges:
        if not isinstance(edge, dict) or "from" not in edge or "to" not in edge:
            raise WorkflowError("every edge needs 'from' and 'to'")
        if edge["from"] not in seen or edge["to"] not in seen:
            raise WorkflowError(f"edge references unknown node: {edge}")
        if edge["from"] == edge["to"]:
            raise WorkflowError(f"self-edge on node {edge['from']}")
        outgoing[edge["from"]].append(edge["to"])
        indegree[edge["to"]] += 1
    # Kahn's algorithm; leftover indegree > 0 means a cycle.
    queue = [nid for nid, deg in indegree.items() if deg == 0]
    order: list[str] = []
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for nxt in outgoing[nid]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if len(order) != len(seen):
        raise WorkflowError("definition contains a cycle")
    return order


def _lookup(path: str, context: dict) -> Any:
    cur: Any = context
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return ""
    return cur


def render_template(template: str, run_input: dict, node_outputs: dict) -> str:
    """Render ``{{input.x}}`` / ``{{nodes.<id>}}`` placeholders."""
    def _replace(match: re.Match) -> str:
        path = match.group(1)
        if path.startswith("input."):
            value = _lookup(path[len("input."):], run_input)
        elif path.startswith("nodes."):
            value = _lookup(path[len("nodes."):], node_outputs)
        else:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return str(value) if value is not None else ""
    return _TEMPLATE_RE.sub(_replace, template or "")


async def _run_node(node: dict, run_input: dict, node_outputs: dict) -> Any:
    """Execute one node (no retries/timeout here — the caller wraps)."""
    ntype = node["type"]
    config = node.get("config") or {}
    if ntype == "text":
        return render_template(config.get("template", ""), run_input, node_outputs)
    if ntype == "transform":
        op = config.get("op")
        source = config.get("source")
        if source:
            text = str(_lookup(source, {"nodes": node_outputs, "input": run_input}) or "")
        elif node_outputs:
            text = str(list(node_outputs.values())[-1] or "")
        else:
            text = str(run_input.get("text", "") or "")
        if op == "upper":
            return text.upper()
        if op == "lower":
            return text.lower()
        if op == "reverse":
            return text[::-1]
        if op == "trim":
            return text.strip()
        if op == "title":
            return text.title()
        raise WorkflowError(f"unknown transform op: {op}")
    if ntype == "retrieve":
        from .rag import retrieve_hybrid_chunks

        query = render_template(config.get("query", ""), run_input, node_outputs)
        file_ids = config.get("file_ids") or []
        chunks = retrieve_hybrid_chunks(query, file_ids, top_k=int(config.get("top_k", 5)))
        return [c.get("citation", {}) for c in chunks]
    if ntype == "memory_save":
        from .memory import MemoryKind, save_memory

        content = render_template(config.get("content", ""), run_input, node_outputs)
        kind = config.get("kind", "semantic")
        if kind not in ("episodic", "semantic", "procedural"):
            raise WorkflowError(f"unknown memory kind: {kind}")
        record = await save_memory(content, kind=MemoryKind(kind))
        return {"memory_id": record.id if record else None}
    if ntype == "http_fetch":
        import httpx

        from .ingest_url import html_to_text, validate_url

        url = render_template(config.get("url", ""), run_input, node_outputs).strip()
        validate_url(url)  # raises IngestUrlError (a ValueError) on rejection
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0), follow_redirects=False) as client:
            resp = await client.get(url, headers={"User-Agent": "Sangam/1.0 (+local-first)"})
        if resp.status_code != 200:
            raise WorkflowError(f"http_fetch returned HTTP {resp.status_code}")
        return html_to_text(resp.content.decode("utf-8", errors="replace"))[:4000]
    raise WorkflowError(f"unknown node type: {ntype}")


async def execute_definition(
    definition: dict,
    run_input: dict,
    *,
    on_node_done=None,
) -> tuple[dict, dict, str | None]:
    """Execute a validated definition.

    Returns (node_outputs, node_results, error). Validation errors
    raise WorkflowError before anything runs; a node failure does
    NOT raise — it returns the error, with node_results recording
    every node's status (failed node + skipped rest = dead letter).
    """
    order = validate_definition(definition)
    by_id = {n["id"]: n for n in definition["nodes"]}
    node_outputs: dict[str, Any] = {}
    node_results: dict[str, dict] = {}
    failed = False
    failure_error: str | None = None
    for nid in order:
        if failed:
            node_results[nid] = {"status": "skipped", "output": None, "error": None, "attempts": 0}
            continue
        node = by_id[nid]
        retries = node.get("retries", 0)
        timeout = node.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        attempts = 0
        last_error: Exception | None = None
        output: Any = None
        for attempt in range(retries + 1):
            attempts = attempt + 1
            try:
                output = await asyncio.wait_for(
                    _run_node(node, run_input, node_outputs), timeout=timeout
                )
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001 — recorded, then retried/failed
                last_error = exc
                if attempt < retries:
                    await asyncio.sleep(0.05 * (attempt + 1))
        if last_error is not None:
            node_results[nid] = {
                "status": "failed", "output": None,
                "error": str(last_error)[:500], "attempts": attempts,
            }
            failed = True
            failure_error = str(last_error)[:500]
        else:
            node_outputs[nid] = output
            node_results[nid] = {"status": "succeeded", "output": output, "error": None, "attempts": attempts}
        if on_node_done:
            on_node_done(nid, node_results[nid])
    return node_outputs, node_results, failure_error


async def run_workflow_row(wf: Any, db: Any, run_input: dict,
                           *, idempotency_key: str | None = None,
                           replay_of: str | None = None) -> Any:
    """Persist + execute one workflow run (used by routes and scheduler).

    Idempotency: if ``idempotency_key`` matches a finished run of the
    same workflow, that run is returned without re-executing.
    """
    import json as _json

    from sqlalchemy import select

    from .models import WorkflowRun

    if idempotency_key:
        existing = (await db.execute(
            select(WorkflowRun).where(
                WorkflowRun.workflow_id == wf.id,
                WorkflowRun.idempotency_key == idempotency_key,
                WorkflowRun.status.in_(["succeeded", "failed"]),
            )
        )).scalars().first()
        if existing:
            return existing
    definition = _json.loads(wf.definition_json or "{}")
    run = WorkflowRun(
        id=f"wfr-{uuid.uuid4().hex[:12]}",
        workflow_id=wf.id,
        user_id=wf.user_id,
        status="running",
        input_json=_json.dumps(run_input),
        idempotency_key=idempotency_key,
        replay_of=replay_of,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    try:
        outputs, results, error = await execute_definition(definition, run_input)
    except WorkflowError as exc:
        outputs, results, error = {}, {}, str(exc)
    run.output_json = _json.dumps(outputs)
    run.node_results_json = _json.dumps(results)
    run.error = error
    run.status = "failed" if error else "succeeded"
    run.finished_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(run)
    return run


async def start_workflow_scheduler(app=None) -> None:
    """Opt-in scheduler loop (SANGAM_WORKFLOW_SCHEDULER=1).

    Every 30s, runs enabled workflows whose trigger is not manual and
    whose next_run has passed, then recomputes next_run. Kept out of
    the default path so tests and smoke runs never get surprise runs.
    """
    if os.environ.get("SANGAM_WORKFLOW_SCHEDULER") != "1":
        return
    from sqlalchemy import select

    from .automations import parse_schedule
    from .database import get_session_factory
    from .models import Workflow

    while True:
        await asyncio.sleep(30)
        try:
            factory = get_session_factory()
            async with factory() as db:
                now = datetime.now(UTC)
                rows = (await db.execute(
                    select(Workflow).where(
                        Workflow.enabled.is_(True),
                        Workflow.trigger != "manual",
                        Workflow.next_run.is_not(None),
                        Workflow.next_run <= now,
                    )
                )).scalars().all()
                for wf in rows:
                    try:
                        await run_workflow_row(wf, db, {})
                    except Exception:
                        pass
                    wf.next_run = parse_schedule(wf.trigger)
                    await db.commit()
        except Exception:
            pass
