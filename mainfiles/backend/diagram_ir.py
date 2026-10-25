"""Diagram JSON-Schema IR (archify's pattern, not its product).

One IR — ``architecture`` only — with strict validation, annotated
fixable errors (never silent failures), a canonical diff, and
measured-vs-illustrative evidence pinned to a git revision, generated
FROM the code graph so Sangam diagrams are measured by default.

Deliberately out of scope (say so, don't approximate): archify's
11 renderers, brand system, and locale system. Rendering stays in
Sangam's existing Mermaid frontend; this module owns the IR contract.

IR shape::

    {schema_version: 1, diagram_type: "architecture",
     meta: {title, evidence: "measured"|"illustrative",
            repository: {url, revision},   # revision: 40-hex, optional
            evidence_refs: [{path, line}]},
     components: [{id, type, label, sublabel?}],
     connections: [{id, from, to, label?, variant?}]}
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

SCHEMA_VERSION = 1
DIAGRAM_TYPE = "architecture"
COMPARATOR_VERSION = 1

_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
_RESERVED_PREFIX = "explainer-"

_COMPONENT_KEYS = {"id", "type", "label", "sublabel"}
_CONNECTION_KEYS = {"id", "from", "to", "label", "variant"}
_META_KEYS = {"title", "evidence", "repository", "evidence_refs"}
_TOP_KEYS = {"schema_version", "diagram_type", "meta", "components", "connections"}
_COMPONENT_TYPES = {"service", "module", "package", "database", "queue",
                    "external", "ui", "worker", "gateway", "library"}
_VARIANTS = {"sync", "async", "http", "import", "call"}


def _err(code: str, message: str, path: str, fix: str, severity: str = "error") -> dict:
    return {"code": code, "severity": severity, "message": message,
            "path": path, "supportedFixes": fix}


def validate_diagram(doc: dict) -> list[dict]:
    """Strict validation: schema-shape + semantic checks. Returns a
    list of annotated diagnostics (empty = valid). Nothing is silently
    dropped or repaired — the caller/LLM repairs from ``supportedFixes``."""
    errs: list[dict] = []
    if not isinstance(doc, dict):
        return [_err("not-an-object", "Diagram must be a JSON object", "$",
                     "Wrap the diagram in an object with schema_version, diagram_type, meta, components, connections.")]
    for key in doc:
        if key not in _TOP_KEYS:
            errs.append(_err("additional-property",
                             f"Unknown top-level key: {key!r}", f"/{key}",
                             f"Remove {key!r} or move it under meta."))
    if doc.get("schema_version") != SCHEMA_VERSION:
        errs.append(_err("bad-schema-version",
                         f"schema_version must be {SCHEMA_VERSION}", "/schema_version",
                         f"Set schema_version to {SCHEMA_VERSION}."))
    if doc.get("diagram_type") in _TYPED_DIAGRAM_TYPES:
        return _validate_typed(doc)
    if doc.get("diagram_type") != DIAGRAM_TYPE:
        errs.append(_err("bad-diagram-type",
                         f"diagram_type must be {DIAGRAM_TYPE!r} or one of "
                         f"{sorted(_TYPED_DIAGRAM_TYPES)}", "/diagram_type",
                         f"Set diagram_type to {DIAGRAM_TYPE!r} or a typed IR type."))
    meta = doc.get("meta")
    if not isinstance(meta, dict):
        errs.append(_err("missing-meta", "meta must be an object", "/meta",
                         "Add meta: {title, evidence}."))
        meta = {}
    else:
        for key in meta:
            if key not in _META_KEYS:
                errs.append(_err("additional-property",
                                 f"Unknown meta key: {key!r}", f"/meta/{key}",
                                 f"Remove {key!r} from meta."))
        if not meta.get("title"):
            errs.append(_err("missing-title", "meta.title is required", "/meta/title",
                             "Add a non-empty meta.title."))
        if meta.get("evidence") not in ("measured", "illustrative"):
            errs.append(_err("bad-evidence",
                             "meta.evidence must be 'measured' or 'illustrative'",
                             "/meta/evidence",
                             "Set evidence to 'measured' (verified against code) or 'illustrative'."))
        repo = meta.get("repository")
        if repo is not None:
            if not isinstance(repo, dict) or not _HEX40_RE.match(str(repo.get("revision", ""))):
                errs.append(_err("bad-revision",
                                 "repository.revision must be a 40-hex git revision",
                                 "/meta/repository/revision",
                                 "Set revision to the 40-hex output of `git rev-parse HEAD`, or drop repository."))
    components = doc.get("components")
    if not isinstance(components, list):
        errs.append(_err("bad-components", "components must be a list", "/components",
                         "Set components to a list of {id, type, label}."))
        components = []
    seen_ids: set[str] = set()
    for i, comp in enumerate(components):
        path = f"/components/{i}"
        if not isinstance(comp, dict):
            errs.append(_err("bad-component", "component must be an object", path,
                             "Replace it with {id, type, label}."))
            continue
        for key in comp:
            if key not in _COMPONENT_KEYS:
                errs.append(_err("additional-property",
                                 f"Unknown component key: {key!r}", f"{path}/{key}",
                                 f"Remove {key!r} from the component."))
        for field in ("id", "type", "label"):
            if field not in comp:
                errs.append(_err("missing-field",
                                 f"component is missing {field!r}", f"{path}/{field}",
                                 f"Add {field!r} to the component."))
        cid = comp.get("id")
        if isinstance(cid, str):
            if not _ID_RE.match(cid) or len(cid) > 100:
                errs.append(_err("bad-id",
                                 f"component id {cid!r} must match ^[A-Za-z][A-Za-z0-9_-]*$ and be <=100 chars",
                                 f"{path}/id",
                                 "Rename the id to start with a letter, using only letters, digits, _ and -."))
            if cid.startswith(_RESERVED_PREFIX):
                errs.append(_err("reserved-id",
                                 f"component id {cid!r} uses the reserved prefix { _RESERVED_PREFIX!r}",
                                 f"{path}/id", "Rename the id without the 'explainer-' prefix."))
            if cid in seen_ids:
                errs.append(_err("duplicate-id",
                                 f"duplicate component id: {cid!r}", f"{path}/id",
                                 f"Rename this component to a unique id (e.g. {cid}-2)."))
            seen_ids.add(cid)
        if comp.get("type") not in _COMPONENT_TYPES:
            errs.append(_err("bad-component-type",
                             f"component type must be one of {sorted(_COMPONENT_TYPES)}",
                             f"{path}/type",
                             "Use 'module' for code modules, 'service' for services, 'external' for third parties."))
    connections = doc.get("connections")
    if not isinstance(connections, list):
        errs.append(_err("bad-connections", "connections must be a list", "/connections",
                         "Set connections to a list of {id, from, to}."))
        connections = []
    seen_conn: set[str] = set()
    for i, conn in enumerate(connections):
        path = f"/connections/{i}"
        if not isinstance(conn, dict):
            errs.append(_err("bad-connection", "connection must be an object", path,
                             "Replace it with {id, from, to}."))
            continue
        for key in conn:
            if key not in _CONNECTION_KEYS:
                errs.append(_err("additional-property",
                                 f"Unknown connection key: {key!r}", f"{path}/{key}",
                                 f"Remove {key!r} from the connection."))
        for field in ("id", "from", "to"):
            if field not in conn:
                errs.append(_err("missing-field",
                                 f"connection is missing {field!r}", f"{path}/{field}",
                                 f"Add {field!r} to the connection."))
        if conn.get("id") in seen_conn:
            errs.append(_err("duplicate-id",
                             f"duplicate connection id: {conn.get('id')!r}", f"{path}/id",
                             "Rename this connection to a unique id."))
        seen_conn.add(conn.get("id"))
        for end in ("from", "to"):
            ref = conn.get(end)
            if ref is not None and ref not in seen_ids:
                errs.append(_err("unresolved-reference",
                                 f"connection {conn.get('id')!r} references unknown component {ref!r}",
                                 f"{path}/{end}",
                                 f"Add a component with id {ref!r}, or change {end} to an existing component id."))
        if conn.get("variant") is not None and conn.get("variant") not in _VARIANTS:
            errs.append(_err("bad-variant",
                             f"connection variant must be one of {sorted(_VARIANTS)}",
                             f"{path}/variant",
                             "Use 'import' for module imports, 'call' for function calls, 'http' for HTTP."))
    return errs


def _canonical(doc: dict) -> str:
    """Canonical JSON: sorted keys, sorted components/connections by id."""
    copy = json.loads(json.dumps(doc))
    copy["components"] = sorted(copy.get("components", []), key=lambda c: c.get("id", ""))
    copy["connections"] = sorted(copy.get("connections", []), key=lambda c: c.get("id", ""))
    return json.dumps(copy, sort_keys=True, separators=(",", ":"))


def diagram_diff(old: dict, new: dict) -> dict:
    """Canonical diff (archify's delta pattern, comparator v1):
    added/removed/changed components and connections by id."""
    def _by_id(items: list) -> dict:
        return {c["id"]: c for c in items if isinstance(c, dict) and "id" in c}

    old_c, new_c = _by_id(old.get("components", [])), _by_id(new.get("components", []))
    old_e, new_e = _by_id(old.get("connections", [])), _by_id(new.get("connections", []))
    changed_c = [cid for cid in old_c.keys() & new_c.keys()
                 if json.dumps(old_c[cid], sort_keys=True) != json.dumps(new_c[cid], sort_keys=True)]
    changed_e = [cid for cid in old_e.keys() & new_e.keys()
                 if json.dumps(old_e[cid], sort_keys=True) != json.dumps(new_e[cid], sort_keys=True)]
    return {"comparator_version": COMPARATOR_VERSION,
            "components": {"added": sorted(set(new_c) - set(old_c)),
                           "removed": sorted(set(old_c) - set(new_c)),
                           "changed": sorted(changed_c)},
            "connections": {"added": sorted(set(new_e) - set(old_e)),
                            "removed": sorted(set(old_e) - set(new_e)),
                            "changed": sorted(changed_e)}}


def _git_revision(repo_root: Path) -> str | None:
    try:
        out = subprocess.run(["git", "--no-replace-objects", "rev-parse", "HEAD"],
                             cwd=str(repo_root), capture_output=True, text=True,
                             timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    rev = out.stdout.strip()
    return rev if _HEX40_RE.match(rev) else None


def _git_blob_lines(repo_root: Path, revision: str, path: str) -> int | None:
    """Line count of a path at a pinned revision, via local git blobs
    only (no network — archify's repository-evidence idea)."""
    try:
        out = subprocess.run(
            ["git", "--no-replace-objects", "cat-file", "-p", f"{revision}:{path}"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=10,
            env={"GIT_NO_LAZY_FETCH": "1", "PATH": "/usr/bin:/bin:/usr/local/bin"})
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.count("\n") + (1 if out.stdout else 0)


def verify_evidence(doc: dict, repo_root: Path | str) -> dict:
    """Verify measured evidence: every evidence_ref path/line must
    exist in the pinned revision's blobs. Any failure downgrades the
    diagram to illustrative with reasons — never silently measured."""
    meta = doc.get("meta") or {}
    refs = meta.get("evidence_refs") or []
    revision = (meta.get("repository") or {}).get("revision")
    failures: list[str] = []
    if meta.get("evidence") != "measured":
        return {"evidence": meta.get("evidence"), "verified": True, "failures": []}
    if not revision or not _HEX40_RE.match(str(revision)):
        return {"evidence": "illustrative", "verified": False,
                "failures": ["no valid 40-hex revision pinned"]}
    root = Path(repo_root)
    for ref in refs:
        path, line = ref.get("path"), ref.get("line")
        total = _git_blob_lines(root, revision, path) if path else None
        if total is None:
            failures.append(f"{path}: not found at revision {revision[:8]}")
        elif isinstance(line, int) and not (1 <= line <= total):
            failures.append(f"{path}:{line}: out of range (blob has {total} lines)")
    if failures:
        return {"evidence": "illustrative", "verified": False, "failures": failures}
    return {"evidence": "measured", "verified": True, "failures": []}


def _comp_id(path: str) -> str:
    """Stable component id from a module path (must match ^[A-Za-z]...)."""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_")
    if slug and slug[0].isdigit():
        slug = "m_" + slug
    digest = hashlib.sha256(path.encode()).hexdigest()[:6]
    return f"{slug}_{digest}" if slug else f"mod_{digest}"


def diagram_from_code_graph(graph: dict, repo_root: Path | str | None = None,
                            title: str = "Codebase architecture") -> dict:
    """Generate a measured-by-default diagram FROM the code graph:
    components = top-level modules/packages (files grouped by their
    directory), connections = imports + calls aggregated to module
    level. Evidence is 'measured' only when a git revision pins it."""
    modules: dict[str, dict] = {}  # dir -> component
    file_to_comp: dict[str, str] = {}
    for node in graph.get("file_nodes") or []:
        path = node["path"]
        directory = path.rsplit("/", 1)[0] if "/" in path else "(root)"
        if directory not in modules:
            modules[directory] = {"id": _comp_id(directory), "type": "package",
                                  "label": directory, "sublabel": ""}
        file_to_comp[path] = modules[directory]["id"]
    # Files with no file_nodes entry (shouldn't happen) still get a comp.
    for sym in graph.get("symbols", {}).values():
        if sym["file"] not in file_to_comp:
            directory = sym["file"].rsplit("/", 1)[0] if "/" in sym["file"] else "(root)"
            if directory not in modules:
                modules[directory] = {"id": _comp_id(directory), "type": "package",
                                      "label": directory, "sublabel": ""}
            file_to_comp[sym["file"]] = modules[directory]["id"]

    connections: dict[tuple[str, str, str], dict] = {}
    for e in graph.get("edges") or []:
        if e["type"] == "imports":
            src_file = e["file"]
            dst = e["to"]
            if not dst.startswith("file:"):
                continue  # external module: no component to point at
            src, tgt = file_to_comp.get(src_file), file_to_comp.get(dst[5:])
            variant = "import"
        elif e["type"] == "calls":
            src_sym = graph["symbols"].get(e["from"])
            tgt_sym = graph["symbols"].get(e["to"])
            if not src_sym or not tgt_sym:
                continue
            src, tgt = file_to_comp.get(src_sym["file"]), file_to_comp.get(tgt_sym["file"])
            variant = "call"
        else:
            continue
        if not src or not tgt or src == tgt:
            continue
        key = (src, tgt, variant)
        if key not in connections:
            connections[key] = {"id": f"conn_{len(connections)}", "from": src,
                                "to": tgt, "label": variant, "variant": variant}
    # Connection ids must match the id pattern: conn_0 is fine ([A-Za-z] start).
    revision = _git_revision(Path(repo_root)) if repo_root else None
    evidence = "measured" if revision else "illustrative"
    doc = {
        "schema_version": SCHEMA_VERSION, "diagram_type": DIAGRAM_TYPE,
        "meta": {"title": title, "evidence": evidence,
                 "repository": {"revision": revision} if revision else None,
                 "evidence_refs": []},
        "components": sorted(modules.values(), key=lambda c: c["id"]),
        "connections": sorted(connections.values(), key=lambda c: c["id"]),
    }
    if revision is None:
        doc["meta"].pop("repository")
    return doc


# ================================================================ Batch 11
# Typed IR family (archify salvage: 11 schema types -> Sangam's small
# family). Architecture above is unchanged; these types share the same
# contract shape: schema_version, diagram_type, meta (title + evidence),
# then type-specific collections. Every type enforces the evidence rule
# archify states: a diagram claiming "measured" without a pinned 40-hex
# revision fails validation (fixable: pin it or relabel illustrative).
# ================================================================

_TYPED_DIAGRAM_TYPES = {"erd", "sequence", "workflow", "timeline"}

_ERD_KEYS = {"name", "columns"}
_COLUMN_KEYS = {"name", "type", "keys", "references"}
_SEQ_PART_KEYS = {"id", "label"}
_SEQ_MSG_KEYS = {"id", "from", "to", "label", "kind"}
_WF_STEP_KEYS = {"id", "label", "kind"}
_WF_TRANS_KEYS = {"id", "from", "to", "condition"}
_TL_EVENT_KEYS = {"id", "label", "at"}


def _validate_typed_meta(doc: dict, errs: list[dict]) -> None:
    meta = doc.get("meta")
    if not isinstance(meta, dict):
        errs.append(_err("missing-meta", "meta must be an object", "/meta",
                         "Add meta: {title, evidence}."))
        return
    for key in meta:
        if key not in _META_KEYS:
            errs.append(_err("additional-property", f"Unknown meta key: {key!r}",
                             f"/meta/{key}", f"Remove {key!r} from meta."))
    if not meta.get("title"):
        errs.append(_err("missing-title", "meta.title is required", "/meta/title",
                         "Add a non-empty meta.title."))
    if meta.get("evidence") not in ("measured", "illustrative"):
        errs.append(_err("bad-evidence",
                         "meta.evidence must be 'measured' or 'illustrative'",
                         "/meta/evidence",
                         "Set evidence to 'measured' or 'illustrative'."))
    elif meta.get("evidence") == "measured":
        repo = meta.get("repository") or {}
        if not _HEX40_RE.match(str(repo.get("revision", ""))):
            errs.append(_err("unpinned-measured",
                             "measured evidence requires a pinned 40-hex "
                             "repository.revision",
                             "/meta/repository/revision",
                             "Pin revision to `git rev-parse HEAD`, or set "
                             "evidence to 'illustrative'."))


def _check_ids(items: list, path: str, errs: list[dict]) -> set[str]:
    seen: set[str] = set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            errs.append(_err("bad-item", "item must be an object", f"{path}/{i}",
                             "Replace it with an object with an id."))
            continue
        cid = item.get("id") or item.get("name")
        if isinstance(cid, str):
            if cid in seen:
                errs.append(_err("duplicate-id", f"duplicate id: {cid!r}",
                                 f"{path}/{i}", "Rename it to a unique id."))
            seen.add(cid)
    return seen


def _validate_typed(doc: dict) -> list[dict]:
    errs: list[dict] = []
    if doc.get("schema_version") != SCHEMA_VERSION:
        errs.append(_err("bad-schema-version",
                         f"schema_version must be {SCHEMA_VERSION}", "/schema_version",
                         f"Set schema_version to {SCHEMA_VERSION}."))
    _validate_typed_meta(doc, errs)
    dtype = doc.get("diagram_type")
    if dtype == "erd":
        tables = doc.get("tables")
        if not isinstance(tables, list) or not tables:
            errs.append(_err("bad-tables", "tables must be a non-empty list", "/tables",
                             "Add at least one table with columns."))
            return errs
        table_names: set[str] = set()
        for ti, table in enumerate(tables):
            path = f"/tables/{ti}"
            if not isinstance(table, dict):
                errs.append(_err("bad-table", "table must be an object", path,
                                 "Use {name, columns: [...]}."))
                continue
            name = table.get("name")
            if not name:
                errs.append(_err("missing-field", "table needs a name", f"{path}/name",
                                 "Add the table name."))
                continue
            table_names.add(name)
            columns = table.get("columns")
            if not isinstance(columns, list) or not columns:
                errs.append(_err("bad-columns", f"table {name!r} needs columns",
                                 f"{path}/columns", "Add columns with SQL types."))
                continue
            for ci, col in enumerate(columns):
                cpath = f"{path}/columns/{ci}"
                if not isinstance(col, dict):
                    errs.append(_err("bad-column", "column must be an object", cpath,
                                     "Use {name, type, keys}."))
                    continue
                for key in col:
                    if key not in _COLUMN_KEYS:
                        errs.append(_err("additional-property",
                                         f"Unknown column key: {key!r}", f"{cpath}/{key}",
                                         f"Remove {key!r}."))
                if not col.get("name"):
                    errs.append(_err("missing-field", "column needs a name",
                                     f"{cpath}/name", "Add the column name."))
                if not col.get("type"):
                    errs.append(_err("missing-field",
                                     f"column {col.get('name')!r} needs a SQL type",
                                     f"{cpath}/type",
                                     "Set type, e.g. 'integer' or 'text'."))
                keys = col.get("keys", [])
                if not isinstance(keys, list) or any(k not in ("pk", "fk") for k in keys):
                    errs.append(_err("bad-keys",
                                     f"column keys must be a subset of ['pk', 'fk']",
                                     f"{cpath}/keys", "Use keys: [] or ['pk'] or ['fk'] or ['pk','fk']."))
                refs = col.get("references")
                if refs is not None:
                    if not isinstance(refs, str) or "." not in refs:
                        errs.append(_err("bad-reference",
                                         f"references must be 'table.column'",
                                         f"{cpath}/references",
                                         "Set references to e.g. 'orders.id'."))
                    elif "fk" not in (col.get("keys") or []):
                        errs.append(_err("bad-reference",
                                         "references requires the column to be a fk",
                                         f"{cpath}/references",
                                         "Add 'fk' to keys, or drop references."))
        # Second pass: references must resolve to a real table.column.
        known_cols = set()
        for table in tables:
            if isinstance(table, dict):
                for col in (table.get("columns") or []):
                    if isinstance(col, dict) and col.get("name"):
                        known_cols.add(f"{table.get('name')}.{col['name']}")
        for table in tables:
            if not isinstance(table, dict):
                continue
            for col in (table.get("columns") or []):
                if isinstance(col, dict) and col.get("references") \
                        and col["references"] not in known_cols:
                    errs.append(_err("unresolved-reference",
                                     f"reference {col['references']!r} does not "
                                     "resolve to a table.column",
                                     "/tables", "Point it at an existing table.column."))
    elif dtype == "sequence":
        parts = doc.get("participants")
        msgs = doc.get("messages")
        if not isinstance(parts, list) or not parts:
            errs.append(_err("bad-participants", "participants must be a non-empty list",
                             "/participants", "Add at least two participants."))
            parts = []
        if not isinstance(msgs, list) or not msgs:
            errs.append(_err("bad-messages", "messages must be a non-empty list",
                             "/messages", "Add at least one message."))
            msgs = []
        ids = _check_ids(parts, "/participants", errs)
        for i, msg in enumerate(msgs):
            path = f"/messages/{i}"
            if not isinstance(msg, dict):
                continue
            for end in ("from", "to"):
                if msg.get(end) not in ids:
                    errs.append(_err("unresolved-reference",
                                     f"message {msg.get('id')!r} references unknown "
                                     f"participant {msg.get(end)!r}", f"{path}/{end}",
                                     f"Add a participant with id {msg.get(end)!r}."))
            if msg.get("kind") is not None and msg["kind"] not in ("sync", "async", "return"):
                errs.append(_err("bad-kind", "message kind must be sync/async/return",
                                 f"{path}/kind", "Use 'sync', 'async' or 'return'."))
    elif dtype == "workflow":
        steps = doc.get("steps")
        trans = doc.get("transitions")
        if not isinstance(steps, list) or not steps:
            errs.append(_err("bad-steps", "steps must be a non-empty list", "/steps",
                             "Add at least one step."))
            steps = []
        if not isinstance(trans, list):
            errs.append(_err("bad-transitions", "transitions must be a list",
                             "/transitions", "Set transitions to a list."))
            trans = []
        ids = _check_ids(steps, "/steps", errs)
        for i, tr in enumerate(trans):
            path = f"/transitions/{i}"
            if not isinstance(tr, dict):
                continue
            for end in ("from", "to"):
                if tr.get(end) not in ids:
                    errs.append(_err("unresolved-reference",
                                     f"transition {tr.get('id')!r} references unknown "
                                     f"step {tr.get(end)!r}", f"{path}/{end}",
                                     f"Add a step with id {tr.get(end)!r}."))
    elif dtype == "timeline":
        events = doc.get("events")
        if not isinstance(events, list) or not events:
            errs.append(_err("bad-events", "events must be a non-empty list", "/events",
                             "Add at least one event with an 'at' value."))
            return errs
        _check_ids(events, "/events", errs)
        for i, ev in enumerate(events):
            if isinstance(ev, dict) and ev.get("at") in (None, ""):
                errs.append(_err("missing-field", "event needs an 'at' value",
                                 f"/events/{i}/at",
                                 "Set 'at' to a date or sequence label."))
    return errs


def erd_junctions(doc: dict) -> list[str]:
    """Tables that are junctions (archify rule): every column carries
    pk/fk and at least two columns are fk."""
    out = []
    for table in (doc.get("tables") or []):
        cols = table.get("columns") or []
        if len(cols) >= 2 and all(set(c.get("keys", [])) <= {"pk", "fk"}
                                  and c.get("keys") for c in cols) \
                and sum(1 for c in cols if "fk" in c.get("keys", [])) >= 2:
            out.append(table.get("name"))
    return out


# ---------------------------------------------------------------- layout
# diagram-design salvage: verifiable geometry, not style words. Nodes
# are {id, x, y, w, h, label?} in SVG coordinates; the verifier checks
# the 4px grid, a single accent colour, label/node budgets, and — for
# this computed-geometry path — rectangle overlap. Mermaid text has no
# geometry, so overlap stays a visual check there (unchanged claim).

GRID = 4
MAX_NODES = 60
MAX_LABEL_CHARS = 60


def verify_layout(nodes: list[dict], accent: str | None = None,
                  accents_used: list[str] | None = None) -> list[dict]:
    """Verify a computed layout. Returns diagnostics (empty = pass)."""
    findings: list[dict] = []

    def f(code: str, message: str, fix: str) -> dict:
        return {"code": code, "message": message, "supportedFixes": fix}

    if len(nodes) > MAX_NODES:
        findings.append(f("node-budget", f"{len(nodes)} nodes exceeds the "
                        f"{MAX_NODES}-node budget",
                        "Split the diagram or collapse detail nodes."))
    rects = []
    for node in nodes:
        nid = node.get("id", "?")
        for coord in ("x", "y", "w", "h"):
            value = node.get(coord)
            if not isinstance(value, (int, float)) or value % GRID != 0:
                findings.append(f("off-grid",
                                  f"node {nid!r} {coord}={value!r} is not "
                                  f"divisible by {GRID}",
                                  f"Snap {coord} to a multiple of {GRID}."))
        if len(str(node.get("label", ""))) > MAX_LABEL_CHARS:
            findings.append(f("label-budget",
                              f"node {nid!r} label exceeds {MAX_LABEL_CHARS} chars",
                              "Shorten the label; move detail to a sublabel."))
        rects.append(node)
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rects[i], rects[j]
            if a.get("x", 0) < b.get("x", 0) + b.get("w", 0) \
                    and b.get("x", 0) < a.get("x", 0) + a.get("w", 0) \
                    and a.get("y", 0) < b.get("y", 0) + b.get("h", 0) \
                    and b.get("y", 0) < a.get("y", 0) + a.get("h", 0):
                findings.append(f("overlap",
                                  f"nodes {a.get('id')!r} and {b.get('id')!r} overlap",
                                  "Move one node so their rectangles no longer intersect."))
    used = {c.lower() for c in (accents_used or []) if isinstance(c, str)}
    if accent and len(used - {accent.lower()}) > 0:
        findings.append(f("multi-accent",
                          f"more than one accent colour used: {sorted(used)}",
                          f"Use only the single accent {accent}."))
    return findings


def export_html_svg(doc: dict, nodes: list[dict] | None = None,
                    accent: str = "#3A7BD5") -> str:
    """Standalone HTML+SVG export (diagram-design's one-file delivery):
    a single HTML file with inline SVG. Nodes are placed on the 4px
    grid as given; without nodes it renders the title + a note that
    geometry comes from the layout step (never invented positions)."""
    import html as _html
    title = _html.escape(str((doc.get("meta") or {}).get("title", "Diagram")))
    dtype = _html.escape(str(doc.get("diagram_type", "")))
    evidence = _html.escape(str((doc.get("meta") or {}).get("evidence", "")))
    shapes = []
    for node in (nodes or []):
        x, y, w, h = (node.get("x", 0), node.get("y", 0),
                      node.get("w", 120), node.get("h", 48))
        label = _html.escape(str(node.get("label", node.get("id", ""))))
        shapes.append(f'<g><rect x="{x}" y="{y}" width="{w}" height="{h}" '
                      f'rx="8" fill="none" stroke="{accent}" stroke-width="1"/>'
                      f'<text x="{x + w / 2}" y="{y + h / 2 + 4}" '
                      f'text-anchor="middle" font-family="sans-serif" '
                      f'font-size="13">{label}</text></g>')
    body = "\n".join(shapes) if shapes else \
        "<text x=\"16\" y=\"32\" font-family=\"sans-serif\" font-size=\"13\">" \
        "No placed nodes — supply layout nodes to render geometry.</text>"
    return ("<!DOCTYPE html>\n<html><head><meta charset=\"utf-8\">"
            f"<title>{title}</title></head><body>"
            f"<h1>{title}</h1><p>{dtype} · evidence: {evidence} · "
            f"single accent {accent} · 1px hairlines · no shadows</p>"
            f"<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 800 600\">"
            f"{body}</svg></body></html>")
