"""Tests for the agent engine (code_agent.py), code graph, instincts, and new endpoints."""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


# --- instincts ------------------------------------------------------------

def test_instincts_relevant(tmp_path, monkeypatch):
    import backend.instincts as inst
    monkeypatch.setattr(inst, "_PATH", tmp_path / "instincts.json")
    got = inst.get_relevant_instincts("fix the python tests")
    assert any("test" in g.lower() for g in got)
    assert len(got) <= 4


def test_instincts_record_and_reinforce(tmp_path, monkeypatch):
    import backend.instincts as inst
    monkeypatch.setattr(inst, "_PATH", tmp_path / "instincts.json")
    inst.record_instinct("Always run lint before commit.", ["lint"])
    items = inst._read()
    assert any(i["pattern"].startswith("Always run lint") for i in items)
    before = next(i["confidence"] for i in items if i["pattern"].startswith("Always run lint"))
    inst.reinforce_instinct("Always run lint before commit.", helped=True)
    after = next(i["confidence"] for i in inst._read() if i["pattern"].startswith("Always run lint"))
    assert after > before
    inst.reinforce_instinct("Always run lint before commit.", helped=False)
    after2 = next(i["confidence"] for i in inst._read() if i["pattern"].startswith("Always run lint"))
    assert after2 < after


# --- code graph -----------------------------------------------------------

def test_code_graph_build_and_explain(tmp_path):
    from backend.code_graph import build_graph, explain, find_path
    (tmp_path / "a.py").write_text("def foo():\n    bar()\n\ndef bar():\n    pass\n")
    (tmp_path / "b.py").write_text("from a import foo\ndef baz():\n    foo()\n")
    g = build_graph(tmp_path)
    assert g["files"] == 2
    assert "foo" in g["symbols"] or any(k.endswith("foo") for k in g["symbols"])
    e = explain("foo", g)
    assert "symbol" in e
    assert e["call_count"] >= 1
    assert explain("nonexistent_xyz", g).get("error")


def test_code_graph_path(tmp_path):
    from backend.code_graph import build_graph, find_path
    (tmp_path / "a.py").write_text("def alpha():\n    beta()\ndef beta():\n    gamma()\ndef gamma():\n    pass\n")
    g = build_graph(tmp_path)
    p = find_path("alpha", "gamma", g)
    assert p["hops"] == 2
    assert p["path"][0].endswith("alpha")


# --- agent engine (mocked LLM) --------------------------------------------

class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeResp:
    def __init__(self, message):
        self.choices = [_FakeChoice(message)]


class _FakeMsg(dict):
    def get(self, k, d=None):
        return super().get(k, d)


@pytest.mark.asyncio
async def test_run_agent_tool_loop(monkeypatch):
    import backend.code_agent as ca

    calls = []

    async def fake_llm(model_id, messages, tools, db):
        n = len(calls)
        calls.append(1)
        if n == 0:
            return _FakeResp(_FakeMsg({
                "content": "Let me check.",
                "tool_calls": [{"id": "1", "function": {
                    "name": "web_search",
                    "arguments": json.dumps({"query": "test"})}}],
            }))
        return _FakeResp(_FakeMsg({"content": "Done.", "tool_calls": []}))
    monkeypatch.setattr(ca, "_llm_with_tools", fake_llm)

    async def fake_tool(name, args):
        assert name == "web_search"
        return {"results": ["r1"]}
    monkeypatch.setattr(ca, "_execute_tool", fake_tool)
    monkeypatch.setattr("backend.instincts.get_relevant_instincts", lambda task, limit=4: [])

    steps = [s async for s in ca.run_agent("hi", "openai::gpt-4o", db=None,
                                           tool_names=["web_search"], max_iterations=5)]
    kinds = [s.kind for s in steps]
    assert "tool_call" in kinds
    assert "tool_result" in kinds
    assert "answer" in kinds
    assert steps[-1].content == "Done."


@pytest.mark.asyncio
async def test_run_agent_llm_error(monkeypatch):
    import backend.code_agent as ca

    async def boom(model_id, messages, tools, db):
        raise RuntimeError("no key")
    monkeypatch.setattr(ca, "_llm_with_tools", boom)
    monkeypatch.setattr("backend.instincts.get_relevant_instincts", lambda task, limit=4: [])

    steps = [s async for s in ca.run_agent("hi", "openai::gpt-4o", db=None, max_iterations=2)]
    assert steps[-1].kind == "error"
    assert "no key" in steps[-1].content


@pytest.mark.asyncio
async def test_run_agent_max_iterations(monkeypatch):
    import backend.code_agent as ca

    async def fake_llm(model_id, messages, tools, db):
        return _FakeResp(_FakeMsg({
            "content": "",
            "tool_calls": [{"id": "1", "function": {"name": "web_search", "arguments": "{}"}}],
        }))
    monkeypatch.setattr(ca, "_llm_with_tools", fake_llm)
    async def _ok_tool(n, a):
        return {"ok": True}
    monkeypatch.setattr(ca, "_execute_tool", _ok_tool)
    monkeypatch.setattr("backend.instincts.get_relevant_instincts", lambda task, limit=4: [])

    steps = [s async for s in ca.run_agent("hi", "openai::gpt-4o", db=None,
                                           tool_names=["web_search"], max_iterations=3)]
    assert steps[-1].kind == "done"
    assert "max steps" in steps[-1].content.lower()


# --- new endpoints ----------------------------------------------------------

def _openapi_paths():
    from fastapi.testclient import TestClient
    from backend.main import app
    c = TestClient(app)
    return list(c.get("/openapi.json").json()["paths"].keys())


def test_agent_run_endpoint_registered():
    paths = _openapi_paths()
    assert "/api/agent/run" in paths
    assert "/api/v1/agent/run" in paths


def test_append_messages_endpoint_registered():
    paths = _openapi_paths()
    assert any("/chats/{chat_id}/messages" in p for p in paths)


def test_agentic_reasoning_endpoint_gone():
    paths = _openapi_paths()
    assert not any("agentic-reasoning" in p for p in paths)
