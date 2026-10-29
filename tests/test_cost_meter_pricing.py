"""Agent cost meter pricing: a saved cost_budget must be enforceable.

Before this change, no production caller passed price_per_1k_usd to the
agent loop, so CostMeter always reported cost_known False and a budget
was logged as unenforceable, never enforced. Prices are now derived
from LiteLLM's bundled cost table for the run's model (offline, no new
dependency); an unknown model still reports unknown cost, never a
fabricated rate.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ["TEST_MODE"] = "1"

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))


def test_model_prices_known_model_and_prefix_stripped():
    from backend.providers.pricing import model_prices

    bare = model_prices("gpt-4o-mini")
    assert bare is not None
    input_price, output_price = bare
    assert input_price == pytest.approx(1.5e-07)
    assert output_price == pytest.approx(6e-07)
    # LiteLLM's table is keyed by bare names; a provider-prefixed id
    # must resolve to the same entry.
    assert model_prices("openai/gpt-4o-mini") == bare


def test_model_prices_unknown_never_fabricates():
    from backend.providers.pricing import model_prices

    assert model_prices("no-such-model-xyz") is None
    assert model_prices("") is None
    assert model_prices(None) is None
    assert model_prices(123) is None


def test_cost_meter_per_token_prices():
    import backend.code_agent as ca

    meter = ca.CostMeter(input_price_per_token=1.5e-07,
                         output_price_per_token=6e-07)
    meter.add({"prompt_tokens": 1000, "completion_tokens": 1000,
               "total_tokens": 2000})
    # 1000 * 1.5e-07 + 1000 * 6e-07 = 0.00075, priced per direction.
    assert meter.cost_usd == pytest.approx(0.00075)
    assert meter.snapshot()["cost_known"] is True
    assert meter.budget_exceeded(0.0005) is True
    assert meter.budget_exceeded(0.001) is False


def test_cost_meter_legacy_flat_rate_unchanged():
    import backend.code_agent as ca

    meter = ca.CostMeter(price_per_1k_usd=10.0)
    meter.add({"prompt_tokens": 0, "completion_tokens": 0,
               "total_tokens": 200})
    assert meter.cost_usd == 2.0


def test_cost_meter_per_token_takes_precedence_over_flat_rate():
    import backend.code_agent as ca

    meter = ca.CostMeter(price_per_1k_usd=10.0,
                         input_price_per_token=1.5e-07,
                         output_price_per_token=6e-07)
    meter.add({"prompt_tokens": 1000, "completion_tokens": 1000,
               "total_tokens": 2000})
    assert meter.cost_usd == pytest.approx(0.00075)


class _Msg(dict):
    @property
    def content(self):
        return self.get("content", "")

    @property
    def tool_calls(self):
        return self.get("tool_calls", [])


class _Resp:
    def __init__(self, msg, usage):
        self.choices = [SimpleNamespace(message=msg, finish_reason="stop")]
        self.usage = usage


@pytest.mark.asyncio
async def test_run_agent_reports_real_cost_for_priced_model(monkeypatch):
    import backend.code_agent as ca

    seen: list = []

    async def fake_llm(model_id, messages, tools, db):
        return _Resp(_Msg({"content": "done", "tool_calls": []}),
                     SimpleNamespace(prompt_tokens=1000,
                                     completion_tokens=500,
                                     total_tokens=1500))

    monkeypatch.setattr(ca, "_llm_with_tools", fake_llm)
    monkeypatch.setattr("backend.instincts.get_relevant_instincts",
                        lambda task, limit=4: [])
    steps = [s async for s in ca.run_agent(
        "hi", "openai::gpt-4o-mini", db=None, tool_names=[],
        max_iterations=3,
        on_usage_detail=lambda snap: seen.append(snap))]
    assert seen, "on_usage_detail must receive a snapshot"
    snap = seen[-1]
    assert snap["cost_known"] is True
    # 1000 * 1.5e-07 + 500 * 6e-07 = 0.00045
    assert snap["cost_usd"] == pytest.approx(0.00045)
    assert any(s.kind == "thought" and "done" in s.content for s in steps)


@pytest.mark.asyncio
async def test_run_agent_budget_now_enforceable(monkeypatch):
    import backend.code_agent as ca

    calls = []

    async def fake_llm(model_id, messages, tools, db):
        calls.append(model_id)
        return _Resp(_Msg({"content": "", "tool_calls": [
            {"id": "1", "type": "function",
             "function": {"name": "list_files",
                          "arguments": '{"path": "."}'}}]}),
                     SimpleNamespace(prompt_tokens=100000,
                                     completion_tokens=0,
                                     total_tokens=100000))

    async def fake_tool(name, args):
        return {"ok": True}

    monkeypatch.setattr(ca, "_llm_with_tools", fake_llm)
    monkeypatch.setattr(ca, "_execute_tool", fake_tool)
    monkeypatch.setattr("backend.instincts.get_relevant_instincts",
                        lambda task, limit=4: [])
    # First iteration costs 100000 * 1.5e-07 = $0.015, so a $0.01
    # budget must stop the run at the second iteration check, before
    # a second model call. (A run that answers in one iteration
    # returns before any second check — that is the loop's existing
    # per-iteration budget semantics, not a pricing gap.)
    steps = [s async for s in ca.run_agent(
        "hi", "openai::gpt-4o-mini", db=None, tool_names=["list_files"],
        max_iterations=5, max_cost_usd=0.01)]
    assert len(calls) == 1
    assert any(s.kind == "error" and "Budget exceeded" in s.content
               for s in steps)


@pytest.mark.asyncio
async def test_run_agent_unknown_model_stays_unknown(monkeypatch):
    import backend.code_agent as ca

    seen: list = []

    async def fake_llm(model_id, messages, tools, db):
        return _Resp(_Msg({"content": "done", "tool_calls": []}),
                     SimpleNamespace(prompt_tokens=1000,
                                     completion_tokens=500,
                                     total_tokens=1500))

    monkeypatch.setattr(ca, "_llm_with_tools", fake_llm)
    monkeypatch.setattr("backend.instincts.get_relevant_instincts",
                        lambda task, limit=4: [])
    [s async for s in ca.run_agent(
        "hi", "openai::no-such-model-xyz", db=None, tool_names=[],
        max_iterations=3,
        on_usage_detail=lambda snap: seen.append(snap))]
    assert seen and seen[-1]["cost_known"] is False
    assert seen[-1]["cost_usd"] is None
