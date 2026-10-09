"""Tests for Phase 3: knowledge graph, approval gate, run history."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


# --- knowledge graph ---

def test_build_knowledge_graph():
    from backend.knowledge_graph import build_knowledge_graph
    g = build_knowledge_graph(
        memories=[{"id": "1", "content": "User likes python testing", "kind": "semantic", "importance": 0.8}],
        documents=[{"id": "d1", "filename": "test_plan.py", "mime_type": "text/x-python", "size": 100}],
        chats=[{"id": "c1", "title": "Python testing help", "model": "gpt-4o"}],
        max_nodes=50,
    )
    assert g["stats"]["memories"] == 1
    assert g["stats"]["documents"] == 1
    assert g["stats"]["chats"] == 1
    # 3 content nodes + 1 memory wing node (Phase 6: wings group by kind)
    assert len(g["nodes"]) == 4
    wing = next((n for n in g["nodes"] if n["type"] == "wing"), None)
    assert wing is not None
    assert wing["id"] == "wing:semantic"


def test_knowledge_endpoints_registered():
    from fastapi.testclient import TestClient
    from backend.main import app
    paths = TestClient(app).get("/openapi.json").json()["paths"].keys()
    assert "/api/knowledge/graph" in paths
    assert "/api/knowledge/search" in paths
    assert "/api/runs" in paths


# --- approval gate ---

@pytest.mark.asyncio
async def test_approval_approve(monkeypatch):
    import backend.code_agent as ca

    async def fake_llm(model_id, messages, tools, db):
        # First call: request write_file. Second: done.
        if len([m for m in messages if m.get("role") == "tool"]) == 0:
            class M(dict):
                def get(self, k, d=None): return super().get(k, d)
            class C:
                def __init__(self, m): self.message = m
            class R:
                def __init__(self, m): self.choices = [C(m)]
            return R(M({"content": "", "tool_calls": [
                {"id": "1", "function": {"name": "write_file",
                 "arguments": '{"path": "x.txt", "content": "hi"}'}}]}))
        class M(dict):
            def get(self, k, d=None): return super().get(k, d)
        class C:
            def __init__(self, m): self.message = m
        class R:
            def __init__(self, m): self.choices = [C(m)]
        return R(M({"content": "Done", "tool_calls": []}))

    async def fake_tool(name, args):
        return {"ok": True, "path": args.get("path")}
    monkeypatch.setattr(ca, "_llm_with_tools", fake_llm)
    monkeypatch.setattr(ca, "_execute_tool", fake_tool)
    monkeypatch.setattr("backend.instincts.get_relevant_instincts", lambda task, limit=4: [])

    steps = []
    async def collect():
        async for s in ca.run_agent("write x", "openai::gpt-4o", db=None,
                                     tool_names=["write_file"],
                                     require_approval=["write_file"],
                                     approval_timeout=5.0):
            steps.append(s)
            if s.kind == "approval_needed":
                # Simulate user approving
                ca.resolve_approval(s.approval_id, True)
    await collect()
    kinds = [s.kind for s in steps]
    assert "approval_needed" in kinds
    assert "tool_call" in kinds  # approved, so it ran


@pytest.mark.asyncio
async def test_approval_deny(monkeypatch):
    import backend.code_agent as ca

    async def fake_llm(model_id, messages, tools, db):
        if len([m for m in messages if m.get("role") == "tool"]) == 0:
            class M(dict):
                def get(self, k, d=None): return super().get(k, d)
            class C:
                def __init__(self, m): self.message = m
            class R:
                def __init__(self, m): self.choices = [C(m)]
            return R(M({"content": "", "tool_calls": [
                {"id": "1", "function": {"name": "write_file",
                 "arguments": '{"path": "x.txt"}'}}]}))
        class M(dict):
            def get(self, k, d=None): return super().get(k, d)
        class C:
            def __init__(self, m): self.message = m
        class R:
            def __init__(self, m): self.choices = [C(m)]
        return R(M({"content": "Done", "tool_calls": []}))
    async def fake_tool(name, args):
        raise AssertionError("should not run when denied")
    monkeypatch.setattr(ca, "_llm_with_tools", fake_llm)
    monkeypatch.setattr(ca, "_execute_tool", fake_tool)
    monkeypatch.setattr("backend.instincts.get_relevant_instincts", lambda task, limit=4: [])

    steps = []
    async for s in ca.run_agent("write x", "openai::gpt-4o", db=None,
                                tool_names=["write_file"],
                                require_approval=["write_file"],
                                approval_timeout=5.0):
        steps.append(s)
        if s.kind == "approval_needed":
            ca.resolve_approval(s.approval_id, False)
    # Denied: tool_call should NOT appear
    assert "approval_needed" in [s.kind for s in steps]
    assert "tool_call" not in [s.kind for s in steps]


def test_approve_endpoint_registered():
    from fastapi.testclient import TestClient
    from backend.main import app
    paths = TestClient(app).get("/openapi.json").json()["paths"].keys()
    assert "/api/agent/approve/{approval_id}" in paths
