"""
api_routes/fit_routes.py — model fit advisor API (Batch 7, llmfit analogue).

GET  /models/hardware           host CPU/RAM/VRAM detection (VRAM unknown
                                unless nvidia-smi answers — never guessed)
GET  /models/catalogue          built-in catalogue (estimates, not live
                                measurements; embeddings marked non-runnable)
POST /models/recommend          ranked fit/speed/quality/context list
POST /models/benchmark          timed generation via the provider stream
                                path; local (Ollama) only unless the caller
                                passes allow_remote=true — cloud models are
                                never benchmarked silently at the user's cost
GET  /models/benchmarks         stored benchmark results, newest first
POST /models/ollama/pull        start an Ollama pull (202 + poll id)
GET  /models/ollama/pulls/{id}   poll a pull
DELETE /models/ollama/{model}    delete an Ollama model

Benchmark 503: if no model is configured, the endpoint says so plainly
and returns no numbers — numbers are never faked.
"""
from __future__ import annotations

import threading
import uuid

import httpx
from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import llm
from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..model_fit import (
    CATALOGUE,
    ModelBenchmark,
    detect_hardware,
    recommend,
    run_benchmark,
)
from .common import router

OLLAMA_UNREACHABLE = (
    "Ollama is not reachable on this machine. Start it with `ollama serve` "
    "and download a model, or use a cloud key instead."
)

_PULLS: dict[str, dict] = {}


def _ollama_base() -> str:
    return settings.OLLAMA_BASE_URL.rstrip("/")


@router.get("/models/hardware")
async def get_hardware(user=Depends(get_current_user)):
    return detect_hardware()


@router.get("/models/catalogue")
async def get_catalogue(user=Depends(get_current_user)):
    return {"models": CATALOGUE, "note": "Catalogue estimates from public model-card sizes, not live measurements."}


class RecommendIn(BaseModel):
    use_case: str | None = None
    max_context: int | None = None


async def _latest_benchmarks(db: AsyncSession) -> dict[str, float]:
    """Latest measured tok/s per model id (provider-usage or
    estimated-words rows both count as stored measurements; the
    route labels them measured because a real run produced them,
    and model_fit marks the speed source accordingly)."""
    try:
        res = await db.execute(
            select(ModelBenchmark).order_by(ModelBenchmark.created_at.desc()).limit(200)
        )
        out: dict[str, float] = {}
        for row in res.scalars().all():
            if row.model_id not in out and row.tok_per_s:
                out[row.model_id] = row.tok_per_s
        return out
    except Exception:
        return {}


@router.post("/models/recommend")
async def recommend_models(payload: RecommendIn, db: AsyncSession = Depends(get_db),
                           user=Depends(get_current_user)):
    hardware = detect_hardware()
    benchmarks = await _latest_benchmarks(db)
    return {
        "hardware": hardware,
        "recommendations": recommend(hardware, payload.use_case, payload.max_context,
                                     benchmarks=benchmarks),
        "measured_from_benchmarks": sorted(benchmarks),
    }


class RouteIn(BaseModel):
    strategy: str = "priority"
    candidates: list[str] | None = None
    costs: dict[str, float] | None = None
    billable: list[str] | None = None
    session_id: str | None = None
    pin: bool = False


@router.post("/models/route")
async def route_model(payload: RouteIn, user=Depends(get_current_user)):
    """OmniRoute strategy choice over Sangam's provider registry:
    returns the chosen provider + why (scores/inputs shown), or
    available=false with a reason (fail-closed never bills).
    With pin=true and a session_id, the session is pinned to the
    chosen provider for subsequent chooses until unpinned — pass
    pin=false with the same session_id to keep the pin unchanged;
    unpinning is a client-side session reset (new session_id)."""
    from ..providers.fallback_chain import STRATEGIES, get_fallback_chain

    if payload.strategy not in STRATEGIES:
        raise HTTPException(422, f"Unknown strategy: {payload.strategy!r} "
                                 f"(known: {', '.join(STRATEGIES)})")
    chain = get_fallback_chain()
    if payload.pin and payload.session_id:
        # Pin only after choosing, so a pin never forces a dead provider.
        provider, reasons = chain.choose(payload.strategy, payload.candidates,
                                         costs=payload.costs,
                                         billable=set(payload.billable or []),
                                         session_id=None)
        if provider:
            chain.pin_session(payload.session_id, provider)
        return {"strategy": payload.strategy, "provider": provider,
                "reasons": reasons, "pinned_session": payload.session_id if provider else None}
    provider, reasons = chain.choose(payload.strategy, payload.candidates,
                                     costs=payload.costs,
                                     billable=set(payload.billable or []),
                                     session_id=payload.session_id)
    return {"strategy": payload.strategy, "provider": provider,
            "reasons": reasons,
            "pinned_provider": chain.pinned_provider(payload.session_id)}


class BenchmarkIn(BaseModel):
    model_id: str | None = None
    prompt: str = "Say hello in one short sentence."
    max_tokens: int | None = 64
    allow_remote: bool = False


@router.post("/models/benchmark")
async def benchmark_model(
    payload: BenchmarkIn,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    model_id = payload.model_id
    if not model_id:
        try:
            model_id = await llm.default_model_id(db)
        except Exception:
            model_id = None
    if not model_id:
        raise HTTPException(
            status_code=503,
            detail="No model is configured. Add a provider key or start Ollama, then try again.",
        )
    is_local = "ollama" in model_id.lower()
    if not is_local and not payload.allow_remote:
        raise HTTPException(
            status_code=422,
            detail="Benchmarking is for local models unless allow_remote=true is passed explicitly.",
        )
    messages = [{"role": "user", "content": payload.prompt}]
    try:
        result = await run_benchmark(
            llm.stream_completion(model_id, messages, db, max_tokens=payload.max_tokens)
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Benchmark failed: {exc}") from exc
    row = ModelBenchmark(
        id=uuid.uuid4().hex[:12],
        model_id=model_id,
        prompt=payload.prompt,
        ttft_s=result["ttft_s"],
        tokens=result["tokens"],
        duration_s=result["duration_s"],
        tok_per_s=result["tok_per_s"],
        token_source=result["token_source"],
    )
    db.add(row)
    await db.commit()
    return {"model_id": model_id, **result}


@router.get("/models/benchmarks")
async def list_benchmarks(db: AsyncSession = Depends(get_db), user=Depends(get_current_user)):
    res = await db.execute(
        select(ModelBenchmark).order_by(ModelBenchmark.created_at.desc()).limit(50)
    )
    rows = res.scalars().all()
    return {"benchmarks": [
        {
            "id": r.id, "model_id": r.model_id, "prompt": r.prompt,
            "ttft_s": r.ttft_s, "tokens": r.tokens, "duration_s": r.duration_s,
            "tok_per_s": r.tok_per_s, "token_source": r.token_source,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]}


# ---------------------------------------------------------------- Ollama mgmt

class OllamaPullIn(BaseModel):
    model: str


def _pull_worker(pull_id: str, model: str) -> None:
    rec = _PULLS[pull_id]
    try:
        with httpx.stream(
            "POST", f"{_ollama_base()}/api/pull", json={"name": model, "stream": True},
            timeout=3600,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    import json as _json

                    data = _json.loads(line)
                except ValueError:
                    continue
                rec["status"] = data.get("status", rec["status"])
                if data.get("error"):
                    rec["status"] = "error"
                    rec["detail"] = str(data["error"])
                    return
        rec["status"] = "success"
    except Exception as exc:  # noqa: BLE001
        rec["status"] = "error"
        rec["detail"] = str(exc)


@router.post("/models/ollama/pull", status_code=202)
async def ollama_pull(payload: OllamaPullIn, user=Depends(get_current_user)):
    try:
        resp = httpx.get(f"{_ollama_base()}/api/tags", timeout=5)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=OLLAMA_UNREACHABLE) from exc
    pull_id = uuid.uuid4().hex[:12]
    _PULLS[pull_id] = {"id": pull_id, "model": payload.model, "status": "pulling", "detail": ""}
    thread = threading.Thread(target=_pull_worker, args=(pull_id, payload.model), daemon=True)
    thread.start()
    return {"id": pull_id, "model": payload.model, "status": "pulling"}


@router.get("/models/ollama/pulls/{pull_id}")
async def ollama_pull_status(pull_id: str, user=Depends(get_current_user)):
    rec = _PULLS.get(pull_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Unknown pull id")
    return rec


@router.delete("/models/ollama/{model:path}")
async def ollama_delete(model: str, user=Depends(get_current_user)):
    try:
        resp = httpx.request("DELETE", f"{_ollama_base()}/api/delete",
                             json={"name": model}, timeout=30)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=OLLAMA_UNREACHABLE) from exc
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Ollama model not found: {model}")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Ollama delete failed: {resp.text[:200]}")
    return {"model": model, "deleted": True}
