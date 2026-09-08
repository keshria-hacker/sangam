"""
Live model discovery - fetches available models from provider APIs.
"""
import asyncio
import json
import logging
import re

import httpx

from .base import NON_CHAT_MARKERS, ModelInfo, ProviderConfig
from .inaccessible import is_inaccessible
from backend.response_events import ModelCapabilities

logger = logging.getLogger(__name__)


def _infer_capabilities(model_id: str, provider_id: str, entry: dict | None = None) -> ModelCapabilities:
    """Infer model capabilities from model ID/provider and optional raw entry data.

    This is a heuristic based on model naming conventions and known provider capabilities.
    For more accurate capabilities, providers should supply them directly in their model listing.
    """
    lower = model_id.lower()

    # Base capabilities from provider
    capabilities = ModelCapabilities(
        streaming=True,  # All supported providers stream
        tools=False,
        reasoning=False,
        vision=False,
        documents=False,
        citations=False,
        structured_output=False,
    )

    # Provider-specific heuristics
    if provider_id in {"openai", "anthropic", "gemini", "nvidia", "together", "groq", "openrouter", "deepseek", "mistral"}:
        # These providers generally support tools on most modern models
        capabilities.tools = True

        # Vision models (common naming patterns)
        if any(pattern in lower for pattern in ["vision", "gpt-4o", "claude-3", "gemini-1.5", "pixtral", "llava"]):
            capabilities.vision = True

        # Reasoning models
        if any(pattern in lower for pattern in ["o1", "o3", "r1", "reasoning", "qwq"]):
            capabilities.reasoning = True

        # Structured output (newer models)
        if any(pattern in lower for pattern in ["gpt-4o", "gpt-4.1", "claude-3.5", "gemini-1.5", "mistral-large"]):
            capabilities.structured_output = True

    elif provider_id == "ollama":
        # Ollama models - infer from name
        if any(pattern in lower for pattern in ["vision", "llava", "bakllava", "moondream", "pixtral"]):
            capabilities.vision = True
        if any(pattern in lower for pattern in ["hermes", "phi3", "nemotron", "qwen2.5", "llama3.1", "llama3.2", "command-r", "qwq"]):
            capabilities.tools = True
        if any(pattern in lower for pattern in ["r1", "qwq", "deepseek-r1"]):
            capabilities.reasoning = True

    # Check entry metadata for explicit capabilities
    if entry:
        # Some providers include capability fields
        if entry.get("supports_vision") or entry.get("vision"):
            capabilities.vision = True
        # Check for tools in various formats: boolean flags or capabilities array
        entry_tools = entry.get("tools") or entry.get("supports_tools") or entry.get("function_calling")
        entry_capabilities = entry.get("capabilities", [])
        if isinstance(entry_capabilities, list) and "tools" in entry_capabilities:
            entry_tools = True
        if entry_tools:
            capabilities.tools = True
        if entry.get("supports_reasoning") or entry.get("reasoning"):
            capabilities.reasoning = True
        # Check for reasoning in capabilities array
        entry_capabilities = entry.get("capabilities", [])
        if isinstance(entry_capabilities, list) and "reasoning" in entry_capabilities:
            capabilities.reasoning = True
        if entry.get("structured_output") or entry.get("json_mode"):
            capabilities.structured_output = True

    return capabilities


async def fetch_models_from_provider(
    api_key: str,
    config: ProviderConfig,
    timeout_seconds: float = 20.0,
) -> list[ModelInfo]:
    """Fetch all available models from a provider's model listing endpoint."""
    if not api_key:
        return []

    headers = {"Accept": "application/json"}
    if config.auth_type == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"
    elif config.auth_type == "header":
        headers[config.auth_header_name] = api_key
    if config.extra_headers:
        headers.update(config.extra_headers)

    is_query_auth = config.auth_type == "query"
    query_key_name = config.query_key if is_query_auth else None

    all_models: list[ModelInfo] = []
    seen_ids: set[str] = set()
    url = config.model_endpoint

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds / 2))
        ) as client:
            visited: set[str] = set()
            pages_fetched = 0
            max_pages = 10

            while url and url not in visited and pages_fetched < max_pages:
                visited.add(url)

                # Attach query auth (Gemini-style) per request
                request_url = url
                if is_query_auth and query_key_name:
                    sep = "&" if "?" in url else "?"
                    request_url = f"{url}{sep}{query_key_name}={api_key}"

                response = await client.get(request_url, headers=headers)
                response.raise_for_status()
                payload = response.json()

                for entry in payload.get(config.json_path, []) or []:
                    if not isinstance(entry, dict):
                        continue

                    raw_id = entry.get(config.id_field)
                    if not raw_id or not isinstance(raw_id, str):
                        continue

                    model_id = str(raw_id)
                    if config.strip_prefix and model_id.startswith(config.strip_prefix):
                        model_id = model_id[len(config.strip_prefix):]
                    if not model_id or model_id in seen_ids:
                        continue

                    # Filter non-chat models
                    lowered = model_id.lower()
                    if any(marker in lowered for marker in NON_CHAT_MARKERS):
                        continue

                    seen_ids.add(model_id)

                    # Derive name
                    name = _derive_name(model_id, entry, config)

                    # Extract description if available
                    description = ""
                    if config.description_field:
                        raw_desc = entry.get(config.description_field)
                        if raw_desc and isinstance(raw_desc, str):
                            description = raw_desc

                    # Build litellm_id with prefix
                    litellm_id = model_id
                    if config.litellm_prefix and not model_id.startswith(config.litellm_prefix):
                        litellm_id = f"{config.litellm_prefix}{model_id}"

                    # Skip if known inaccessible
                    if is_inaccessible(litellm_id):
                        continue

                    capabilities = _infer_capabilities(model_id, config.provider_id, entry)

                    all_models.append(ModelInfo(
                        id=f"{config.provider_id}::{litellm_id}",
                        name=name,
                        provider_id=config.provider_id,
                        provider_label=config.label,
                        litellm_id=litellm_id,
                        description=description,
                        model_id=model_id,
                        capabilities=capabilities,
                    ))

                # Follow pagination
                next_url = payload.get("next")
                if next_url and isinstance(next_url, str) and next_url not in visited:
                    url = next_url
                else:
                    url = None

    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        # Return whatever we collected before the failure
        logger.warning(
            "fetch_models_from_provider(%s) failed at %s (collected %d models): %s",
            config.provider_id,
            url,
            len(all_models),
            exc,
            exc_info=True,
        )

    return all_models


def _derive_name(model_id: str, entry: dict, config: ProviderConfig) -> str:
    """Derive a human-readable name from the model entry."""
    if config.name_field:
        raw_name = entry.get(config.name_field)
        if raw_name and isinstance(raw_name, str):
            return raw_name
    # Fallback: last segment after /
    return model_id.rsplit("/", maxsplit=1)[-1] if "/" in model_id else model_id


async def _ollama_reachable(base_url: str = "http://localhost:11434") -> bool:
    """Check if Ollama server is reachable."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{base_url.rstrip('/')}/api/tags")
            return response.status_code == 200
    except httpx.HTTPError:
        return False


async def fetch_ollama_models(base_url: str = "http://localhost:11434") -> list[ModelInfo]:
    """Fetch models from local Ollama server."""
    endpoint = f"{base_url.rstrip('/')}/api/tags"
    models: list[ModelInfo] = []

    async def _fetch_and_process() -> list[ModelInfo]:
        async with httpx.AsyncClient(timeout=2.5) as client:
            response = await client.get(endpoint)
            response.raise_for_status()
            result: list[ModelInfo] = []
            for item in response.json().get("models", []):
                if isinstance(item.get("name"), str) and item["name"]:
                    name = item["name"]
                    capabilities = _infer_capabilities(name, "ollama", item)
                    litellm_id = f"ollama/{name}"
                    result.append(ModelInfo(
                        id=f"ollama::{litellm_id}",
                        name=name,
                        provider_id="ollama",
                        provider_label="Ollama",
                        litellm_id=litellm_id,
                        capabilities=capabilities,
                    ))
            return result

    # Try direct connection first
    try:
        return await _fetch_and_process()
    except httpx.HTTPError as exc:
        logger.debug("Ollama not reachable at %s (%s); attempting auto-start", endpoint, exc)

    # Auto-start Ollama and retry with backoff
    from .ollama import _try_start_ollama as _async_ollama_start
    await _async_ollama_start()

    backoff_delays = [1.0, 2.0, 3.0, 5.0]
    for delay in backoff_delays:
        await asyncio.sleep(delay)
        try:
            return await _fetch_and_process()
        except httpx.HTTPError as exc:
            logger.debug("Ollama retry failed (delay=%ss): %s", delay, exc)
            continue

    if not models:
        logger.warning(
            "Ollama unreachable at %s after %d retries; returning empty model list",
            endpoint,
            len(backoff_delays),
        )

    return models


# Re-export Ollama process management from ollama.py (single source of truth)
from .ollama import _ollama_start_attempted, _ollama_process, _cleanup_ollama as cleanup_ollama  # noqa: F401