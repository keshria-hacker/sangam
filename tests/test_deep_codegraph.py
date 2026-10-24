"""Deep code-graph tests (Wave-2: CODE GRAPH + DIAGRAMS + NOTE GRAPH).

Covers, against real fixtures (no mocks except the rebuild-failure
injection, which is the point of that test):

1. Build-time resolution: same-file unique -> EXTRACTED, cross-file
   unique -> INFERRED, ambiguous -> dropped + counted, never guessed;
   explain/find_path return candidates instead of collapsing.
2. Symbols carry signatures, spans, body_hash; file nodes exist;
   the schema gate rejects a bad confidence.
3. The dead unified-graph branch is fixed: real call edges with real
   provenance materialise in build_knowledge_graph.
4. Fingerprint freshness: edit without rebuild -> stale; a rebuild
   failure serves stale + warning, never an error.
5. JS/TS extraction (incl. a real Sangam frontend file as dogfood).
6. Graft's six tools + affected + diff + JSON/HTML exports.
7. Diagram IR: strict validation with fixable errors, canonical diff,
   measured evidence pinned to a git revision.
8. Note graph: link index (incl. dangling), rename propagation,
   header-tree + extract-section, budget-trimmed expansion retrieval.
9. Routes on a throwaway app: /knowledge/graph/check reports drift
   WITHOUT rebuilding it away.

Pytest only — no Playwright, no servers on shared ports, no api.py edit.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

from backend.code_graph import (  # noqa: E402
    build_graph,
    cached_graph,
    check_freshness,
    ensure_fresh_graph,
    explain,
    find_path,
    invalidate_cache,
    validate_graph,
)
from backend.code_graph_queries import (  # noqa: E402
    affected,
    check_freshness_tool,
    export_graph_html,
    export_graph_json,
    file_api,
    find_all,
    find_code,
    graph_diff,
    repo_map,
    trace_calls,
)
from backend.diagram_ir import (  # noqa: E402
    diagram_diff,
    diagram_from_code_graph,
    validate_diagram,
    verify_evidence,
)
from backend.knowledge_graph import build_knowledge_graph  # noqa: E402
from backend.note_graph import (  # noqa: E402
    backlinks_for,
    build_link_index,
    expand_retrieval,
    extract_section,
    parse_header_tree,
    parse_note_links,
    rename_note_propagate,
)


def _py_tree(tmp_path: Path) -> Path:
    (tmp_path / "a.py").write_text(
        "def foo():\n    bar()\n\ndef bar():\n    pass\n")
    (tmp_path / "b.py").write_text(
        "from a import foo\ndef baz():\n    foo()\n")
    return tmp_path


def _js_tree(tmp_path: Path) -> Path:
    (tmp_path / "app.js").write_text(
        "import { helper } from './util.js';\n"
        "export function main() {\n  helper();\n}\n")
    (tmp_path / "util.js").write_text(
        "export function helper() {\n  return 1;\n}\n")
    return tmp_path


# ------------------------------------------------------------------ 1. resolution
def test_same_file_unique_is_extracted(tmp_path):
    g = build_graph(_py_tree(tmp_path))
    edge = [e for e in g["edges"] if e["type"] == "calls"
            and e["from"] == "a.py#foo"][0]
    assert edge["to"] == "a.py#bar"
    assert edge["confidence"] == "EXTRACTED"


def test_cross_file_unique_is_inferred(tmp_path):
    g = build_graph(_js_tree(tmp_path))
    edge = [e for e in g["edges"] if e["type"] == "calls"
            and e["from"] == "app.js#main"][0]
    assert edge["to"] == "util.js#helper"
    assert edge["confidence"] == "INFERRED"


def test_ambiguous_call_dropped_and_counted_not_guessed(tmp_path):
    root = _py_tree(tmp_path)
    (root / "c.py").write_text("def foo():\n    pass\n")
    g = build_graph(root)
    # baz -> foo is ambiguous (a.py#foo vs c.py#foo): dropped, counted.
    assert g["stats"]["dropped_ambiguous"] == 1
    assert not [e for e in g["edges"] if e["from"] == "b.py#baz"]
    dropped = g["stats"]["dropped"][0]
    assert dropped["reason"] == "ambiguous"
    # ...and explain refuses to collapse instead of picking first.
    res = explain("foo", g)
    assert "candidates" in res
    assert set(res["candidates"]) == {"a.py#foo", "c.py#foo"}


def test_unresolved_call_dropped_and_counted(tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    nosuchfn()\n")
    g = build_graph(tmp_path)
    assert g["stats"]["dropped_unresolved"] == 1
    assert not [e for e in g["edges"] if e["type"] == "calls"]


def test_find_path_ambiguous_endpoint_reports_candidates(tmp_path):
    root = _py_tree(tmp_path)
    (root / "c.py").write_text("def foo():\n    pass\n")
    g = build_graph(root)
    res = find_path("baz", "foo", g)
    assert "candidates" in res


def test_find_path_same_file_chain(tmp_path):
    (tmp_path / "a.py").write_text(
        "def alpha():\n    beta()\ndef beta():\n    gamma()\ndef gamma():\n    pass\n")
    g = build_graph(tmp_path)
    p = find_path("alpha", "gamma", g)
    assert p["hops"] == 2
    assert p["path"][0].endswith("alpha")


# ------------------------------------------------------------------ 2. symbols + gate
def test_symbols_carry_signature_span_body_hash(tmp_path):
    g = build_graph(_py_tree(tmp_path))
    sym = g["symbols"]["a.py#foo"]
    assert sym["signature"].startswith("foo(")
    assert sym["line"] == 1 and sym["end_line"] == 2
    assert len(sym["body_hash"]) == 64
    assert sym["name"] == "foo"  # the field the dead branch needed
    assert sym["calls"] == ["a.py#bar"]  # ...and this one
    assert any(n["id"] == "file:a.py" for n in g["file_nodes"])


def test_schema_gate_rejects_bad_confidence(tmp_path):
    g = build_graph(_py_tree(tmp_path))
    g["edges"][0]["confidence"] = "MAYBE"
    with pytest.raises(ValueError, match="invalid confidence"):
        validate_graph(g)


def test_class_methods_owner_qualified(tmp_path):
    (tmp_path / "a.py").write_text(
        "class A:\n    def get(self):\n        pass\n\n"
        "class B:\n    def get(self):\n        pass\n\n"
        "def use():\n    A().get()\n")
    g = build_graph(tmp_path)
    # A().get() is ambiguous (A.get vs B.get): the `get` call must be
    # dropped, not guessed — while the A() constructor call itself
    # legitimately resolves to class A.
    assert g["stats"]["dropped_ambiguous"] >= 1
    assert not [e for e in g["edges"] if e["from"] == "a.py#use"
                and e["to"].endswith(".get")]
    assert any(e["from"] == "a.py#use" and e["to"] == "a.py#A"
               for e in g["edges"])


# ------------------------------------------------------------------ 3. dead branch fixed
def test_unified_graph_call_edges_materialise(tmp_path):
    g = build_graph(_py_tree(tmp_path))
    kg = build_knowledge_graph(code_graph=g)
    call_edges = [e for e in kg["edges"] if e["type"] == "calls"]
    assert call_edges, "no call edges — the dead branch is back"
    pair = {(e["from"], e["to"]) for e in call_edges}
    assert ("code:a.py#foo", "code:a.py#bar") in pair
    assert call_edges[0]["provenance"] in ("EXTRACTED", "INFERRED")
    labels = {n["id"]: n["label"] for n in kg["nodes"]}
    assert labels.get("code:a.py#foo") == "foo"  # short name, not qualname id


# ------------------------------------------------------------------ 4. freshness
def test_freshness_reports_edit_without_restart(tmp_path):
    root = _py_tree(tmp_path)
    g = build_graph(root)
    assert check_freshness(root, g)["fresh"] is True
    (root / "a.py").write_text(
        "def foo():\n    bar()\n\ndef bar():\n    pass\n\ndef extra():\n    pass\n")
    drift = check_freshness(root, g)
    assert drift["fresh"] is False and drift["changed"] == ["a.py"]


def test_rebuild_failure_serves_stale_with_warning(tmp_path, monkeypatch):
    root = _py_tree(tmp_path)
    invalidate_cache(root)
    graph, warning = ensure_fresh_graph(root)
    assert warning is None
    import backend.code_graph as cg
    monkeypatch.setattr(cg, "build_graph",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    (root / "a.py").write_text("def foo():\n    pass\n")
    stale, warning = ensure_fresh_graph(root)
    assert stale is graph  # same object: stale served
    assert warning and "boom" in warning
    assert "serving stale" in warning
    invalidate_cache(root)


def test_check_freshness_tool_delegates(tmp_path):
    g = build_graph(_py_tree(tmp_path))
    assert check_freshness_tool(tmp_path, g)["fresh"] is True
    assert check_freshness_tool(tmp_path, None)["fresh"] is False


# ------------------------------------------------------------------ 5. JS/TS
def test_js_extraction_defs_calls_imports(tmp_path):
    g = build_graph(_js_tree(tmp_path))
    assert "app.js#main" in g["symbols"]
    assert g["symbols"]["util.js#helper"]["exported"] is True
    assert g["stats"]["languages"]["javascript"] == 2
    assert file_api(g, "app.js")["symbols"][0]["qualname"] == "main"


def test_js_class_methods(tmp_path):
    (tmp_path / "w.js").write_text(
        "export class Widget {\n  render() {\n    this.draw();\n  }\n"
        "  draw() {\n    return 1;\n  }\n}\n")
    g = build_graph(tmp_path)
    assert "w.js#Widget.render" in g["symbols"]
    assert g["symbols"]["w.js#Widget.render"]["kind"] == "method"


def test_dogfood_real_sangam_frontend_file():
    tabs = _ROOT / "mainfiles/frontend/js/features/tabs/tabs.js"
    assert tabs.exists()
    g = build_graph(tabs.parent)
    js_syms = [s for s in g["symbols"].values() if s["file"] == "tabs.js"]
    assert js_syms, "Sangam's own tabs.js produced zero JS symbols"
    assert any(s["kind"] in ("function", "class") for s in js_syms)


# ------------------------------------------------------------------ 6. query tools
def _rich(tmp_path: Path):
    (tmp_path / "a.py").write_text(
        "def alpha():\n    beta()\ndef beta():\n    gamma()\ndef gamma():\n    pass\n")
    return build_graph(tmp_path)


def test_find_code_pagerank_rerank(tmp_path):
    g = _rich(tmp_path)
    res = find_code(g, "beta")
    assert res["results"] and res["results"][0]["name"] == "beta"
    assert all("pagerank_score" in r for r in res["results"])
    assert find_code(g, "zzz-no-match")["results"] == []


def test_file_api_find_all_repo_map(tmp_path):
    g = _rich(tmp_path)
    api = file_api(g, "a.py")
    assert [s["qualname"] for s in api["symbols"]] == ["alpha", "beta", "gamma"]
    assert file_api(g, "nope.py").get("error")
    assert find_all(g, "alp.*")["count"] == 1
    assert find_all(g, "[invalid")["error"]
    assert repo_map(g)["total_symbols"] == 3


def test_trace_calls_in_out_depth_and_contains_excluded(tmp_path):
    g = _rich(tmp_path)
    out = trace_calls(g, "alpha", "out", "all")
    assert [n["symbol"] for n in out["nodes"]] == \
        ["a.py#alpha", "a.py#beta", "a.py#gamma"]
    assert trace_calls(g, "alpha", "out", 1)["count"] == 2
    assert trace_calls(g, "gamma", "in", "all")["count"] == 3
    assert trace_calls(g, "alpha", "sideways")["error"]
    # contains edges exist but are never walked: tracing from a file id fails cleanly
    assert trace_calls(g, "file:a.py")["error"]


def test_affected_blast_radius(tmp_path):
    g = _rich(tmp_path)
    aff = affected(g, "gamma")
    assert aff["defining_file"] == "a.py"
    assert aff["caller_count"] == 2  # beta + alpha (transitive)
    assert "a.py#alpha" in aff["callers_transitive"]


def test_graph_diff_on_body_hash(tmp_path):
    g1 = _rich(tmp_path)
    (tmp_path / "a.py").write_text(
        "def alpha():\n    beta()\ndef beta():\n    gamma()\ndef gamma():\n    return 42\n")
    g2 = build_graph(tmp_path)
    diff = graph_diff(g1, g2)
    assert diff["changed"] == ["a.py#gamma"]
    assert diff["added"] == [] and diff["removed"] == []


def test_exports_json_directed_and_html_standalone(tmp_path):
    g = _rich(tmp_path)
    j = export_graph_json(g)
    assert j["directed"] is True
    assert any(e["from"] == "a.py#alpha" and e["to"] == "a.py#beta"
               for e in j["edges"])
    h = export_graph_html(g)
    assert h.startswith("<!DOCTYPE html>")
    assert "http://" not in h and "https://" not in h  # nothing external
    assert "alpha" in h


# ------------------------------------------------------------------ 7. diagram IR
def _diagram(tmp_path: Path):
    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "a.py").write_text("from pkg.b import helper\ndef main():\n    helper()\n")
    (tmp_path / "pkg" / "b.py").write_text("def helper():\n    pass\n")
    g = build_graph(tmp_path)
    return diagram_from_code_graph(g, repo_root=tmp_path)


def test_diagram_from_graph_valid_and_measured_shape(tmp_path):
    doc = _diagram(tmp_path)
    assert validate_diagram(doc) == []
    assert doc["meta"]["evidence"] == "illustrative"  # no git repo here
    assert doc["components"] and doc["connections"]
    assert all(c["variant"] in ("import", "call") for c in doc["connections"])


def test_diagram_validation_errors_are_annotated_and_fixable(tmp_path):
    doc = _diagram(tmp_path)
    bad = dict(doc)
    bad["components"] = doc["components"] + [
        {"id": doc["components"][0]["id"], "type": "module", "label": "dup",
         "surprise": 1}]
    errs = validate_diagram(bad)
    codes = {e["code"] for e in errs}
    assert "duplicate-id" in codes and "additional-property" in codes
    assert all(e.get("supportedFixes") and e.get("path") for e in errs)
    unresolved = {"schema_version": 1, "diagram_type": "architecture",
                  "meta": {"title": "t", "evidence": "illustrative"},
                  "components": [{"id": "A", "type": "module", "label": "a"}],
                  "connections": [{"id": "c1", "from": "A", "to": "NOPE"}]}
    assert any(e["code"] == "unresolved-reference"
               for e in validate_diagram(unresolved))


def test_diagram_diff_canonical(tmp_path):
    doc = _diagram(tmp_path)
    changed = dict(doc, components=[])
    diff = diagram_diff(doc, changed)
    assert diff["comparator_version"] == 1
    assert diff["components"]["removed"] == [c["id"] for c in doc["components"]]


def test_diagram_measured_evidence_pinned_to_git_revision(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("def f():\n    pass\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "x"], cwd=tmp_path, check=True)
    g = build_graph(tmp_path)
    doc = diagram_from_code_graph(g, repo_root=tmp_path)
    assert doc["meta"]["evidence"] == "measured"
    assert len(doc["meta"]["repository"]["revision"]) == 40
    doc["meta"]["evidence_refs"] = [{"path": "a.py", "line": 1}]
    assert verify_evidence(doc, tmp_path)["verified"] is True
    doc["meta"]["evidence_refs"] = [{"path": "a.py", "line": 99}]
    bad = verify_evidence(doc, tmp_path)
    assert bad["evidence"] == "illustrative" and bad["failures"]


# ------------------------------------------------------------------ 8. note graph
_NOTES = [
    {"id": "n1", "notebook_id": "nb", "title": "Alpha",
     "content": "# Intro\ntext\n## Details\nsee [[Beta]] and [[Beta|piped]] and [t](Gamma.md)\n"},
    {"id": "n2", "notebook_id": "nb", "title": "Beta",
     "content": "links [[Alpha]] and [[Missing]]\n"},
    {"id": "n3", "notebook_id": "nb", "title": "Gamma", "content": "plain\n"},
]


def test_note_link_index_resolves_and_flags_dangling():
    rows = build_link_index(_NOTES)
    by_src = {}
    for r in rows:
        by_src.setdefault(r["source_note_id"], []).append(r)
    assert {r["target_title"] for r in by_src["n1"]} == {"Beta", "Gamma"}
    dangling = [r for r in rows if r["target_title"] == "Missing"]
    assert len(dangling) == 1 and dangling[0]["target_note_id"] is None
    assert backlinks_for(rows, "n2") == ["n1"]  # index lookup, not grep


def test_note_link_parsing_kinds():
    links = parse_note_links("[[A]] [[B|show]] [t](C.md) [x](https://e.com)")
    assert [(l["target"], l["kind"]) for l in links] == [
        ("A", "wikilink"), ("B", "piped"), ("C", "markdown")]


def test_rename_propagation_rewrites_linkers_no_orphans():
    res = rename_note_propagate(_NOTES, "n2", "Beta2")
    assert res["renamed"]["old_title"] == "Beta"
    assert len(res["updates"]) == 1
    upd = res["updates"][0]
    assert "[[Old Title]]" not in upd["new_content"]
    assert "[[Beta2]]" in upd["new_content"]
    assert "[[Beta2|piped]]" in upd["new_content"]  # piped display kept
    assert "[t](Gamma.md)" in upd["new_content"]  # unrelated link untouched
    assert "[[Beta]]" not in upd["new_content"]


def test_header_tree_and_extract_section():
    content = _NOTES[0]["content"]
    tree = parse_header_tree(content)
    assert tree[0]["title"] == "Intro"
    assert tree[0]["children"][0]["title"] == "Details"
    ex = extract_section(content, "Details", "Details Note")
    assert "see [[Beta]]" in ex["new_note_content"]
    assert ex["updated_source_content"].endswith("[[Details Note]]")
    assert "[[Beta]]" not in ex["updated_source_content"]
    assert extract_section(content, "Nope", "X")["error"]
    assert extract_section("# A\nx\n# A\ny\n", "A", "X")["error"]  # ambiguous


def test_graph_expansion_retrieval_budget_trims_periphery():
    by_id = {n["id"]: n for n in _NOTES}
    rows = build_link_index(_NOTES)
    full = expand_retrieval(by_id, rows, ["n2"], depth=2, max_tokens=4000)
    assert [d["note_id"] for d in full["documents"]] == ["n2", "n1", "n3"]
    tiny = expand_retrieval(by_id, rows, ["n2"], depth=2, max_tokens=5)
    assert tiny["trimmed"] is True
    assert [d["note_id"] for d in tiny["documents"]] == ["n2"]  # seed kept


# ------------------------------------------------------------------ 9. routes (throwaway app)
def test_graph_check_route_reports_drift_without_rebuilding(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api_routes import code_graph_routes  # noqa: F401  (registers routes)
    from backend.api_routes.common import router
    from backend.auth import get_current_user
    import backend.tools.builtin as bi

    _py_tree(tmp_path)
    orig = bi._get_workspace_root
    bi._get_workspace_root = lambda: tmp_path
    invalidate_cache()
    try:
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="u1")
        client = TestClient(app, raise_server_exceptions=False)
        first = client.get("/knowledge/graph/check")
        assert first.status_code == 200 and first.json()["fresh"] is True
        (tmp_path / "a.py").write_text(
            "def foo():\n    bar()\n\ndef bar():\n    pass\n\ndef extra():\n    pass\n")
        drift = client.get("/knowledge/graph/check").json()
        assert drift["fresh"] is False and drift["changed"] == ["a.py"]
        exp = client.get("/code-graph/export?format=json")
        assert exp.status_code == 200
        assert exp.json()["stats"]["symbols"] >= 3
        assert client.get("/knowledge/graph/check").json()["fresh"] is True
    finally:
        bi._get_workspace_root = orig
        invalidate_cache()
