"""
llm.py - Unified LLM Provider Facade (v2: Modular Architecture)

This module acts as a backward-compatible facade over the new modular provider system
in backend/providers/. It re-exports all the key functions and types so existing
code (api.py, main.py, etc.) continues to work without changes.
"""
from collections.abc import AsyncGenerator
from typing import Any

# Core provider facade - all main API functions
from backend.providers import (
    CURATED_MODELS,
    MODELS,
    PROVIDERS,
    ModelInfo,
    ProviderConfig,
    _inaccessible_models,
    clear_inaccessible_models,
    default_model_id,
    get_db_keys,
    list_models,
    list_provider_status,
    list_providers_static,
    registry,
    resolve_api_key,
)
# Enhanced provider routing functions - drop-in replacements for the originals
from backend.providers.enhanced.integration import (
    stream_completion,
    stream_response_events,
)

from backend.providers.base import ProviderStreamChunk

# Backward compatibility - model discovery functions
from backend.providers.model_discovery import (
    cleanup_ollama,
    fetch_models_from_provider,
    fetch_ollama_models,
)

# Backward compatibility: export the internal set directly
# (used by some code that checks _inaccessible_models.add())
inaccessible_models = _inaccessible_models


# Backward-compatible Ollama functions
async def list_ollama_models(base_url: str = "http://localhost:11434") -> list[ModelInfo]:
    """Return models from local Ollama server (backward-compatible wrapper)."""
    from backend.providers.model_discovery import fetch_ollama_models
    return await fetch_ollama_models(base_url)


async def _try_start_ollama() -> None:
    """Attempt to start Ollama server (backward-compatible wrapper)."""
    # This wrapper exists so tests can patch llm._try_start_ollama
    from backend.providers.ollama import _try_start_ollama as _real_try_start_ollama
    await _real_try_start_ollama()


# For backward compatibility with code that imports these directly
# from llm import PROVIDERS, CURATED_MODELS, etc.
# These are already imported above and available in module namespace

# Re-export private attributes for tests
_providers_static = None


def _model_id_for(provider: str, litellm_id: str) -> str:
    """Generate internal model ID from provider and litellm_id."""
    return f"{provider}::{litellm_id}"


def _resolve_model(model_id: str) -> ModelInfo:
    """Resolve a model ID string to ModelInfo."""
    # Handle ollama:model format
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
        # Try to find in CURATED_MODELS
        for m in CURATED_MODELS.values():
            if m.litellm_id == litellm_id:
                return m
        # Fallback: create basic ModelInfo
        return ModelInfo(
            id=model_id,
            name=litellm_id.split("/")[-1],
            provider_id=provider,
            provider_label=PROVIDERS.get(provider, {}).get("label", provider),
            litellm_id=litellm_id,
        )
    return None


def __getattr__(name):
    """Lazy load provider configs for backward compatibility."""
    global _providers_static
    if name == "_providers_static":
        from backend.providers import list_providers_static
        _providers_static = list_providers_static()
        return _providers_static
    if name == "_ollama_start_attempted":
        from backend.providers.model_discovery import _ollama_start_attempted
        return _ollama_start_attempted
    if name == "_ollama_process":
        from backend.providers.model_discovery import _ollama_process
        return _ollama_process
    raise AttributeError(f"module 'llm' has no attribute '{name}'")
async def list_models(db: Any) -> list[ModelInfo]:
    """Return all selectable models from all linked providers."""
    from backend.providers import list_models as _list_models
    return await _list_models(db)


async def list_provider_status(db: Any) -> list[dict[str, Any]]:
    """Return providers currently reachable with valid keys."""
    from backend.providers import list_provider_status as _list_provider_status
    return await _list_provider_status(db)


async def default_model_id(db: Any) -> str | None:
    """Pick first available model (prefers Ollama)."""
    from backend.providers import default_model_id as _default_model_id
    return await _default_model_id(db)


async def stream_completion(  # noqa: PLR0917
    model_id: str,
    messages: list[dict],
    db: Any,
    temperature: float = 0.7,
    max_tokens: int = None,
    reasoning_effort: str = None,
) -> AsyncGenerator[str | ProviderStreamChunk]:
    """Stream completion from the appropriate provider."""
    # Note: The enhanced version is now imported above and overrides this.
    # This docstring is kept for backward compatibility.
    from backend.providers import stream_completion as _stream_completion
    async for chunk in _stream_completion(
        model_id, messages, db, temperature, max_tokens, reasoning_effort
    ):
        yield chunk


async def stream_response_events(  # noqa: PLR0917
    model_id: str,
    messages: list[dict],
    db: Any,
    temperature: float = 0.7,
    max_tokens: int = None,
    reasoning_effort: str = None,
    message_id: str = None,
    request_id: str = None,
) -> AsyncGenerator[Any]:
    """Stream canonical Sangam response events from providers."""
    # Note: The enhanced version is now imported above and overrides this.
    # This docstring is kept for backward compatibility.
    from backend.providers import stream_response_events as _stream_response_events
    async for event in _stream_response_events(
        model_id, messages, db, temperature, max_tokens, reasoning_effort, message_id, request_id
    ):
        yield event


async def get_db_keys(db: Any) -> dict[str, str]:
    """Fetch all stored provider keys from the database."""
    from backend.providers import get_db_keys as _get_db_keys
    return await _get_db_keys(db)


async def resolve_api_key(provider_id: str, db: Any) -> str | None:
    """Resolve API key for a provider: DB first, then env."""
    from backend.providers import resolve_api_key as _resolve_api_key
    return await _resolve_api_key(provider_id, db)


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

    # Reuse patterns from providers.base
    patterns = [
        re.compile(r'sk-[a-zA-Z0-9-_]{20,}'),
        re.compile(r'sk-ant-[a-zA-Z0-9-_]{20,}'),
        re.compile(r'AIza[a-zA-Z0-9-_]{35}'),
        re.compile(r'nvapi-[a-zA-Z0-9-_]{20,}'),
        re.compile(r'tgp_v1_[a-zA-Z0-9-_]{20,}'),
        re.compile(r'gsk_[a-zA-Z0-9-_]{20,}'),
        re.compile(r'sk-or-v1-[a-zA-Z0-9-_]{20,}'),
        re.compile(r'[A-Za-z0-9+/]{40,}={0,2}'),
        re.compile(r'[a-fA-F0-9]{40,}'),
        re.compile(r'Bearer\\s+[a-zA-Z0-9\\-_=]{20,}'),
    ]
    for pattern in patterns:
        msg = pattern.sub('***REDACTED***', msg)
    return msg


def _cleanup_ollama() -> None:
    """Cleanup auto-started Ollama process on shutdown."""
    from backend.providers import cleanup_ollama
    cleanup_ollama()


# Backward-compatible wrapper for old fetch_models_from_provider API
# ============================================================

async def fetch_models_from_provider(  # noqa: PLR0917
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
    """
    Backward-compatible wrapper for the old fetch_models_from_provider API.

    This function translates the old flat parameter API to the new ProviderConfig
    and fetch_models_from_provider pattern. It's kept for backward compatibility
    with existing tests and code.
    """
    from backend.providers.base import ProviderConfig
    from backend.providers.model_discovery import fetch_models_from_provider as new_fetch_models

    # Build a ProviderConfig from the old parameters
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

    # Call the new function
    models = await new_fetch_models(api_key, config)

    # Convert ModelInfo objects to dicts matching the old API format
    # The old API returned the raw model_id (after strip_prefix) as "id"
    # and the full litellm_id with prefix as "litellm_id"
    result = []
    seen_ids = set()
    for m in models:
        # Use the raw model_id stored in ModelInfo
        raw_id = m.model_id if m.model_id else (m.litellm_id or m.id)

        # Deduplicate by raw_id (tests expect this)
        if raw_id in seen_ids:
            continue
        seen_ids.add(raw_id)

        model_dict = {
            "id": raw_id,
            "name": m.name,
            "provider": provider_id,
            "provider_label": provider_label,
            "description": m.description or "",
            "litellm_id": m.litellm_id,
        }
        result.append(model_dict)

    return result


async def _fetch_provider_models(provider_id: str, api_key: str) -> list[str]:
    """
    Backward-compatible wrapper for the old _fetch_provider_models function.

    Returns a list of LiteLLM model IDs (with prefix) for the given provider.
    """
    from backend.providers import list_providers_static
    from backend.providers.base import ProviderConfig
    from backend.providers.model_discovery import fetch_models_from_provider as new_fetch_models

    # Build config from static registry
    static = list_providers_static()
    if provider_id not in static:
        return []

    # Map provider_id to config
    provider_configs = {
        "openai": ProviderConfig(
            provider_id="openai",
            label="OpenAI",
            local=False,
            env_key_name="OPENAI_API_KEY",
            api_base="https://api.openai.com/v1",
            model_endpoint="https://api.openai.com/v1/models",
            auth_type="bearer",
            json_path="data",
            id_field="id",
            litellm_prefix="openai/",
        ),
        "gemini": ProviderConfig(
            provider_id="gemini",
            label="Gemini",
            local=False,
            env_key_name="GEMINI_API_KEY",
            api_base="https://generativelanguage.googleapis.com/v1beta",
            model_endpoint="https://generativelanguage.googleapis.com/v1beta/models",
            auth_type="query",
            query_key="key",
            json_path="models",
            id_field="name",
            strip_prefix="models/",
            litellm_prefix="gemini/",
        ),
        "nvidia": ProviderConfig(
            provider_id="nvidia",
            label="NVIDIA NIM",
            local=False,
            env_key_name="NVIDIA_NIM_API_KEY",
            api_base="https://integrate.api.nvidia.com/v1",
            model_endpoint="https://integrate.api.nvidia.com/v1/models",
            auth_type="bearer",
            json_path="data",
            id_field="id",
            litellm_prefix="nvidia_nim/",
        ),
    }

    config = provider_configs.get(provider_id)
    if not config:
        return []

    try:
        models = await new_fetch_models(api_key, config)
        # Deduplicate by litellm_id (tests expect prefix deduplication)
        seen = set()
        result = []
        for m in models:
            if m.litellm_id and m.litellm_id not in seen:
                seen.add(m.litellm_id)
                result.append(m.litellm_id)
    except Exception:
        return []
    else:
        return result


# For backward compatibility with code that imports these directly
# from llm import PROVIDERS, CURATED_MODELS, etc.
# These are already imported above and available in module namespace

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
    # Legacy compatibility
    "CURATED_MODELS",
    "MODELS",
    "PROVIDERS",
    "_inaccessible_models",
    "inaccessible_models",
    # Backward-compatible model discovery
    "fetch_models_from_provider",
    "fetch_ollama_models",
    "cleanup_ollama",
    "_fetch_provider_models",
    # Utilities
    "sanitize_error",
    "_cleanup_ollama",
    "_linked_providers",
]