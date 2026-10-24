"""Batch 7 (Model Fit Advisor) tests.

Covers: quant memory maths (7B Q4_K fits 16GB, 70B Q4_K does not fit
8GB, KV-cache grows with context); hardware detection with VRAM
"unknown" when nvidia-smi is absent (mocked subprocess); recommend
ranks a fitting model above a non-fitting one and labels the non-fit;
benchmark with a mocked provider stream computes TTFT + tok/s from
usage when present and labels word-count estimates when absent, and
503s with no model; Ollama pull returns 503 when Ollama is unreachable.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ["TEST_MODE"] = "1"

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "mainfiles") not in sys.path:
    sys.path.insert(0, str(_ROOT / "mainfiles"))

import backend.api_routes.fit_routes as fit_routes  # noqa: E402
import backend.model_fit as model_fit  # noqa: E402
from backend.config import settings  # noqa: E402
from backend.database import AsyncSessionLocal, Base, get_engine, reset_engine_for_testing  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.ratelimit_redis import reset_rate_limit_store_for_testing  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _api_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/b7fit.db")
    reset_engine_for_testing()
    reset_rate_limit_store_for_testing()

    async def _create_all():
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create_all())
    return TestClient(create_app())


@pytest.fixture
def client(tmp_path, monkeypatch):
    return _api_client(tmp_path, monkeypatch)


def _auth_headers(client):
    creds = {"username": "b7_user", "password": "StrongPass123!"}
    r = client.post("/api/auth/register", json=creds)
    data = r.json() if r.status_code == 201 else client.post("/api/auth/login", json=creds).json()
    return {"Authorization": f"Bearer {data['access_token']}",
            "X-CSRF-Token": data["csrf_token"]}


# ---------------------------------------------------------------- maths

def test_7b_q4k_fits_16gb_and_70b_does_not_fit_8gb():
    assert model_fit.fit_score(7, "Q4_K", 32, 4096, 8192, 16)["fits"] is True
    score = model_fit.fit_score(70.6, "Q4_K", 80, 8192, 8192, 8)
    assert score["fits"] is False
    assert score["est_memory_gb"] > 8


def test_kv_cache_grows_with_context():
    small = model_fit.kv_cache_gb(32, 4096, 4096)
    big = model_fit.kv_cache_gb(32, 4096, 32768)
    assert big > small
    assert model_fit.kv_cache_gb(32, 4096, 8192) == pytest.approx(
        2 * 32 * 4096 * 8192 * 2.0 / 1e9)


def test_unknown_quant_raises():
    with pytest.raises(ValueError):
        model_fit.weights_gb(7, "Q9_ZZZ")


# ------------------------------------------------------------- hardware

class _FakeRun:
    def __init__(self, stdout):
        self.stdout = stdout


def test_hardware_vram_unknown_without_nvidia_smi(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: None)
    hw = model_fit.detect_hardware()
    assert hw["vram_gb"] is None
    assert hw["vram_status"] == "unknown"
    assert isinstance(hw["cpu_count"], int)
    assert hw["ram_gb"] is None or hw["ram_gb"] > 0


def test_hardware_vram_from_nvidia_smi(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    status, gb = model_fit._vram_gb(runner=lambda *a, **k: _FakeRun("24576\n"))
    assert status == "nvidia" and gb == 24.0


# ------------------------------------------------------------ recommend

def test_recommend_ranks_fitting_above_non_fitting_and_labels_it():
    hw = {"ram_gb": 16.0, "vram_gb": None}
    rows = model_fit.recommend(hw, use_case="chat", max_context=8192)
    assert rows
    fits = [i for i, r in enumerate(rows) if r["fits"]]
    nonfits = [i for i, r in enumerate(rows) if not r["fits"]]
    assert fits and nonfits
    assert max(fits) < min(nonfits)
    big = next(r for r in rows if r["id"] == "llama-3.1-70b")
    assert big["fits"] is False
    assert big["fits_label"] == "does not fit on this machine"
    assert big["bottleneck"] in ("weights", "kv-cache")


def test_recommend_embeddings_not_runnable_for_chat():
    rows = model_fit.recommend({"ram_gb": 16.0, "vram_gb": None}, use_case="chat")
    assert all(r["runnable"] for r in rows)
    assert not any("embeddings" in r["use_cases"] for r in rows)
    emb = model_fit.recommend({"ram_gb": 16.0, "vram_gb": None}, use_case="embeddings")
    assert emb and all(r["runnable"] is False for r in emb)


def test_recommend_api_labels_non_fit(client):
    h = _auth_headers(client)
    r = client.post("/api/models/recommend", json={"use_case": "chat"}, headers=h)
    assert r.status_code == 200, r.text
    recs = r.json()["recommendations"]
    assert recs
    for rec in recs:
        assert rec["fits_label"] in ("fits on this machine", "does not fit on this machine")
        if not rec["fits"]:
            assert rec["fits_label"] == "does not fit on this machine"


def test_hardware_api_and_catalogue_api(client):
    h = _auth_headers(client)
    r = client.get("/api/models/hardware", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "ram_gb" in body and "vram_status" in body
    r = client.get("/api/models/catalogue", headers=h)
    assert r.status_code == 200
    models = r.json()["models"]
    assert len(models) >= 12
    emb = [m for m in models if "embeddings" in m["use_cases"]]
    assert emb and all(m["runnable"] is False for m in emb)


# ------------------------------------------------------------ benchmark

class _Chunk:
    def __init__(self, text, output_tokens=None):
        self.text = text
        self.usage = type("U", (), {"output_tokens": output_tokens})() if output_tokens is not None else None


async def _gen_with_usage():
    yield _Chunk("Hello ", None)
    yield _Chunk("world", 4)


async def _gen_plain():
    yield "Hello "
    yield "brave new world"


def test_benchmark_uses_provider_usage_when_present():
    res = asyncio.run(model_fit.run_benchmark(_gen_with_usage()))
    assert res["token_source"] == "provider-usage"
    assert res["tokens"] == 4
    assert res["ttft_s"] is not None and res["tok_per_s"] > 0


def test_benchmark_labels_word_estimate_when_usage_absent():
    res = asyncio.run(model_fit.run_benchmark(_gen_plain()))
    assert res["token_source"] == "estimated-words"
    assert res["tokens"] == 4  # Hello brave new world
    assert "estimated from text" in res["token_source_note"]


def test_benchmark_api_503_with_no_model(client, monkeypatch):
    h = _auth_headers(client)

    async def _no_model(db):
        return None

    monkeypatch.setattr(fit_routes.llm, "default_model_id", _no_model)
    r = client.post("/api/models/benchmark", json={}, headers=h)
    assert r.status_code == 503, r.text
    assert "No model is configured" in r.text


def test_benchmark_api_remote_needs_explicit_flag(client):
    h = _auth_headers(client)
    r = client.post("/api/models/benchmark",
                    json={"model_id": "openai:gpt-4o"}, headers=h)
    assert r.status_code == 422, r.text


def test_benchmark_api_stores_and_lists(client, monkeypatch):
    h = _auth_headers(client)

    async def _fake_stream(model_id, messages, db, max_tokens=None, **kw):
        yield _Chunk("Hello ", None)
        yield _Chunk("world", 4)

    monkeypatch.setattr(fit_routes.llm, "stream_completion", _fake_stream)
    r = client.post("/api/models/benchmark",
                    json={"model_id": "ollama:llama3.1"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_source"] == "provider-usage" and body["tokens"] == 4
    r = client.get("/api/models/benchmarks", headers=h)
    assert r.status_code == 200
    assert any(b["model_id"] == "ollama:llama3.1" for b in r.json()["benchmarks"])


def test_ollama_pull_503_when_unreachable(client, monkeypatch):
    import httpx

    h = _auth_headers(client)

    def _boom(*a, **k):
        raise httpx.ConnectError("refused", request=None)

    monkeypatch.setattr(httpx, "get", _boom)
    r = client.post("/api/models/ollama/pull", json={"model": "llama3.1"}, headers=h)
    assert r.status_code == 503, r.text
    assert "ollama serve" in r.text
