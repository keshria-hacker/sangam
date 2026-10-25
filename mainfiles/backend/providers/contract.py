"""
backend/providers/contract.py — provider adapter contract enforcement,
per-provider/per-model capability registry, pre-flight warnings, and
cost-ranked routing (spec/a6-studio-skills, Cluster A).

This module does NOT invent capabilities. The registry is built from:
  * backend/providers/compat.py PROVIDERS (11 providers, incl. OmniRoute)
    + CURATED_MODELS (per-model capability flags), and
  * backend/providers/registry.py static configs (providers with no
    curated model get capabilities_known=False, never guessed flags).

Pre-flight: preflight(provider, model, wanted) returns a plain warning
for every wanted capability the model is known NOT to support, phrased
as "this model can't do X", plus capabilities_known=False when the
model is not in the registry at all (caller must not claim support).

Cost-ranked routing extends (never forks) fallback_chain: candidates
with a known price sort cheapest-first; unknown-price candidates sort
last with cost_known=False, so an unknown price is never presented
as cheap.
"""
from __future__ import annotations

from typing import Any

CAPABILITY_NAMES = (
    "streaming",
    "tools",
    "reasoning",
    "vision",
    "documents",
    "citations",
    "structured_output",
)

# Friendly wording for the pre-flight warning surfaced to the caller/UI.
_CAPABILITY_LABELS = {
    "streaming": "streaming responses",
    "tools": "tool calls",
    "reasoning": "reasoning output",
    "vision": "vision (image input)",
    "documents": "document input",
    "citations": "citations",
    "structured_output": "structured output",
}


def _curated_registry() -> dict[str, dict]:
    """Per-provider registry rows from the curated catalog."""
    from .compat import CURATED_MODELS, PROVIDERS

    rows: dict[str, dict] = {}
    for pid, meta in PROVIDERS.items():
        rows[pid] = {
            "provider_id": pid,
            "label": meta["label"],
            "local": meta["local"],
            "models": [],
        }
    for model in CURATED_MODELS.values():
        row = rows.setdefault(model.provider_id, {
            "provider_id": model.provider_id,
            "label": model.provider_label,
            "local": False,
            "models": [],
        })
        caps = model.capabilities
        row["models"].append({
            "id": model.id,
            "name": model.name,
            "litellm_id": model.litellm_id,
            "capabilities": (
                {name: bool(getattr(caps, name, False)) for name in CAPABILITY_NAMES}
                if caps is not None else None
            ),
            "capabilities_known": caps is not None,
        })
    return rows


def capability_registry() -> dict:
    """Full per-provider/per-model registry (no network, no guessing)."""
    from .registry import _STATIC_PROVIDER_CONFIGS, init_provider_registry, registry

    init_provider_registry()

    rows = _curated_registry()
    # Every statically registered provider must appear, even with no
    # curated model — with capabilities_known=False, not invented flags.
    for config in _STATIC_PROVIDER_CONFIGS:
        rows.setdefault(config.provider_id, {
            "provider_id": config.provider_id,
            "label": config.label,
            "local": config.local,
            "models": [],
        })
    registered = set(registry.all_provider_ids())
    providers = []
    for pid in sorted(rows):
        row = rows[pid]
        row = dict(row)
        row["registered"] = pid in registered
        providers.append(row)
    return {"providers": providers, "capability_names": list(CAPABILITY_NAMES)}


def _find_model(provider_id: str, model_id: str) -> dict | None:
    rows = _curated_registry()
    row = rows.get(provider_id)
    if not row:
        return None
    for model in row["models"]:
        if model["id"] == model_id or model.get("litellm_id") == model_id:
            return model
    return None


def preflight(provider_id: str, model_id: str, wanted: list[str]) -> dict:
    """Pre-flight check: which wanted capabilities this model can't do.

    wanted entries must be capability names; unknown names are reported
    as unknown_wanted (never silently dropped or treated as supported).
    """
    unknown_wanted = [w for w in wanted if w not in CAPABILITY_NAMES]
    known_wanted = [w for w in wanted if w in CAPABILITY_NAMES]
    model = _find_model(provider_id, model_id)
    if model is None:
        return {
            "provider_id": provider_id,
            "model_id": model_id,
            "capabilities": None,
            "capabilities_known": False,
            "warnings": [
                f"Capabilities for model {model_id!r} are not in the registry: "
                "support for the requested capabilities is unknown — "
                "do not assume this model can do them."
            ],
            "blocked": [],
            "unknown_wanted": unknown_wanted,
        }
    caps = model["capabilities"] or {}
    warnings = []
    blocked = []
    for want in known_wanted:
        if not caps.get(want):
            label = _CAPABILITY_LABELS.get(want, want)
            warnings.append(f"This model can't do {label} ({want}).")
            blocked.append(want)
    return {
        "provider_id": provider_id,
        "model_id": model_id,
        "capabilities": caps,
        "capabilities_known": True,
        "warnings": warnings,
        "blocked": blocked,
        "unknown_wanted": unknown_wanted,
    }


def cost_ranked_route(candidates: list[dict]) -> list[dict]:
    """Rank fallback candidates cheapest-first (extends fallback_chain).

    Each candidate: {provider, model, price_per_1k_usd?}. Unknown price
    sorts last with cost_known=False. Ties keep input order (stable).
    """
    ranked = []
    for cand in candidates:
        price = cand.get("price_per_1k_usd")
        known = isinstance(price, (int, float)) and price >= 0
        ranked.append({
            "provider": cand.get("provider"),
            "model": cand.get("model"),
            "price_per_1k_usd": price if known else None,
            "cost_known": known,
        })
    ranked.sort(key=lambda r: (not r["cost_known"], r["price_per_1k_usd"] if r["cost_known"] else 0))
    return ranked


def check_adapters() -> dict:
    """Verify every registered provider class honors the adapter contract.

    Contract methods: capabilities(), stream(), tools(), reasoning(),
    citations(), normalize_error() + stream_completion(). A method
    counts as honored when the class (or BaseProvider) defines it;
    BaseProvider supplies safe defaults, so a missing override is a
    report row, not a crash — the registry never claims an override
    that does not exist.
    """
    from .registry import init_provider_registry, registry

    init_provider_registry()
    # Provider classes register through the package's lazy init
    # (backend.providers._ensure_initialized); without it the registry
    # holds configs only and every class row would read None.
    try:
        from . import _ensure_initialized

        _ensure_initialized()
    except Exception:  # noqa: BLE001 — static rows are still reported
        pass
    methods = ("capabilities", "stream", "tools", "reasoning", "citations",
               "normalize_error", "stream_completion")
    rows = []
    for pid in sorted(registry.all_provider_ids()):
        cls = registry.get_provider_class(pid)
        if cls is None:
            # OpenAI-compatible providers share a class registered under
            # their own id only when their module imported; unregistered
            # classes are reported, not hidden.
            rows.append({"provider_id": pid, "class": None,
                         "methods": {m: False for m in methods},
                         "contract_ok": False,
                         "note": "No provider class registered"})
            continue
        found = {method: hasattr(cls, method) for method in methods}
        rows.append({
            "provider_id": pid,
            "class": cls.__name__,
            "methods": found,
            "contract_ok": all(found.values()),
            "note": "",
        })
    return {"adapters": rows, "contract_methods": list(methods)}
