"""
llm.py — Unified LLM provider facade.

This module is the stable import surface over ``backend/providers/``. App code
(api.py, summarizer.py, skills/) and tests import from here instead of reaching
into provider internals, so the provider implementation can evolve freely.

The async API functions resolve their implementation from the providers package
at call time, so patching either ``backend.llm.<name>`` or
``backend.providers.<name>`` works in tests.
"""
from collections.abc import AsyncGenerator
from typing import Any

# --- Re-exported types and values (single source of truth: backend/providers) ---
from .providers import (
    CURATED_MODELS,
    MODELS,
    PROVIDERS,
    ModelInfo,
    ProviderConfig,
    _inaccessible_models,
    clear_inaccessible_models,
    list_providers_static,
    registry,
)
from .providers.base import ProviderStreamChunk
from .providers.model_discovery import (
    cleanup_ollama,
    fetch_ollama_models,
)

# Backward compatibility: some code mutates this set directly via
# ``llm.inaccessible_models.add(...)``.
inaccessible_models = _inaccessible_models

# Lazily-populated cache for the ``_providers_static`` module attribute
# (see ``__getattr__``).
_providers_static: dict[str, dict] | None = None


# ---------------------------------------------------------------------------
# Model ID helpers
# ---------------------------------------------------------------------------

def _model_id_for(provider: str, litellm_id: str) -> str:
    """Generate the internal model ID from provider and litellm_id."""
    return f"{provider}::{litellm_id}"


def _resolve_model(model_id: str) -> ModelInfo | None:
    """Resolve a model ID string to a ModelInfo (None for unknown formats)."""
    # Handle ollama:<model> format
    if model_id.startswith("ollama:"):
        model_name = model_id.split(":", 1)[1]
        return ModelInfo(
            id=f"ollama::{model_name}",
            name=model_name,
            provider_id="ollama",
            provider_label="Ollama",
            litellm_id=f"ollama/{model_name}",
        )
    # Handle provider::litellm_id format
    if "::" in model_id:
        provider, litellm_id = model_id.split("::", 1)
        # Prefer a curated entry when one matches
        for m in CURATED_MODELS.values():
            if m.litellm_id == litellm_id:
                return m
        # Fallback: build a basic ModelInfo on the fly
        return ModelInfo(
            id=model_id,
            name=litellm_id.split("/")[-1],
            provider_id=provider,
            provider_label=PROVIDERS.get(provider, {}).get("label", provider),
            litellm_id=litellm_id,
        )
    return None


# ---------------------------------------------------------------------------
# Key / provider helpers
# ---------------------------------------------------------------------------

def _linked_providers(keys: dict[str, str]) -> set[str]:
    """Provider ids (cloud only) that have a key available at runtime."""
    linked: set[str] = set()
    for pid, meta in PROVIDERS.items():
        if meta.get("local", False):
            continue
        if keys.get(pid) or meta.get("env_key"):
            linked.add(pid)
    return linked


def sanitize_error(msg: str) -> str:
    """Strip potential API key values from error messages before logging."""
    import re

    patterns = [
        re.compile(r"sk-[a-zA-Z0-9-_]{20,}"),
        re.compile(r"sk-ant-[a-zA-Z0-9-_]{20,}"),
        re.compile(r"AIza[a-zA-Z0-9-_]{35}"),
        re.compile(r"nvapi-[a-zA-Z0-9-_]{20,}"),
        re.compile(r"tgp_v1_[a-zA-Z0-9-_]{20,}"),
        re.compile(r"gsk_[a-zA-Z0-9-_]{20,}"),
        re.compile(r"sk-or-v1-[a-zA-Z0-9-_]{20,}"),
        re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),
        re.compile(r"[a-fA-F0-9]{40,}"),
        re.compile(r"Bearer\\s+[a-zA-Z0-9\\-_=]{20,}"),
    ]
    for pattern in patterns:
        msg = pattern.sub("***REDACTED***", msg)
    return msg


# ---------------------------------------------------------------------------
# Async API — delegated to the providers package at call time
# ---------------------------------------------------------------------------

async def list_models(db: Any) -> list[ModelInfo]:
    """Return all selectable models from all linked providers."""
    from . import providers
    return await providers.list_models(db)


async def list_provider_status(db: Any) -> list[dict[str, Any]]:
    """Return providers currently reachable with valid keys."""
    from . import providers
    return await providers.list_provider_status(db)


async def default_model_id(db: Any) -> str | None:
    """Pick first available model (prefers Ollama)."""
    from . import providers
    return await providers.default_model_id(db)


async def get_db_keys(db: Any) -> dict[str, str]:
    """Fetch all stored provider keys from the database."""
    from . import providers
    return await providers.get_db_keys(db)


async def resolve_api_key(provider_id: str, db: Any) -> str | None:
    """Resolve API key for a provider: DB first, then env."""
    from . import providers
    return await providers.resolve_api_key(provider_id, db)


async def stream_completion(  # noqa: PLR0913
    model_id: str,
    messages: list[dict],
    db: Any,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> AsyncGenerator[str | ProviderStreamChunk]:
    """Stream completion from the appropriate provider.

    Phase 7: wrapped with the fallback chain's circuit breaker + quota.
    Records success/failure so the UI can show provider health.
    """
    from . import providers
    from .providers.fallback_chain import get_fallback_chain

    # Resolve provider_id from model_id for circuit breaker tracking
    provider_id = None
    try:
        info = _resolve_model(model_id)
        provider_id = info.provider_id if info else None
    except Exception:
        pass

    chain = get_fallback_chain()
    if provider_id:
        # Quota + circuit breaker guard (raises if open/exceeded)
        quota = chain.quotas.get(provider_id)
        if quota:
            ok, reason = quota.check()
            if not ok:
                raise RuntimeError(f"Provider {provider_id}: {reason}")
        breaker = chain.breakers.get(provider_id)
        try:
            await breaker.guard()
        except Exception:
            # Circuit open — record and re-raise so caller sees the real error
            raise

    try:
        async for chunk in providers.stream_completion(
            model_id, messages, db, temperature, max_tokens, reasoning_effort
        ):
            yield chunk
        # Success: record it
        if provider_id:
            await chain.breakers.get(provider_id).record_success()
            if provider_id in chain.quotas:
                chain.quotas[provider_id].record()
    except Exception:
        # Failure: trip the breaker
        if provider_id:
            try:
                await chain.breakers.get(provider_id).record_failure()
            except Exception:
                pass
        raise


async def stream_response_events(  # noqa: PLR0913
    model_id: str,
    messages: list[dict],
    db: Any,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
    message_id: str | None = None,
    request_id: str | None = None,
) -> AsyncGenerator[Any]:
    """Stream canonical Sangam response events from providers.

    Phase 8 (D6): wrapped with the fallback chain's circuit breaker + quota,
    same as stream_completion. This is the chat request path, so provider
    health now reflects real chat traffic.
    """
    from . import providers
    from .providers.fallback_chain import get_fallback_chain

    provider_id = None
    try:
        info = _resolve_model(model_id)
        provider_id = info.provider_id if info else None
    except Exception:
        pass

    chain = get_fallback_chain()
    if provider_id:
        quota = chain.quotas.get(provider_id)
        if quota:
            ok, reason = quota.check()
            if not ok:
                raise RuntimeError(f"Provider {provider_id}: {reason}")
        breaker = chain.breakers.get(provider_id)
        try:
            await breaker.guard()
        except Exception:
            raise

    try:
        async for event in providers.stream_response_events(
            model_id, messages, db, temperature, max_tokens, reasoning_effort,
            message_id, request_id,
        ):
            yield event
        if provider_id:
            await chain.breakers.get(provider_id).record_success()
            if provider_id in chain.quotas:
                chain.quotas[provider_id].record()
    except Exception:
        if provider_id:
            try:
                await chain.breakers.get(provider_id).record_failure()
            except Exception:
                pass
        raise


# ---------------------------------------------------------------------------
# Ollama lifecycle
# ---------------------------------------------------------------------------

async def list_ollama_models(base_url: str = "http://localhost:11434") -> list[ModelInfo]:
    """Return models from the local Ollama server."""
    from .providers import model_discovery
    return await model_discovery.fetch_ollama_models(base_url)


async def _try_start_ollama() -> None:
    """Attempt to start the Ollama server (kept so tests can patch it here)."""
    from .providers.ollama import _try_start_ollama as _real_try_start_ollama
    await _real_try_start_ollama()


def _cleanup_ollama() -> None:
    """Clean up an auto-started Ollama process on shutdown."""
    from . import providers
    providers.cleanup_ollama()


def __getattr__(name: str) -> Any:
    """Lazy attributes for backward compatibility (tests inspect these)."""
    global _providers_static
    if name == "_providers_static":
        if globals().get("_providers_static") is None:
            from . import providers
            _providers_static = providers.list_providers_static()
        return _providers_static
    if name == "_ollama_start_attempted":
        from .providers.model_discovery import _ollama_start_attempted
        return _ollama_start_attempted
    if name == "_ollama_process":
        from .providers.model_discovery import _ollama_process
        return _ollama_process
    raise AttributeError(f"module 'llm' has no attribute '{name}'")


# ---------------------------------------------------------------------------
# Backward-compatible model-fetch wrappers (old flat-parameter API)
# ---------------------------------------------------------------------------

async def fetch_models_from_provider(  # noqa: PLR0913 — legacy signature
    api_key: str,
    endpoint_url: str,
    provider_id: str,
    provider_label: str,
    auth_type: str = "bearer",
    auth_header_name: str | None = None,
    extra_headers: dict[str, str] | None = None,
    query_key: str | None = None,
    json_path: str = "data",
    id_field: str = "id",
    strip_prefix: str = "",
    name_field: str | None = None,
    description_field: str | None = None,
    timeout_seconds: float = 10.0,
) -> list[dict]:
    """Translate the legacy flat-parameter API onto ProviderConfig-based fetch.

    Returns plain dicts (id/name/provider/litellm_id/...) as before, with
    duplicate raw ids removed.
    """
    from .providers.model_discovery import fetch_models_from_provider as new_fetch_models

    config = ProviderConfig(
        provider_id=provider_id,
        label=provider_label,
        local=False,
        env_key_name=None,
        api_base=endpoint_url,
        model_endpoint=endpoint_url,
        auth_type=auth_type,
        auth_header_name=auth_header_name or "Authorization",
        extra_headers=extra_headers,
        json_path=json_path,
        id_field=id_field,
        strip_prefix=strip_prefix,
        litellm_prefix=f"{provider_id}/",
        name_field=name_field,
        description_field=description_field,
        query_key=query_key,
    )

    models = await new_fetch_models(api_key, config, timeout_seconds=timeout_seconds)

    result = []
    seen_ids: set[str] = set()
    for m in models:
        raw_id = m.model_id if m.model_id else (m.litellm_id or m.id)
        if raw_id in seen_ids:
            continue
        seen_ids.add(raw_id)
        result.append({
            "id": raw_id,
            "name": m.name,
            "provider": provider_id,
            "provider_label": provider_label,
            "description": m.description or "",
            "litellm_id": m.litellm_id,
        })
    return result


async def _fetch_provider_models(provider_id: str, api_key: str) -> list[str]:
    """Return LiteLLM-prefixed model IDs for a provider (legacy API).

    Uses the static provider registry to build the fetch config. Unknown or
    local providers and any fetch failure return an empty list.
    """
    from .providers.model_discovery import fetch_models_from_provider as new_fetch_models

    static = list_providers_static()
    if provider_id not in static:
        return []

    config = registry.get_config(provider_id)
    if config is None or config.local:
        return []

    try:
        models = await new_fetch_models(api_key, config)
    except Exception:  # noqa: BLE001 — callers treat failures as "no models"
        return []

    seen: set[str] = set()
    result = []
    for m in models:
        if m.litellm_id and m.litellm_id not in seen:
            seen.add(m.litellm_id)
            result.append(m.litellm_id)
    return result


__all__ = [
    # Main async API
    "list_models",
    "list_provider_status",
    "default_model_id",
    "stream_completion",
    "stream_response_events",
    "get_db_keys",
    "resolve_api_key",
    "list_providers_static",
    "clear_inaccessible_models",
    # Provider registry
    "registry",
    # Types
    "ModelInfo",
    "ProviderConfig",
    "ProviderStreamChunk",
    # Legacy compatibility
    "CURATED_MODELS",
    "MODELS",
    "PROVIDERS",
    "_inaccessible_models",
    "inaccessible_models",
    # Model discovery
    "fetch_models_from_provider",
    "fetch_ollama_models",
    "cleanup_ollama",
    "_fetch_provider_models",
    # Utilities
    "sanitize_error",
    "_cleanup_ollama",
    "_linked_providers",
]
