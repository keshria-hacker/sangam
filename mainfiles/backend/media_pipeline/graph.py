"""Sangam-native node graph (ComfyUI salvage, no ComfyUI).

What was actually read in ComfyUI's source (``comfy_execution/graph.py``,
``comfy/comfy_types/node_typing.py``): nodes declare ``INPUT_TYPES``
(required/optional/hidden) and ``RETURN_TYPES``/``RETURN_NAMES``; links
carry typed values between output and input sockets; execution dissolves
the graph in topological order (``ExecutionList``) and cycle detection
leaves only the cycle behind (``DependencyCycleError``). Custom-node
*code execution* is deliberately NOT ported: Sangam's graph has a fixed
node registry, typed sockets, validation, and topological execution —
and it executes only through handler callables the caller supplies
(Sangam's existing engines). A node type with no handler fails loudly
instead of running anything.

Graph doc::

    {"nodes": [{"id": "p1", "type": "prompt", "inputs": {"text": "a cat"}}],
     "links": [{"from_node": "p1", "from_socket": "text",
                "to_node": "g1", "to_socket": "prompt"}]}
"""
from __future__ import annotations

# node type -> {inputs: {name: (socket_type, required)}, outputs: {name: socket_type}}
NODE_DEFS: dict[str, dict] = {
    "prompt": {"inputs": {"text": ("text", True)}, "outputs": {"text": "text"}},
    "style_apply": {"inputs": {"text": ("text", True), "style": ("text", False)},
                    "outputs": {"text": "text"}},
    "image_generate": {"inputs": {"prompt": ("text", True)},
                       "outputs": {"image": "image"}},
    "text_chunk": {"inputs": {"text": ("text", True)}, "outputs": {"chunks": "text"}},
    "tts": {"inputs": {"text": ("text", True)}, "outputs": {"audio": "audio"}},
    "diagram_validate": {"inputs": {"diagram": ("diagram", True)},
                         "outputs": {"diagram": "diagram"}},
    "subtitle_export": {"inputs": {"segments": ("segments", True)},
                        "outputs": {"text": "text"}},
    "design_critique": {"inputs": {"html": ("text", True)},
                        "outputs": {"text": "text"}},
    "overlay": {"inputs": {"annotations": ("annotations", True)},
                "outputs": {"image": "image"}},
}


def _err(code: str, message: str, fix: str) -> dict:
    return {"code": code, "message": message, "supportedFixes": fix}


def validate_graph(doc: object) -> list[dict]:
    """Validate a graph doc; empty list = valid. Checks node types,
    socket names/types, required inputs (literal or linked), duplicate
    links onto one input socket, and cycles."""
    errs: list[dict] = []
    if not isinstance(doc, dict):
        return [_err("not-an-object", "Graph must be an object",
                     "Pass {nodes: [...], links: [...]}.")]
    nodes = doc.get("nodes")
    links = doc.get("links", [])
    if not isinstance(nodes, list) or not nodes:
        return [_err("no-nodes", "nodes must be a non-empty list",
                     "Add at least one node.")]
    if not isinstance(links, list):
        return [_err("bad-links", "links must be a list",
                     "Set links to a list (possibly empty).")]
    by_id: dict[str, dict] = {}
    for node in nodes:
        if not isinstance(node, dict) or not node.get("id"):
            errs.append(_err("bad-node", "Every node needs an id",
                             "Give each node a unique id."))
            continue
        if node["id"] in by_id:
            errs.append(_err("duplicate-id", f"Duplicate node id: {node['id']!r}",
                             "Rename one of the nodes."))
        by_id[node["id"]] = node
        if node.get("type") not in NODE_DEFS:
            errs.append(_err("unknown-node",
                             f"Unknown node type: {node.get('type')!r}",
                             f"Use one of {sorted(NODE_DEFS)}. No custom-node "
                             "code is loaded — unknown types are rejected."))
    # Link checks.
    linked_inputs: set[tuple[str, str]] = set()
    edges: dict[str, set[str]] = {nid: set() for nid in by_id}
    for link in links:
        if not isinstance(link, dict):
            errs.append(_err("bad-link", "Every link must be an object",
                             "Use {from_node, from_socket, to_node, to_socket}."))
            continue
        fn, fs = link.get("from_node"), link.get("from_socket")
        tn, ts = link.get("to_node"), link.get("to_socket")
        src = by_id.get(fn) if isinstance(fn, str) else None
        dst = by_id.get(tn) if isinstance(tn, str) else None
        if src is None or dst is None:
            errs.append(_err("unknown-link-end",
                             f"Link references an unknown node: {link}",
                             "Point links at node ids that exist."))
            continue
        src_def = NODE_DEFS.get(src.get("type"), {})
        dst_def = NODE_DEFS.get(dst.get("type"), {})
        src_type = src_def.get("outputs", {}).get(fs)
        dst_spec = dst_def.get("inputs", {}).get(ts)
        if src_type is None:
            errs.append(_err("unknown-socket",
                             f"Node {fn!r} has no output socket {fs!r}",
                             f"Use one of {sorted(src_def.get('outputs', {}))}."))
        if dst_spec is None:
            errs.append(_err("unknown-socket",
                             f"Node {tn!r} has no input socket {ts!r}",
                             f"Use one of {sorted(dst_def.get('inputs', {}))}."))
        elif src_type is not None and src_type != dst_spec[0]:
            errs.append(_err("type-mismatch",
                             f"Socket type mismatch: {fs!r} is {src_type}, "
                             f"{ts!r} needs {dst_spec[0]}",
                             "Link sockets of the same type, or insert a "
                             "converting node."))
        if (tn, ts) in linked_inputs:
            errs.append(_err("double-link",
                             f"Input {tn!r}.{ts!r} already has a link",
                             "Each input socket takes at most one link."))
        linked_inputs.add((tn, ts))
        edges[fn].add(tn)
    # Required inputs: literal or linked.
    for node in nodes:
        if not isinstance(node, dict):
            continue
        spec = NODE_DEFS.get(node.get("type"), {}).get("inputs", {})
        literals = node.get("inputs") or {}
        for name, (_type, required) in spec.items():
            if required and name not in literals and (node["id"], name) not in linked_inputs:
                errs.append(_err("missing-input",
                                 f"Node {node['id']!r} is missing required input {name!r}",
                                 f"Set inputs.{name} or link a node output to it."))
    # Cycle detection (Kahn; leftovers are the cycle).
    indegree = {nid: 0 for nid in by_id}
    for src, dsts in edges.items():
        for dst in dsts:
            indegree[dst] += 1
    queue = sorted(n for n, d in indegree.items() if d == 0)
    seen = 0
    while queue:
        cur = queue.pop(0)
        seen += 1
        for dst in sorted(edges[cur]):
            indegree[dst] -= 1
            if indegree[dst] == 0:
                queue.append(dst)
    if seen != len(by_id):
        cyclic = sorted(n for n, d in indegree.items() if d > 0)
        errs.append(_err("cycle", f"Graph has a cycle through: {cyclic}",
                         "Remove a link so execution order is acyclic."))
    return errs


def execution_order(doc: dict) -> list[str]:
    """Topological node order. Raises ValueError on an invalid graph."""
    errs = validate_graph(doc)
    if errs:
        raise ValueError(f"invalid graph: {errs[0]['message']}")
    edges: dict[str, set[str]] = {n["id"]: set() for n in doc["nodes"]}
    indegree = {n["id"]: 0 for n in doc["nodes"]}
    for link in doc.get("links", []):
        edges[link["from_node"]].add(link["to_node"])
        indegree[link["to_node"]] += 1
    queue = sorted(n for n, d in indegree.items() if d == 0)
    order: list[str] = []
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for dst in sorted(edges[cur]):
            indegree[dst] -= 1
            if indegree[dst] == 0:
                queue.append(dst)
    return order


def execute_graph(doc: dict, handlers: dict) -> dict:
    """Execute a validated graph through supplied handlers.

    ``handlers`` maps node type -> callable(inputs dict) -> outputs
    dict. No handler for a type raises RuntimeError (the caller turns
    it into 503: engine unavailable) — the graph never invents an
    output and never executes node-supplied code.
    """
    order = execution_order(doc)
    by_id = {n["id"]: n for n in doc["nodes"]}
    link_in: dict[tuple[str, str], tuple[str, str]] = {}
    for link in doc.get("links", []):
        link_in[(link["to_node"], link["to_socket"])] = (
            link["from_node"], link["from_socket"])
    results: dict[str, dict] = {}
    for nid in order:
        node = by_id[nid]
        inputs = dict(node.get("inputs") or {})
        for (tn, ts), (fn, fs) in link_in.items():
            if tn == nid:
                inputs[ts] = results[fn][fs]
        handler = handlers.get(node["type"])
        if handler is None:
            raise RuntimeError(
                f"no handler for node type {node['type']!r}: "
                "engine unavailable, graph not executed")
        outputs = handler(inputs)
        if not isinstance(outputs, dict):
            raise RuntimeError(f"handler for {node['type']!r} returned non-dict")
        results[nid] = outputs
    return {"order": order, "results": results}
