"""Batch 3: new workflow node types (engine guarantees unchanged).

Covers validation, the restricted code evaluator (including rejections),
condition + run_if gating, loop, extract, prompt_transform, and crawl with
a mocked HTTP client. LLM/agent nodes are covered by validation + the
no-db error path only — they need provider keys and are exercised live
through the canvas spec, not unit tests.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mainfiles"))

from backend.workflows import (  # noqa: E402
    WorkflowError,
    eval_code_expression,
    execute_definition,
    validate_definition,
)


def _def(nodes, edges=None):
    return {"nodes": nodes, "edges": edges or []}


def test_new_node_validation():
    assert validate_definition(_def([
        {"id": "c", "type": "condition", "config": {"left": "a", "op": "==", "right": "a"}},
    ])) == ["c"]
    with pytest.raises(WorkflowError):
        validate_definition(_def([{"id": "t", "type": "tool", "config": {"tool": "run_bash"}}]))
    with pytest.raises(WorkflowError):
        validate_definition(_def([{"id": "l", "type": "llm", "config": {}}]))
    with pytest.raises(WorkflowError):
        validate_definition(_def([{"id": "c", "type": "crawl",
                                   "config": {"url": "https://example.com", "max_pages": 99}}]))


@pytest.mark.asyncio
async def test_code_evaluator_safe_and_restricted():
    assert eval_code_expression("len(items) * 2 + 1", {"items": [1, 2, 3]}) == 7
    assert eval_code_expression("x if x > 5 else 0", {"x": 3}) == 0
    for bad in ("__import__('os')", "x.foo", "open('x')", "lambda x: x",
                "x.attr", "[i for i in items]"):
        with pytest.raises(WorkflowError):
            eval_code_expression(bad, {"x": 1, "items": [1]})


@pytest.mark.asyncio
async def test_condition_run_if_and_loop_and_extract():
    nodes = [
        {"id": "check", "type": "condition",
         "config": {"left": "{{input.n}}", "op": ">", "right": "5"}},
        {"id": "yes", "type": "text", "config": {"template": "big"},
         "run_if": "{{nodes.check.branch}}"},
        {"id": "sentence", "type": "text", "config": {"template": "order 42 ready"}},
        {"id": "looped", "type": "loop",
         "config": {"items": '["a", "b"]', "item_template": "got {{item}} #{{item_index}}"}},
        {"id": "ext", "type": "extract",
         "config": {"source": "nodes.sentence",
                    "pattern": r"(?P<word>[a-z]+) (?P<num>\d+)", "mode": "first"}},
        {"id": "pt", "type": "prompt_transform",
         "config": {"system": "You are helpful.", "user": "Say {{input.n}}"}},
    ]
    edges = [{"from": "check", "to": "yes"}, {"from": "sentence", "to": "ext"}]
    # n=10: check true -> gated node runs.
    outputs, results, error = await execute_definition(_def(nodes, edges), {"n": 10})
    assert error is None
    assert results["check"]["output"] == {"branch": "true", "value": True}
    assert outputs["yes"] == "big"
    assert outputs["looped"] == ["got a #0", "got b #1"]
    assert outputs["ext"] == {"word": "order", "num": "42"}
    assert outputs["pt"] == {"system": "You are helpful.", "user": "Say 10"}
    # n=3: check false -> gated node skips WITHOUT failing the run.
    outputs, results, error = await execute_definition(_def(nodes, edges), {"n": 3})
    assert error is None
    assert results["check"]["output"]["branch"] == "false"
    assert results["yes"]["status"] == "skipped"
    assert results["yes"].get("reason") == "run_if false"


@pytest.mark.asyncio
async def test_extract_json_path_and_code_node():
    outputs, results, error = await execute_definition(_def([
        {"id": "src", "type": "text", "config": {"template": '{"user": {"name": "Ada"}}'}},
        {"id": "name", "type": "extract", "config": {"source": "nodes.src", "json_path": "user.name"}},
        {"id": "calc", "type": "code", "config": {"expression": "len(name) + 1",
                                                     "variables": {"name": "{{nodes.name}}"}}},
    ], edges=[{"from": "src", "to": "name"}, {"from": "name", "to": "calc"}]), {})
    assert error is None
    assert outputs["name"] == "Ada"
    assert outputs["calc"] == 4


@pytest.mark.asyncio
async def test_llm_node_without_db_errors_cleanly():
    outputs, results, error = await execute_definition(_def([
        {"id": "m", "type": "llm", "config": {"prompt": "hi"}},
    ]), {})
    assert results["m"]["status"] == "failed"
    assert "database session" in results["m"]["error"]


@pytest.mark.asyncio
async def test_crawl_same_host_only(monkeypatch):
    import httpx

    # The SSRF guard resolves DNS; example.com must not need real DNS here
    # (the guard itself is covered by Phase 2 tests).
    from backend import ingest_url

    monkeypatch.setattr(ingest_url, "validate_url", lambda url: "example.com")

    pages = {
        "https://example.com/": "<html><body><a href='/page2'>two</a>"
                                "<a href='https://other.com/x'>offsite</a>Home text</body></html>",
        "https://example.com/page2": "<html><body>Page two text</body></html>",
    }

    class FakeResp:
        def __init__(self, body):
            self.status_code = 200
            self.content = body.encode()

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **k):
            return FakeResp(pages[url])

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    outputs, results, error = await execute_definition(_def([
        {"id": "c", "type": "crawl",
         "config": {"url": "https://example.com/", "max_pages": 5, "max_depth": 1}},
    ]), {})
    assert error is None
    urls = [p["url"] for p in outputs["c"]]
    assert "https://example.com/" in urls
    assert "https://example.com/page2" in urls
    assert not any("other.com" in u for u in urls)
