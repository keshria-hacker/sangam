"""A5 tests: spec pipeline v2, code intelligence extensions, QA package,
deploy interface. TestClient-based, port-free, no Playwright.

Sample-feature proof (spec -> tasks -> implement -> converge) runs
REAL pytest on a throwaway sample repo in tmp_path: the RED output is
a genuine failing run and the GREEN output a genuine passing run,
and both are submitted as TDD evidence to the API (the API validates
RED/GREEN in code — a pasted green-only pair is rejected, covered by
test_tdd_rejects_green_only_as_red).
"""
from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import backend.api_routes.spec_qa_routes  # noqa: E402,F401 — registers tables/routes
from backend.code_graph import build_graph, invalidate_cache  # noqa: E402
from backend.code_graph_queries import (  # noqa: E402
    architecture_overview,
    change_impact,
    circular_imports,
    search_code_v2,
)
from backend.config import settings  # noqa: E402
from backend.database import Base, get_engine, reset_engine_for_testing  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.qa.greencontract import (  # noqa: E402
    graduated_satisfied,
    next_level,
)
from backend.qa.pytest_gen import generate_pytest_file  # noqa: E402
from backend.qa.recorder import Recorder, save_cassette  # noqa: E402
from backend.qa.replay import replay_cases  # noqa: E402
from backend.qa.report import build_report  # noqa: E402
from backend.spec import ArtifactStore  # noqa: E402
from backend.spec.checklist import render_checklist, validate_checklist  # noqa: E402
from backend.spec.tdd import validate_tdd_evidence  # noqa: E402
from backend.spec_chain import (  # noqa: E402
    analyze_coverage,
    render_plan,
    render_spec,
    render_tasks,
)
from fastapi.testclient import TestClient  # noqa: E402


def _api_client(tmp_path, monkeypatch):
    os.environ["CHROMA_DB_PATH"] = str(tmp_path / "chroma")
    import backend.rag as rag_mod
    importlib.reload(rag_mod)
    rag_mod._client = None
    rag_mod._collection = None
    from backend import memory as memory_mod
    memory_mod.reset_memory_for_testing()
    monkeypatch.setattr(settings, "DATABASE_URL",
                        f"sqlite+aiosqlite:///{tmp_path}/a5.db")
    reset_engine_for_testing()

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


@pytest.fixture
def client(tmp_path, monkeypatch):
    return _api_client(tmp_path, monkeypatch)


def _auth(client):
    creds = {"username": "a5_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post(
        "/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


def _advance(client, h, pid, stage, artifact="", **kw):
    body = {"stage": stage, "artifact": artifact}
    body.update(kw)
    return client.post(f"/api/spec-v2/{pid}/advance", json=body, headers=h)


SAMPLE_SPEC = render_spec(
    "Greeting + addition",
    "A tiny sample feature: greet a name and add two numbers.",
    [{"title": "Greet", "priority": "P0",
      "given": "a name", "when": "greet is called",
      "then": "it returns 'Hello, <name>'"},
     {"title": "Add", "priority": "P1",
      "given": "two numbers", "when": "add is called",
      "then": "[NEEDS CLARIFICATION: add result] is returned"}],
    ["greet returns 'Hello, <name>' for a given name",
     "add returns [NEEDS CLARIFICATION: add result] for two numbers"])

SAMPLE_PLAN = render_plan(
    "Research resolves add result: the numeric sum (clarified).",
    "greet.py: greet(name); calc.py: add(a, b)",
    "greet(name) -> str; add(a, b) -> int",
    "1. pytest test_greet.py 2. pytest test_calc.py")

SAMPLE_CHECKLIST = render_checklist([
    {"title": "greet returns Hello, World", "verifies": ["FR-001"],
     "method": "pytest test_greet.py -q"},
    {"title": "add returns the sum", "verifies": ["FR-002"],
     "method": "pytest test_calc.py -q"},
])

SAMPLE_TASKS = render_tasks([
    {"title": "Implement greet", "files": ["sample/greet.py"],
     "parallel": False, "covers": ["FR-001"]},
    {"title": "Implement add", "files": ["sample/calc.py"],
     "parallel": False, "covers": ["FR-002"]},
])


# ------------------------------------------------------------------ TDD unit
def test_tdd_rejects_green_only_as_red():
    with pytest.raises(ValueError):
        validate_tdd_evidence("pytest -q", "1 passed in 0.01s",
                              "1 passed in 0.01s")
    with pytest.raises(ValueError):
        validate_tdd_evidence("pytest -q", "FAILED x - AssertionError",
                              "1 failed, 1 passed")
    out = validate_tdd_evidence(
        "pytest -q", "FAILED test_x.py::test_a - AssertionError",
        "1 passed in 0.02s")
    assert out["red_ok"] and out["green_ok"]


def test_checklist_must_cover_every_fr():
    validate_checklist(SAMPLE_CHECKLIST, SAMPLE_SPEC)
    bad = render_checklist([
        {"title": "only greet", "verifies": ["FR-001"],
         "method": "pytest test_greet.py -q"}])
    with pytest.raises(ValueError):
        validate_checklist(bad, SAMPLE_SPEC)


def test_greencontract_graduated():
    assert graduated_satisfied("targeted", [{"level": "targeted", "passed": True}])
    assert not graduated_satisfied(
        "package", [{"level": "package", "passed": True}])
    assert graduated_satisfied(
        "package", [{"level": "targeted", "passed": True},
                    {"level": "package", "passed": True}])
    assert next_level([{"level": "targeted", "passed": True}]) == "package"



# ------------------------------------------------------- code graph languages
def _go_tree(tmp_path: Path) -> Path:
    (tmp_path / "main.go").write_text(
        "package main\n\nfunc greet() {}\nfunc main() { greet() }\n")
    return tmp_path


def _rust_tree(tmp_path: Path) -> Path:
    (tmp_path / "lib.rs").write_text(
        "pub fn helper() -> i32 { 1 }\nfn main() { helper(); }\n")
    return tmp_path


def _java_tree(tmp_path: Path) -> Path:
    (tmp_path / "Greeter.java").write_text(
        "public class Greeter {\n"
        "  public String greet() { return helper(); }\n"
        "  private String helper() { return \"hi\"; }\n}\n")
    return tmp_path


def test_go_symbols_and_call(tmp_path):
    g = build_graph(_go_tree(tmp_path))
    assert g["stats"]["languages"] == {"go": 1}
    edge = [e for e in g["edges"] if e["type"] == "calls"][0]
    assert edge["from"] == "main.go#main" and edge["to"] == "main.go#greet"


def test_rust_symbols_and_call(tmp_path):
    g = build_graph(_rust_tree(tmp_path))
    assert g["stats"]["languages"] == {"rust": 1}
    assert "lib.rs#helper" in g["symbols"]
    edge = [e for e in g["edges"] if e["type"] == "calls"][0]
    assert edge["to"] == "lib.rs#helper"


def test_java_symbols_and_call(tmp_path):
    g = build_graph(_java_tree(tmp_path))
    assert g["stats"]["languages"] == {"java": 1}
    edge = [e for e in g["edges"] if e["type"] == "calls"][0]
    assert edge["from"] == "Greeter.java#Greeter.greet"
    assert edge["to"] == "Greeter.java#Greeter.helper"


def test_python_and_js_still_extracted(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    bar()\n\ndef bar():\n    pass\n")
    (tmp_path / "app.js").write_text(
        "export function main() { helper(); }\n"
        "export function helper() { return 1; }\n")
    g = build_graph(tmp_path)
    assert g["stats"]["languages"] == {"python": 1, "javascript": 1}
    assert "a.py#foo" in g["symbols"] and "app.js#main" in g["symbols"]


def test_circular_imports_architecture_impact_search(tmp_path):
    (tmp_path / "a.py").write_text("from b import helper\ndef foo():\n    helper()\n")
    (tmp_path / "b.py").write_text("from a import foo\ndef helper():\n    foo()\n")
    (tmp_path / "c.py").write_text("def lone():\n    pass\n")
    g = build_graph(tmp_path)
    cycles = circular_imports(g)
    assert cycles["count"] == 1
    assert cycles["cycles"] == [["file:a.py", "file:b.py"]]
    ov = architecture_overview(g)
    assert ov["symbols"] == 3 and ov["entry_points"] == ["c.py#lone"]
    imp = change_impact(g, "file:b.py")
    assert imp["callers_transitive"] == ["a.py#foo"]
    assert imp["importers_of_file"] == ["file:a.py"]
    s2 = search_code_v2(g, "helper", root=tmp_path)
    assert s2["grep_enabled"] is True
    assert s2["merged"][0]["source"] == "graph+grep"


# ---------------------------------------------------------------- QA library
def test_qa_record_replay_report_and_noise():
    class FakeClient:
        def __init__(self):
            self.calls = []

        def request(self, method, path, **kwargs):
            self.calls.append((method, path))
            body = {"version": "1", "id": "550e8400-e29b-41d4-a716-446655440000",
                    "ts": "2026-10-25T00:00:00Z"}
            return _FakeResp(200, body)

    class _FakeResp:
        def __init__(self, status_code, body):
            self.status_code = status_code
            self._body = body

        def json(self):
            return self._body

    rec = Recorder()
    case, _ = rec.record_response(FakeClient(), "GET", "/api/features")
    # Recorded body still carries the raw values; replay normalizes them.
    assert case["method"] == "GET" and case["status"] == 200
    results = replay_cases(FakeClient(), rec.cases)
    assert results[0]["passed"] is True
    skipped = dict(rec.cases[0], skip=True)
    results2 = replay_cases(FakeClient(), [skipped])
    assert results2[0]["status"] == "skipped"
    report = build_report(results + results2, untested=["GET /api/unknown"])
    assert (report["passed"], report["failed"], report["skipped"],
            report["untested"]) == (1, 0, 1, 1)
    assert report["all_passed"] is False  # untested work must not hide


def test_qa_generated_pytest_file_parses_and_counts(tmp_path):
    cases = [{"method": "GET", "path": "/api/features", "request_body": None,
              "status": 200, "response_body": {}, "noise_fields": [],
              "skip": False}]
    cassette = save_cassette(cases, tmp_path / "cass.json")
    out = generate_pytest_file(cassette, tmp_path / "test_gen.py")
    text = out.read_text()
    assert "test_replayed_case" in text
    assert "SANGAM_REPO_ROOT" in text


# ------------------------------------------------------- spec v2 via API
def _run_pytest(sample_dir: Path, test_file: str) -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", test_file, "-q"],
        cwd=str(sample_dir), capture_output=True, text=True, timeout=120)
    return (proc.stdout or "") + (proc.stderr or "")


def test_spec_v2_out_of_order_rejected(client):
    h = _auth(client)
    r = client.post("/api/spec-v2", json={"title": "T", "goal": "g"}, headers=h)
    assert r.status_code == 201
    pid = r.json()["id"]
    r = _advance(client, h, pid, "spec", SAMPLE_SPEC)
    assert r.status_code == 422, r.text


def test_spec_v2_sample_end_to_end(client, tmp_path, monkeypatch):
    h = _auth(client)
    r = client.post("/api/spec-v2", json={"title": "Greeting sample",
                                          "goal": "greet + add"}, headers=h)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]

    assert _advance(client, h, pid, "constitution",
                    "# Constitution\n- Principle: tests before code").status_code == 200
    assert _advance(client, h, pid, "spec", SAMPLE_SPEC).status_code == 200
    r = _advance(client, h, pid, "clarify", "",
                 clarifications=[{"question": "[NEEDS CLARIFICATION: add result]",
                                  "answer": "the numeric sum"}])
    assert r.status_code == 200, r.text
    assert _advance(client, h, pid, "plan", SAMPLE_PLAN).status_code == 200
    # Checklist that drops FR-002 must be rejected before the good one.
    bad_checklist = render_checklist([
        {"title": "only greet", "verifies": ["FR-001"],
         "method": "pytest test_greet.py -q"}])
    assert _advance(client, h, pid, "checklist", bad_checklist).status_code == 422
    assert _advance(client, h, pid, "checklist", SAMPLE_CHECKLIST).status_code == 200
    assert _advance(client, h, pid, "tasks", SAMPLE_TASKS).status_code == 200
    analysis = analyze_coverage(SAMPLE_SPEC, SAMPLE_TASKS)
    assert "UNCOVERED" not in analysis
    assert _advance(client, h, pid, "analyze", analysis).status_code == 200
    # Implement before TDD evidence must halt.
    assert _advance(client, h, pid, "implement", "done").status_code == 422

    # ---- REAL sample repo: RED then GREEN, per task ----
    sample = tmp_path / "sample"
    sample.mkdir()
    (sample / "test_greet.py").write_text(
        "from greet import greet\n"
        "def test_greet():\n    assert greet('World') == 'Hello, World'\n")
    (sample / "test_calc.py").write_text(
        "from calc import add\n"
        "def test_add():\n    assert add(2, 3) == 5\n")
    (sample / "greet.py").write_text("def greet(name):\n    return 'bye'\n")
    (sample / "calc.py").write_text("def add(a, b):\n    return 0\n")
    red_greet = _run_pytest(sample, "test_greet.py")
    red_calc = _run_pytest(sample, "test_calc.py")
    assert "FAILED" in red_greet and "AssertionError" in red_greet
    assert "FAILED" in red_calc
    (sample / "greet.py").write_text(
        "def greet(name):\n    return f'Hello, {name}'\n")
    (sample / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    green_greet = _run_pytest(sample, "test_greet.py")
    green_calc = _run_pytest(sample, "test_calc.py")
    assert "1 passed" in green_greet and "1 passed" in green_calc

    diff_greet = ("--- a/sample/greet.py\n+++ b/sample/greet.py\n"
                  "+def greet(name):\n+    return f'Hello, {name}'\n")
    diff_calc = ("--- a/sample/calc.py\n+++ b/sample/calc.py\n"
                 "+def add(a, b):\n+    return a + b\n")
    for task_id, diff, cmd, red, green in [
            ("T1", diff_greet, "pytest test_greet.py -q", red_greet, green_greet),
            ("T2", diff_calc, "pytest test_calc.py -q", red_calc, green_calc)]:
        r = client.post(f"/api/spec-v2/{pid}/tasks/{task_id}/evidence",
                        json={"diff": diff, "test_command": cmd,
                              "red_output": red, "green_output": green},
                        headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["tdd_ok"] is True
    # Fake evidence (green as red) must be rejected by the API too.
    r = client.post(f"/api/spec-v2/{pid}/tasks/T1/evidence",
                    json={"diff": diff_greet, "test_command": "pytest -q",
                          "red_output": green_greet, "green_output": green_greet},
                    headers=h)
    assert r.status_code == 422, r.text

    assert _advance(client, h, pid, "implement",
                    "greet + add implemented with RED/GREEN evidence").status_code == 200
    # GreenContract: package before targeted must be rejected.
    r = client.post(f"/api/spec-v2/{pid}/verify-record",
                    json={"level": "package", "test_command": "pytest -q",
                          "output": green_greet, "passed": True}, headers=h)
    assert r.status_code == 422, r.text
    r = client.post(f"/api/spec-v2/{pid}/verify-record",
                    json={"level": "targeted",
                          "test_command": "pytest test_greet.py test_calc.py -q",
                          "output": green_greet + "\n" + green_calc,
                          "passed": True}, headers=h)
    assert r.status_code == 200, r.text
    assert _advance(client, h, pid, "verify",
                    "targeted verification passed").status_code == 200

    # Review package + PR-style review artifact.
    r = client.post(f"/api/spec-v2/{pid}/review-package", headers=h)
    assert r.status_code == 200, r.text
    pkg_id = r.json()["id"]
    for axis in ("spec", "quality"):
        r = client.post(f"/api/spec-v2/{pid}/review/{axis}",
                        json={"verdict": "pass",
                              "artifact": f"review of package {pkg_id}: ok",
                              "review_package_id": pkg_id}, headers=h)
        assert r.status_code == 200, r.text
    r = client.get(f"/api/spec-v2/{pid}/review-pr", headers=h)
    assert r.status_code == 200, r.text
    assert "Overall: PASS" in r.json()["review_pr"]
    assert "sample/greet.py" in r.json()["review_pr"]

    # Convergence report: no gaps for this sample, then converge.
    r = client.post(f"/api/spec-v2/{pid}/converge-report", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["gaps"] == []
    report = r.json()["report"]
    assert "# Convergence report" in report
    r = _advance(client, h, pid, "converge", report)
    assert r.status_code == 200, r.text
    r = client.get(f"/api/spec-v2/{pid}/artifacts", headers=h)
    assert r.status_code == 200
    stages = [a["stage"] for a in r.json()["artifacts"]]
    assert stages == ["constitution", "spec", "clarify", "plan", "checklist",
                      "tasks", "analyze", "implement", "verify", "converge"]

    # Filesystem artifact store mirrors the same stages.
    store = ArtifactStore(tmp_path / "spec-artifacts")
    store.write(pid, "converge", report)
    assert store.read(pid, "converge") == report
    assert "converge-report.md" in store.list_artifacts(pid)


def test_qa_and_deploy_and_codegraph_api(client, tmp_path, monkeypatch):
    h = _auth(client)
    # QA endpoints
    r = client.get("/api/qa/levels", headers=h)
    assert r.status_code == 200
    assert r.json()["levels"] == ["targeted", "package", "integration", "full"]
    r = client.post("/api/qa/normalize",
                    json={"body": {"ts": "2026-10-25T00:00:00Z", "n": 1},
                          "noise_fields": ["ts"]}, headers=h)
    assert r.json()["normalized"]["ts"] == "<noise>"
    r = client.post("/api/qa/report",
                    json={"results": [{"case": {"path": "/api/features"},
                                       "status": "passed"}],
                          "untested": ["GET /api/unknown"]}, headers=h)
    assert r.status_code == 200
    assert (r.json()["passed"], r.json()["untested"]) == (1, 1)
    # Deploy interface: deferred, never a live dependency.
    r = client.get("/api/deploy/connectors", headers=h)
    assert r.status_code == 200
    assert all(c["status"] == "deferred" for c in r.json()["connectors"])
    r = client.get("/api/deploy/permissions?role=owner", headers=h)
    assert r.json()["permissions"]["deploy.deploy"] is True
    r = client.get("/api/deploy/permissions?role=lan_device", headers=h)
    assert r.json()["permissions"]["deploy.deploy"] is False
    # Code-graph extensions over a workspace-rooted sample tree.
    sample = tmp_path / "graphroot"
    sample.mkdir()
    (sample / "a.py").write_text("from b import helper\ndef foo():\n    helper()\n")
    (sample / "b.py").write_text("from a import foo\ndef helper():\n    foo()\n")
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", sample)
    invalidate_cache(sample)
    r = client.get("/api/code-graph/cycles", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 1
    r = client.get("/api/code-graph/architecture", headers=h)
    assert r.status_code == 200 and r.json()["symbols"] == 2
    r = client.get("/api/code-graph/impact?target=file%3Ab.py", headers=h)
    assert r.status_code == 200
    assert r.json()["callers_transitive"] == ["a.py#foo"]
    r = client.get("/api/code-graph/search-v2?q=helper", headers=h)
    assert r.status_code == 200
    assert r.json()["merged"][0]["source"] == "graph+grep"
    # Record + replay a real API exchange through the same client.
    rec = Recorder()
    case, _ = rec.record_response(client, "GET", "/api/features", headers=h)
    assert case["status"] == 200
    results = replay_cases(client, rec.cases, extra_headers=h)
    assert results[0]["passed"] is True, results[0]


def test_qa_generated_file_replays_green(client, tmp_path):
    """Generated pytest file runs green in a subprocess (no model call).

    The case is recorded through the real app in this test, the
    generated file + cassette are written to tmp_path, and the file
    is executed by a fresh pytest subprocess with SANGAM_REPO_ROOT
    pointing at this worktree. A non-zero exit fails this test.
    """
    h = _auth(client)
    rec = Recorder()
    case, _ = rec.record_response(client, "GET", "/api/features", headers=h)
    assert case["status"] == 200
    cassette = save_cassette(rec.cases, tmp_path / "test_qa_replay_gen.json")
    gen = generate_pytest_file(cassette, tmp_path / "test_qa_replay_gen.py")
    assert gen.exists()
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy",
                                "https_proxy", "ALL_PROXY", "all_proxy")}
    env["TEST_MODE"] = "1"
    env["SANGAM_REPO_ROOT"] = str(_ROOT)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(gen), "-q", "-p", "no:cacheprovider"],
        capture_output=True, text=True, timeout=300, env=env, cwd=str(_ROOT))
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    assert "1 passed" in proc.stdout
