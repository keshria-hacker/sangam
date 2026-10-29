"""Model pricing from LiteLLM's bundled cost table.

Sangam's agent CostMeter previously needed an explicit
``price_per_1k_usd`` to report any cost at all, and no production
caller passed one — so a saved agent ``cost_budget`` could never be
enforced and every run reported ``cost_known: False``. This module
derives per-token input/output prices from the model LiteLLM already
knows, offline, with no network call and no fabricated fallback:

- Lookup order: the id as given, then the id with a provider prefix
  stripped (``openai/gpt-4o-mini`` -> ``gpt-4o-mini``), because
  LiteLLM's table is keyed mostly by bare model names.
- Any failure (LiteLLM missing, model absent, price fields absent or
  non-numeric) returns ``None``: an unknown price stays unknown, it
  is never replaced with a made-up rate.
"""
from __future__ import annotations


def model_prices(litellm_model_id: str | None) -> tuple[float, float] | None:
    """Return (input_cost_per_token, output_cost_per_token) or None."""
    if not litellm_model_id or not isinstance(litellm_model_id, str):
        return None
    try:
        import litellm

        table = litellm.model_cost
    except Exception:  # noqa: BLE001 — pricing is best-effort, never fatal
        return None
    if not isinstance(table, dict):
        return None
    candidates = [litellm_model_id]
    if "/" in litellm_model_id:
        candidates.append(litellm_model_id.split("/", 1)[1])
    for candidate in candidates:
        entry = table.get(candidate)
        if not isinstance(entry, dict):
            continue
        try:
            input_price = float(entry["input_cost_per_token"])
            output_price = float(entry["output_cost_per_token"])
        except (KeyError, TypeError, ValueError):
            continue
        if input_price < 0 or output_price < 0:
            continue
        return (input_price, output_price)
    return None
