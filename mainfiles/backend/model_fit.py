"""
backend/model_fit.py — model fit advisor (AlexsJones/llmfit analogue).

Answers "which model will actually run well on this machine?" with
honest, documented estimates — never fake measurements.

Memory maths (all sizes in GB, 1 GB = 1e9 bytes):
  weights_gb = params_billions * bytes_per_param(quant)
  kv_gb      = 2 * layers * hidden * context_tokens * kv_bytes / 1e9
               (factor 2 = keys + values; kv_bytes defaults to 2 = FP16,
               the usual KV-cache dtype regardless of weight quant)
  total_gb   = weights_gb + kv_gb + OVERHEAD_GB
  OVERHEAD_GB = 1.0 (runtime, tokenizer, fragmentation allowance)

Bytes per parameter (GGUF/AWQ/GPTQ/EXL2 estimates, not measurements):
  FP32 4.0, FP16/BF16 2.0, Q8_0 1.05, Q6_K 0.81, Q5_K 0.68,
  Q4_K 0.59, Q3_K 0.44, AWQ/GPTQ 4-bit 0.55, EXL2 4bpw 0.55,
  EXL2 3bpw 0.42, EXL2 2bpw 0.31. Values include per-block scales, so
  they are slightly above the raw bit-width (e.g. Q4_K is 0.5 raw).

VRAM honesty: VRAM is reported only when nvidia-smi answers. Otherwise
vram is "unknown" — NEVER guessed. AMD GPUs and Apple-Silicon unified
memory report as "unified/unknown": the RAM figure is the only honest
budget there, and fit is judged against RAM.

Catalogue: built-in estimates from public model-card sizes (parameter
counts, context lengths, quant availability). They are NOT live
measurements. Embeddings models are marked runnable=False: they are not
runnable as chat/generation models and are never recommended for a
generation use case.

Benchmarks: stored in a small SQL table (model_benchmarks, Batch 2
precedent). Token counts use the provider's usage field when present;
otherwise words are counted and the result is labelled
"estimated-words" — never presented as exact tokens.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from typing import Any, AsyncGenerator

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

OVERHEAD_GB = 1.0
KV_BYTES = 2.0  # FP16 KV cache

BYTES_PER_PARAM: dict[str, float] = {
    "FP32": 4.0,
    "FP16": 2.0,
    "BF16": 2.0,
    "Q8_0": 1.05,
    "Q6_K": 0.81,
    "Q5_K": 0.68,
    "Q4_K": 0.59,
    "Q3_K": 0.44,
    "AWQ-4bit": 0.55,
    "GPTQ-4bit": 0.55,
    "EXL2-4bpw": 0.55,
    "EXL2-3bpw": 0.42,
    "EXL2-2bpw": 0.31,
}

QUANT_PREFERENCE = ["Q4_K", "Q5_K", "Q6_K", "Q8_0", "FP16"]


def weights_gb(params_b: float, quant: str) -> float:
    bpp = BYTES_PER_PARAM.get(quant)
    if bpp is None:
        raise ValueError(f"Unknown quantization: {quant}")
    return params_b * bpp


def kv_cache_gb(layers: int, hidden: int, context: int, kv_bytes: float = KV_BYTES) -> float:
    return 2 * layers * hidden * context * kv_bytes / 1e9


def estimate_memory_gb(
    params_b: float, quant: str, layers: int, hidden: int, context: int,
    overhead_gb: float = OVERHEAD_GB,
) -> float:
    return weights_gb(params_b, quant) + kv_cache_gb(layers, hidden, context) + overhead_gb


# ---------------------------------------------------------------- hardware

def _cpu_model() -> str:
    model = platform.processor() or ""
    if not model and os.path.exists("/proc/cpuinfo"):
        try:
            for line in open("/proc/cpuinfo", encoding="utf-8", errors="ignore"):
                if line.startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass
    return model or "unknown"


def _ram_gb() -> float | None:
    try:
        import psutil  # type: ignore[import-not-found]

        return round(psutil.virtual_memory().total / 1e9, 2)
    except Exception:
        pass
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return round(kb * 1024 / 1e9, 2)
    except (OSError, ValueError, IndexError):
        pass
    return None


def _vram_gb(runner=subprocess.run) -> tuple[str, float | None]:
    """Return (status, gb). status: 'nvidia' | 'unified/unknown' | 'unknown'.

    Never guesses: without nvidia-smi output there is no VRAM number.
    """
    exe = shutil.which("nvidia-smi")
    if exe:
        try:
            out = runner(
                [exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            vals = [float(v) for v in re.findall(r"[\d.]+", out.stdout or "")]
            if vals:
                return "nvidia", round(max(vals) / 1024, 2)
        except Exception:
            pass
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "unified/unknown", None
    return "unknown", None


def detect_hardware(runner=subprocess.run) -> dict:
    """Detect host hardware with stdlib + platform tools only."""
    vram_status, vram = _vram_gb(runner)
    return {
        "cpu_count": os.cpu_count(),
        "cpu_model": _cpu_model(),
        "ram_gb": _ram_gb(),
        "vram_status": vram_status,
        "vram_gb": vram,
        "platform": platform.system(),
        "machine": platform.machine(),
    }


def available_memory_gb(hardware: dict) -> float | None:
    """Budget for fit checks: VRAM when known, else RAM."""
    if hardware.get("vram_gb"):
        return float(hardware["vram_gb"])
    if hardware.get("ram_gb"):
        return float(hardware["ram_gb"])
    return None


# ---------------------------------------------------------------- catalogue

# Each entry: public model-card sizes (estimates). layers/hidden are the
# published architecture figures used only for the KV-cache estimate.
CATALOGUE: list[dict] = [
    {"id": "llama-3.2-1b", "name": "Llama 3.2 1B", "params_b": 1.24, "layers": 16, "hidden": 2048,
     "quants": ["Q4_K", "Q8_0", "FP16"], "context": 131072, "use_cases": ["chat"],
     "runnable": True, "source_note": "public model card sizes"},
    {"id": "llama-3.2-3b", "name": "Llama 3.2 3B", "params_b": 3.21, "layers": 28, "hidden": 3072,
     "quants": ["Q4_K", "Q5_K", "Q8_0", "FP16"], "context": 131072, "use_cases": ["chat"],
     "runnable": True, "source_note": "public model card sizes"},
    {"id": "llama-3.1-8b", "name": "Llama 3.1 8B", "params_b": 8.03, "layers": 32, "hidden": 4096,
     "quants": ["Q4_K", "Q5_K", "Q6_K", "Q8_0", "FP16"], "context": 131072, "use_cases": ["chat", "code"],
     "runnable": True, "source_note": "public model card sizes"},
    {"id": "mistral-7b", "name": "Mistral 7B", "params_b": 7.25, "layers": 32, "hidden": 4096,
     "quants": ["Q4_K", "Q5_K", "Q6_K", "Q8_0", "FP16"], "context": 32768, "use_cases": ["chat"],
     "runnable": True, "source_note": "public model card sizes"},
    {"id": "qwen2.5-7b", "name": "Qwen 2.5 7B", "params_b": 7.62, "layers": 28, "hidden": 3584,
     "quants": ["Q4_K", "Q5_K", "Q6_K", "Q8_0", "FP16"], "context": 131072, "use_cases": ["chat", "code"],
     "runnable": True, "source_note": "public model card sizes"},
    {"id": "qwen2.5-coder-7b", "name": "Qwen 2.5 Coder 7B", "params_b": 7.62, "layers": 28, "hidden": 3584,
     "quants": ["Q4_K", "Q5_K", "Q8_0", "FP16"], "context": 32768, "use_cases": ["code"],
     "runnable": True, "source_note": "public model card sizes"},
    {"id": "starcoder2-7b", "name": "StarCoder2 7B", "params_b": 7.0, "layers": 30, "hidden": 3840,
     "quants": ["Q4_K", "Q5_K", "Q8_0"], "context": 16384, "use_cases": ["code"],
     "runnable": True, "source_note": "public model card sizes"},
    {"id": "gemma-2-9b", "name": "Gemma 2 9B", "params_b": 9.24, "layers": 42, "hidden": 3584,
     "quants": ["Q4_K", "Q5_K", "Q8_0", "FP16"], "context": 8192, "use_cases": ["chat"],
     "runnable": True, "source_note": "public model card sizes"},
    {"id": "mistral-nemo-12b", "name": "Mistral Nemo 12B", "params_b": 12.2, "layers": 40, "hidden": 5120,
     "quants": ["Q4_K", "Q5_K", "Q8_0", "FP16"], "context": 131072, "use_cases": ["chat"],
     "runnable": True, "source_note": "public model card sizes"},
    {"id": "phi-4-14b", "name": "Phi-4 14B", "params_b": 14.66, "layers": 40, "hidden": 5120,
     "quants": ["Q4_K", "Q5_K", "Q8_0", "FP16"], "context": 16384, "use_cases": ["chat", "reasoning"],
     "runnable": True, "source_note": "public model card sizes"},
    {"id": "qwen2.5-14b", "name": "Qwen 2.5 14B", "params_b": 14.77, "layers": 48, "hidden": 5120,
     "quants": ["Q4_K", "Q5_K", "Q8_0", "FP16"], "context": 131072, "use_cases": ["chat", "code"],
     "runnable": True, "source_note": "public model card sizes"},
    {"id": "gemma-2-27b", "name": "Gemma 2 27B", "params_b": 27.23, "layers": 46, "hidden": 4608,
     "quants": ["Q4_K", "Q5_K", "Q8_0"], "context": 8192, "use_cases": ["chat", "reasoning"],
     "runnable": True, "source_note": "public model card sizes"},
    {"id": "qwen2.5-32b", "name": "Qwen 2.5 32B", "params_b": 32.5, "layers": 64, "hidden": 5120,
     "quants": ["Q4_K", "Q5_K", "Q8_0"], "context": 131072, "use_cases": ["chat", "code", "reasoning"],
     "runnable": True, "source_note": "public model card sizes"},
    {"id": "mixtral-8x7b", "name": "Mixtral 8x7B (MoE)", "params_b": 46.7, "layers": 32, "hidden": 4096,
     "quants": ["Q4_K", "Q5_K", "Q8_0"], "context": 32768, "use_cases": ["chat", "code"],
     "runnable": True, "source_note": "public model card sizes; MoE total params, active params per token are lower"},
    {"id": "llama-3.1-70b", "name": "Llama 3.1 70B", "params_b": 70.6, "layers": 80, "hidden": 8192,
     "quants": ["Q4_K", "Q5_K", "Q8_0", "FP16"], "context": 131072, "use_cases": ["chat", "reasoning"],
     "runnable": True, "source_note": "public model card sizes"},
    {"id": "deepseek-r1-distill-qwen-7b", "name": "DeepSeek R1 Distill Qwen 7B", "params_b": 7.62,
     "layers": 28, "hidden": 3584, "quants": ["Q4_K", "Q5_K", "Q8_0"],
     "context": 131072, "use_cases": ["reasoning"], "runnable": True,
     "source_note": "public model card sizes"},
    {"id": "nomic-embed-text", "name": "Nomic Embed Text", "params_b": 0.137, "layers": 12, "hidden": 768,
     "quants": ["FP16"], "context": 8192, "use_cases": ["embeddings"],
     "runnable": False, "source_note": "public model card sizes; embeddings-only, NOT runnable as a chat model"},
    {"id": "bge-large-en", "name": "BGE Large EN", "params_b": 0.335, "layers": 24, "hidden": 1024,
     "quants": ["FP16"], "context": 512, "use_cases": ["embeddings"],
     "runnable": False, "source_note": "public model card sizes; embeddings-only, NOT runnable as a chat model"},
]

_CATALOGUE_BY_ID = {e["id"]: e for e in CATALOGUE}


def _speed_class(params_b: float) -> str:
    if params_b <= 3:
        return "fast"
    if params_b <= 9:
        return "balanced"
    if params_b <= 15:
        return "moderate"
    if params_b <= 33:
        return "slow"
    return "very-slow"


def _quality_class(params_b: float) -> str:
    if params_b >= 32:
        return "high"
    if params_b >= 8:
        return "good"
    if params_b >= 3:
        return "decent"
    return "basic"


def fit_score(
    params_b: float, quant: str, layers: int, hidden: int, context: int,
    budget_gb: float | None,
) -> dict:
    """Score one model+quant against a memory budget (RAM or VRAM)."""
    est = estimate_memory_gb(params_b, quant, layers, hidden, context)
    fits = budget_gb is not None and est <= budget_gb
    if budget_gb is None:
        bottleneck = "unknown budget — hardware memory could not be detected"
    elif fits:
        bottleneck = "none"
    elif weights_gb(params_b, quant) > budget_gb:
        bottleneck = "weights"
    else:
        bottleneck = "kv-cache"
    return {
        "est_memory_gb": round(est, 2),
        "fits": bool(fits),
        "bottleneck": bottleneck,
        "speed_class": _speed_class(params_b),
        "quality_class": _quality_class(params_b),
    }


def recommend(
    hardware: dict, use_case: str | None = None, max_context: int | None = None,
) -> list[dict]:
    """Rank the catalogue for this machine.

    For each model, the smallest quant that fits is chosen (Q4_K first);
    a model with no fitting quant is still listed, labelled fits=False,
    ranked below every fitting model. Non-runnable embeddings models are
    only returned for use_case='embeddings', never for generation.
    """
    budget = available_memory_gb(hardware)
    context = max_context or 8192
    rows: list[dict] = []
    for entry in CATALOGUE:
        if use_case:
            if use_case not in entry["use_cases"]:
                continue
        else:
            if not entry["runnable"]:
                continue
        if max_context and entry["context"] < max_context:
            continue
        chosen = None
        chosen_score = None
        for quant in QUANT_PREFERENCE:
            if quant not in entry["quants"]:
                continue
            score = fit_score(entry["params_b"], quant, entry["layers"],
                              entry["hidden"], context, budget)
            if score["fits"]:
                chosen, chosen_score = quant, score
                break
        if chosen is None:
            quant = "Q4_K" if "Q4_K" in entry["quants"] else entry["quants"][0]
            chosen, chosen_score = quant, fit_score(
                entry["params_b"], quant, entry["layers"], entry["hidden"], context, budget)
        rows.append({
            "id": entry["id"],
            "name": entry["name"],
            "params_b": entry["params_b"],
            "quant": chosen,
            "context": entry["context"],
            "use_cases": entry["use_cases"],
            "runnable": entry["runnable"],
            "fits": chosen_score["fits"],
            "est_memory_gb": chosen_score["est_memory_gb"],
            "bottleneck": chosen_score["bottleneck"],
            "speed_class": chosen_score["speed_class"],
            "quality_class": chosen_score["quality_class"],
            "fits_label": "fits on this machine" if chosen_score["fits"]
                          else "does not fit on this machine",
            "source_note": entry["source_note"],
        })
    rows.sort(key=lambda r: (not r["fits"], -r["params_b"]))
    return rows


# ---------------------------------------------------------------- benchmarks

class ModelBenchmark(Base):
    """One stored benchmark run (Batch 2 precedent: small table in-module)."""

    __tablename__ = "model_benchmarks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    model_id: Mapped[str] = mapped_column(String(256), index=True)
    prompt: Mapped[str] = mapped_column(Text, default="")
    ttft_s: Mapped[float | None] = mapped_column(Float, default=None)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    tok_per_s: Mapped[float] = mapped_column(Float, default=0.0)
    token_source: Mapped[str] = mapped_column(String(32), default="estimated-words")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


def _chunk_text(chunk: Any) -> str:
    if chunk is None:
        return ""
    if isinstance(chunk, str):
        return chunk
    if isinstance(chunk, dict):
        return str(chunk.get("text") or "")
    return str(getattr(chunk, "text", "") or "")


def _chunk_output_tokens(chunk: Any) -> int | None:
    usage = None
    if isinstance(chunk, dict):
        usage = chunk.get("usage")
    else:
        usage = getattr(chunk, "usage", None)
    if usage is None:
        return None
    if isinstance(usage, dict):
        val = usage.get("output_tokens")
    else:
        val = getattr(usage, "output_tokens", None)
    return val if isinstance(val, int) else None


async def run_benchmark(
    stream: AsyncGenerator[Any, None],
) -> dict:
    """Consume a provider stream, measuring TTFT + tok/s honestly.

    TTFT = time from stream start to the first non-empty text chunk.
    Tokens = provider usage output_tokens when any chunk carries it
    (last value wins); otherwise word count of the collected text,
    labelled token_source='estimated-words'.
    """
    started = time.monotonic()
    ttft: float | None = None
    text_parts: list[str] = []
    usage_tokens: int | None = None
    async for chunk in stream:
        text = _chunk_text(chunk)
        if text and ttft is None:
            ttft = time.monotonic() - started
        text_parts.append(text)
        tok = _chunk_output_tokens(chunk)
        if tok is not None:
            usage_tokens = tok
    duration = time.monotonic() - started
    full_text = "".join(text_parts)
    if usage_tokens is not None:
        tokens, source = usage_tokens, "provider-usage"
    else:
        tokens, source = len(full_text.split()), "estimated-words"
    gen_time = max(duration - (ttft or 0.0), 1e-9)
    return {
        "ttft_s": round(ttft, 3) if ttft is not None else None,
        "tokens": tokens,
        "duration_s": round(duration, 3),
        "tok_per_s": round(tokens / gen_time, 2) if tokens else 0.0,
        "token_source": source,
        "token_source_note": (
            "provider usage" if source == "provider-usage"
            else "estimated from text, provider gave no usage"
        ),
    }
