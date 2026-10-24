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
* Batch 3 nodes: ``llm`` (model call via the provider stream),
  ``agent`` (a team run), ``tool`` (read-only web_search/code_map only),
  ``code`` (restricted expression evaluator — NOT arbitrary code),
  ``condition`` (branch true/false for downstream ``run_if`` gates),
  ``loop`` (render a template per list item), ``crawl`` (same-host BFS,
  SSRF-guarded, capped pages/depth), ``extract`` (regex named groups or
  JSON path), ``prompt_transform`` (render system/user prompt parts).
  Any node may carry ``run_if``: a template that must render truthy or
  the node records ``skipped`` (reason run_if false) without failing.

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

NODE_TYPES = {"text", "transform", "retrieve", "memory_save", "http_fetch",
              # Batch 3 node library (engine unchanged: same validation,
              # timeouts, retries, dead letters, idempotency, replay).
              "llm", "agent", "tool", "code", "condition", "loop",
              "crawl", "extract", "prompt_transform"}
TRANSFORM_OPS = {"upper", "lower", "reverse", "trim", "title"}
# Tool node allowlist: read-only tools only. Write/execute tools are
# excluded from workflows by design — a non-interactive run must never
# silently write files or run shell commands.
TOOL_NODE_TOOLS = {"web_search", "code_map"}
CONDITION_OPS = {"==", "!=", ">", "<", ">=", "<=", "contains"}
SAFE_BUILTINS = {"len": len, "str": str, "int": int, "float": float,
                 "abs": abs, "min": min, "max": max, "sorted": sorted}
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
        _validate_new_node(node)
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


def render_template(template: str, run_input: dict, node_outputs: dict,
                    extra: dict | None = None) -> str:
    """Render ``{{input.x}}`` / ``{{nodes.<id>}}`` placeholders.

    ``extra`` adds top-level names (used by the loop node for
    ``{{item}}`` / ``{{item_index}}``).
    """
    context = {"input": run_input, "nodes": node_outputs, **(extra or {})}

    def _replace(match: re.Match) -> str:
        value = _lookup(match.group(1), context)
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return str(value) if value is not None else ""
    return _TEMPLATE_RE.sub(_replace, template or "")


def _validate_new_node(node: dict) -> None:
    """Per-type config validation for Batch 3 node types."""
    ntype, config, nid = node["type"], node.get("config") or {}, node["id"]
    if ntype == "llm" and not config.get("prompt"):
        raise WorkflowError(f"node {nid}: llm needs config.prompt")
    if ntype == "agent" and not config.get("team"):
        raise WorkflowError(f"node {nid}: agent needs config.team (a team id)")
    if ntype == "tool" and config.get("tool") not in TOOL_NODE_TOOLS:
        raise WorkflowError(f"node {nid}: tool must be one of {sorted(TOOL_NODE_TOOLS)}")
    if ntype == "code" and not config.get("expression"):
        raise WorkflowError(f"node {nid}: code needs config.expression")
    if ntype == "condition":
        if config.get("op") not in CONDITION_OPS:
            raise WorkflowError(f"node {nid}: condition op must be one of {sorted(CONDITION_OPS)}")
        if "left" not in config or "right" not in config:
            raise WorkflowError(f"node {nid}: condition needs left and right")
    if ntype == "loop" and (not config.get("items") or not config.get("item_template")):
        raise WorkflowError(f"node {nid}: loop needs items and item_template")
    if ntype == "crawl":
        if not config.get("url"):
            raise WorkflowError(f"node {nid}: crawl needs config.url")
        if not 1 <= int(config.get("max_pages", 5)) <= 20:
            raise WorkflowError(f"node {nid}: crawl max_pages must be 1..20")
        if not 0 <= int(config.get("max_depth", 1)) <= 2:
            raise WorkflowError(f"node {nid}: crawl max_depth must be 0..2")
    if ntype == "extract" and not (config.get("pattern") or config.get("json_path")):
        raise WorkflowError(f"node {nid}: extract needs pattern or json_path")


def _truthy(text: str) -> bool:
    return text.strip().lower() not in ("", "false", "0", "no", "none", "null")


# --- Restricted expression evaluator for the ``code`` node -----------------
# No imports, no attribute access, no function calls except a small safe
# set. This is deliberately NOT arbitrary code execution: a workflow run
# is non-interactive, so it must never run unchecked code. Full code
# execution stays in the Code Agent tab behind its approval gate.

import ast as _ast


def _eval_expr(tree: _ast.AST, variables: dict) -> Any:
    if isinstance(tree, _ast.Expression):
        return _eval_expr(tree.body, variables)
    if isinstance(tree, _ast.Constant):
        return tree.value
    if isinstance(tree, _ast.Name):
        if tree.id in variables:
            return variables[tree.id]
        raise WorkflowError(f"code node: unknown name {tree.id!r}")
    if isinstance(tree, _ast.BinOp):
        left, right = _eval_expr(tree.left, variables), _eval_expr(tree.right, variables)
        if isinstance(tree.op, _ast.Add):
            return left + right
        if isinstance(tree.op, _ast.Sub):
            return left - right
        if isinstance(tree.op, _ast.Mult):
            return left * right
        if isinstance(tree.op, _ast.Div):
            return left / right
        if isinstance(tree.op, _ast.Mod):
            return left % right
        if isinstance(tree.op, _ast.FloorDiv):
            return left // right
        raise WorkflowError("code node: operator not allowed")
    if isinstance(tree, _ast.UnaryOp) and isinstance(tree.op, _ast.USub):
        return -_eval_expr(tree.operand, variables)
    if isinstance(tree, _ast.Compare) and len(tree.ops) == 1 and len(tree.comparators) == 1:
        left, right = _eval_expr(tree.left, variables), _eval_expr(tree.comparators[0], variables)
        op = tree.ops[0]
        if isinstance(op, _ast.Eq):
            return left == right
        if isinstance(op, _ast.NotEq):
            return left != right
        if isinstance(op, _ast.Gt):
            return left > right
        if isinstance(op, _ast.Lt):
            return left < right
        if isinstance(op, _ast.GtE):
            return left >= right
        if isinstance(op, _ast.LtE):
            return left <= right
        if isinstance(op, _ast.In):
            return left in right
        raise WorkflowError("code node: comparison not allowed")
    if isinstance(tree, _ast.BoolOp):
        values = [_eval_expr(v, variables) for v in tree.values]
        return all(values) if isinstance(tree.op, _ast.And) else any(values)
    if isinstance(tree, _ast.IfExp):
        return _eval_expr(tree.body, variables) if _eval_expr(tree.test, variables) else _eval_expr(tree.orelse, variables)
    if isinstance(tree, ( _ast.List, _ast.Tuple)):
        return [_eval_expr(e, variables) for e in tree.elts]
    if isinstance(tree, _ast.Dict):
        return {_eval_expr(k, variables): _eval_expr(v, variables)
                for k, v in zip(tree.keys, tree.values) if k is not None}
    if isinstance(tree, _ast.Subscript):
        return _eval_expr(tree.value, variables)[_eval_expr(tree.slice, variables)]
    if isinstance(tree, _ast.Call) and isinstance(tree.func, _ast.Name) and tree.func.id in SAFE_BUILTINS:
        return SAFE_BUILTINS[tree.func.id](*[_eval_expr(a, variables) for a in tree.args])
    raise WorkflowError("code node: expression form not allowed")


def eval_code_expression(expression: str, variables: dict) -> Any:
    """Evaluate a restricted expression. Raises WorkflowError on anything else."""
    try:
        tree = _ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise WorkflowError(f"code node: invalid expression: {exc}") from exc
    return _eval_expr(tree, variables)


async def _run_node(node: dict, run_input: dict, node_outputs: dict, db: Any = None) -> Any:
    """Execute one node (no retries/timeout here — the caller wraps).

    ``db`` is required by the llm/agent/tool nodes (provider keys, team
    runs); it is threaded through from run_workflow_row. Direct
    execute_definition callers without a db get a clear error from
    those node types instead of a silent failure.
    """
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
    if ntype == "llm":
        if db is None:
            raise WorkflowError("llm node needs a database session (provider keys)")
        from .llm import default_model_id, stream_completion

        prompt = render_template(config.get("prompt", ""), run_input, node_outputs)
        system = render_template(config.get("system", ""), run_input, node_outputs)
        model = config.get("model") or await default_model_id(db)
        if not model:
            raise WorkflowError("llm node: no model configured")
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        parts: list[str] = []
        async for chunk in stream_completion(model, messages, db,
                                             temperature=float(config.get("temperature", 0.7))):
            parts.append(chunk if isinstance(chunk, str) else (getattr(chunk, "text", None) or ""))
        return "".join(parts)
    if ntype == "agent":
        if db is None:
            raise WorkflowError("agent node needs a database session")
        from .llm import default_model_id
        from .teams.runner import run_team

        task = render_template(config.get("task", ""), run_input, node_outputs)
        model = config.get("model") or await default_model_id(db)
        result = await run_team(config["team"], task, model, db)
        return {"team": config["team"], "output": result.output if hasattr(result, "output") else str(result)}
    if ntype == "tool":
        from .tools.builtin import code_map_handler, web_search_handler

        args = {}
        for key, value in (config.get("args") or {}).items():
            args[key] = render_template(str(value), run_input, node_outputs) if isinstance(value, str) else value
        if config["tool"] == "web_search":
            return await web_search_handler(args.get("query", ""), int(args.get("max_results", 5) or 5))
        return await code_map_handler(args.get("query", ""), args.get("target", ""))
    if ntype == "code":
        expression = render_template(config.get("expression", ""), run_input, node_outputs)
        variables = {"input": run_input, "nodes": node_outputs}
        for key, value in (config.get("variables") or {}).items():
            rendered = render_template(str(value), run_input, node_outputs) if isinstance(value, str) else value
            try:
                variables[key] = json.loads(rendered) if isinstance(rendered, str) and rendered[:1] in "[{" else rendered
            except (ValueError, TypeError):
                variables[key] = rendered
        return eval_code_expression(expression, variables)
    if ntype == "condition":
        left = render_template(str(config["left"]), run_input, node_outputs)
        right = render_template(str(config["right"]), run_input, node_outputs)
        op = config["op"]
        try:
            left_v: Any = json.loads(left)
        except (ValueError, TypeError):
            left_v = left
        try:
            right_v: Any = json.loads(right)
        except (ValueError, TypeError):
            right_v = right
        if op == "==":
            value = left_v == right_v
        elif op == "!=":
            value = left_v != right_v
        elif op == "contains":
            value = str(right) in str(left)
        else:
            try:
                value = {"<": left_v < right_v, ">": left_v > right_v,
                         "<=": left_v <= right_v, ">=": left_v >= right_v}[op]
            except TypeError as exc:
                raise WorkflowError(f"condition: cannot compare: {exc}") from exc
        return {"branch": "true" if value else "false", "value": value}
    if ntype == "loop":
        raw_items = render_template(config.get("items", ""), run_input, node_outputs)
        try:
            items = json.loads(raw_items)
        except (ValueError, TypeError):
            items = [p.strip() for p in raw_items.split(",") if p.strip()]
        if not isinstance(items, list):
            items = [items]
        out = []
        for i, item in enumerate(items):
            out.append(render_template(config["item_template"], run_input, node_outputs,
                                       extra={"item": item, "item_index": i}))
        return out
    if ntype == "crawl":
        import httpx
        from urllib.parse import urljoin, urlparse

        from .ingest_url import html_to_text, validate_url
        from html.parser import HTMLParser

        class _Links(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.links: list[str] = []
                self.title = ""

            def handle_starttag(self, tag: str, attrs: list) -> None:
                if tag == "a":
                    href = dict(attrs).get("href")
                    if href:
                        self.links.append(href)

        start = render_template(config["url"], run_input, node_outputs).strip()
        max_pages = int(config.get("max_pages", 5))
        max_depth = int(config.get("max_depth", 1))
        host = urlparse(start).netloc
        seen: set[str] = set()
        queue: list[tuple[str, int]] = [(start, 0)]
        pages: list[dict] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0), follow_redirects=False) as client:
            while queue and len(pages) < max_pages:
                url, depth = queue.pop(0)
                if url in seen:
                    continue
                seen.add(url)
                try:
                    validate_url(url)
                    resp = await client.get(url, headers={"User-Agent": "Sangam/1.0 (+local-first)"})
                    if resp.status_code != 200:
                        continue
                    html = resp.content.decode("utf-8", errors="replace")
                except Exception:
                    continue
                parser = _Links()
                parser.feed(html)
                pages.append({"url": url, "text": html_to_text(html)[:2000],
                              "links": [l for l in parser.links if l.startswith("http")][:50]})
                if depth < max_depth:
                    for link in parser.links:
                        absolute = urljoin(url, link)
                        if urlparse(absolute).netloc == host and absolute not in seen:
                            queue.append((absolute, depth + 1))
        return pages
    if ntype == "extract":
        source = config.get("source")
        if source:
            text = str(_lookup(source, {"nodes": node_outputs, "input": run_input}) or "")
        elif node_outputs:
            text = str(list(node_outputs.values())[-1] or "")
        else:
            text = str(run_input.get("text", "") or "")
        if config.get("pattern"):
            matches = [m.groupdict() for m in re.finditer(config["pattern"], text)]
            return matches if config.get("mode", "all") == "all" else (matches[0] if matches else {})
        path = config["json_path"]
        try:
            data = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise WorkflowError(f"extract: source is not JSON: {exc}") from exc
        return _lookup(path, data if isinstance(data, dict) else {"value": data})
    if ntype == "prompt_transform":
        out = {}
        for key in ("system", "user"):
            if config.get(key):
                out[key] = render_template(config[key], run_input, node_outputs)
        if not out and config.get("template"):
            return render_template(config["template"], run_input, node_outputs)
        return out
    raise WorkflowError(f"unknown node type: {ntype}")


async def execute_definition(
    definition: dict,
    run_input: dict,
    *,
    on_node_done=None,
    db: Any = None,
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
        # Batch 3: run_if gates a node on a rendered condition (e.g. the
        # output of a condition node: {{nodes.check.branch}} == 'true' is
        # expressed as run_if "{{nodes.check.branch}}" — truthy runs).
        if node.get("run_if") is not None:
            rendered = render_template(str(node["run_if"]), run_input, node_outputs)
            if not _truthy(rendered):
                node_results[nid] = {"status": "skipped", "output": None,
                                     "error": None, "attempts": 0, "reason": "run_if false"}
                if on_node_done:
                    on_node_done(nid, node_results[nid])
                continue
        retries = node.get("retries", 0)
        timeout = node.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
        attempts = 0
        last_error: Exception | None = None
        output: Any = None
        for attempt in range(retries + 1):
            attempts = attempt + 1
            try:
                output = await asyncio.wait_for(
                    _run_node(node, run_input, node_outputs, db=db), timeout=timeout
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
        outputs, results, error = await execute_definition(definition, run_input, db=db)
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
    from .models import Workflow

    while True:
        await asyncio.sleep(30)
        try:
            from .database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
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
