"""
Universal AI Provider System - Public Facade

This module provides the main public API for the provider system.
All external code should import from here, not from individual modules.
"""
from collections.abc import AsyncGenerator
from typing import Any

# Import provider implementations to register them
from . import (
    anthropic,  # noqa: F401
    gemini,  # noqa: F401
    litellm_fallback,  # noqa: F401
    nvidia,  # noqa: F401
    ollama,  # noqa: F401
    openai_compatible,  # noqa: F401
)
from .base import ModelInfo, ProviderConfig
from .inaccessible import (
    clear_inaccessible,
)
from .key_resolver import get_db_keys, get_static_env_key, list_linked_providers, resolve_api_key
from .model_discovery import (
    cleanup_ollama,
    fetch_models_from_provider,
    fetch_ollama_models,
)
from .registry import init_provider_registry, registry
from ..tools import (
    ToolCall,
    ToolResult,
    executor,
    registry as tool_registry,
)
from ..response_events import (
    FinishReason,
    ResponseEvent,
    ResponseEventBuilder,
    ResponseEventType,
    normalize_error,
)

# Initialize registry on import
_init_done = False


def _ensure_initialized() -> None:
    """Lazy initialization of provider registry."""
    global _init_done
    if not _init_done:
        init_provider_registry()
        # Register custom provider classes
        from .anthropic import AnthropicProvider
        from .gemini import GeminiProvider
        from .nvidia import NVIDIAProvider
        from .ollama import OllamaProvider
        from .openai_compatible import (
            DeepSeekProvider,
            GroqProvider,
            MistralProvider,
            OmniRouteProvider,
            OpenAIProvider,
            OpenRouterProvider,
            TogetherProvider,
        )

        registry.register(
            ProviderConfig(
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
            OpenAIProvider
        )
        registry.register(
            ProviderConfig(
                provider_id="anthropic",
                label="Anthropic",
                local=False,
                env_key_name="ANTHROPIC_API_KEY",
                api_base="https://api.anthropic.com/v1",
                model_endpoint="https://api.anthropic.com/v1/models",
                auth_type="header",
                auth_header_name="x-api-key",
                extra_headers={"anthropic-version": "2023-06-01"},
                json_path="data",
                id_field="id",
                litellm_prefix="anthropic/",
            ),
            AnthropicProvider
        )
        registry.register(
            ProviderConfig(
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
            NVIDIAProvider
        )
        registry.register(
            ProviderConfig(
                provider_id="together",
                label="Together AI",
                local=False,
                env_key_name="TOGETHER_API_KEY",
                api_base="https://api.together.xyz/v1",
                model_endpoint="https://api.together.xyz/v1/models",
                auth_type="bearer",
                json_path="data",
                id_field="id",
                litellm_prefix="together_ai/",
            ),
            TogetherProvider
        )
        registry.register(
            ProviderConfig(
                provider_id="groq",
                label="Groq",
                local=False,
                env_key_name="GROQ_API_KEY",
                api_base="https://api.groq.com/openai/v1",
                model_endpoint="https://api.groq.com/openai/v1/models",
                auth_type="bearer",
                json_path="data",
                id_field="id",
                litellm_prefix="groq/",
            ),
            GroqProvider
        )
        registry.register(
            ProviderConfig(
                provider_id="openrouter",
                label="OpenRouter",
                local=False,
                env_key_name="OPENROUTER_API_KEY",
                api_base="https://openrouter.ai/api/v1",
                model_endpoint="https://openrouter.ai/api/v1/models",
                auth_type="bearer",
                json_path="data",
                id_field="id",
                litellm_prefix="openrouter/",
            ),
            OpenRouterProvider
        )
        registry.register(
            ProviderConfig(
                provider_id="deepseek",
                label="DeepSeek",
                local=False,
                env_key_name="DEEPSEEK_API_KEY",
                api_base="https://api.deepseek.com/v1",
                model_endpoint="https://api.deepseek.com/v1/models",
                auth_type="bearer",
                json_path="data",
                id_field="id",
                litellm_prefix="deepseek/",
            ),
            DeepSeekProvider
        )
        registry.register(
            ProviderConfig(
                provider_id="mistral",
                label="Mistral",
                local=False,
                env_key_name="MISTRAL_API_KEY",
                api_base="https://api.mistral.ai/v1",
                model_endpoint="https://api.mistral.ai/v1/models",
                auth_type="bearer",
                json_path="data",
                id_field="id",
                litellm_prefix="mistral/",
            ),
            MistralProvider
        )
        registry.register(
            ProviderConfig(
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
            GeminiProvider
        )
        registry.register(
            ProviderConfig(
                provider_id="ollama",
                label="Ollama",
                local=True,
                env_key_name=None,
                api_base="http://localhost:11434",
                model_endpoint="http://localhost:11434/api/tags",
                auth_type="none",
                json_path="models",
                id_field="name",
                litellm_prefix="ollama/",
            ),
            OllamaProvider
        )
        registry.register(
            ProviderConfig(
                provider_id="omniroute",
                label="OmniRoute",
                local=True,
                env_key_name="OMNIROUTE_API_KEY",
                api_base="http://localhost:20128/v1",
                model_endpoint="http://localhost:20128/v1/models",
                auth_type="bearer",
                json_path="data",
                id_field="id",
                litellm_prefix="openai/",
            ),
            OmniRouteProvider
        )
        _init_done = True


async def list_models(db: Any) -> list[ModelInfo]:
    """Return all selectable models from all linked providers."""
    _ensure_initialized()

    linked = await list_linked_providers(db)

    models: list[ModelInfo] = []

    # Ollama first (local, free, preferred default)
    try:
        ollama_models = await fetch_ollama_models()
        for m in ollama_models:
            models.append(m)
    except Exception:
        pass

    # Cloud providers - fetch concurrently
    async def _fetch_one(pid: str) -> list[ModelInfo]:
        api_key = await resolve_api_key(pid, db)
        if not api_key:
            return []
        config = registry.get_config(pid)
        if not config:
            return []
        try:
            return await fetch_models_from_provider(api_key, config)
        except Exception:
            return []

    if linked:
        import asyncio
        results = await asyncio.gather(
            *[_fetch_one(pid) for pid in linked],
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                continue
            models.extend(result)

    # Filter out inaccessible models
    from .inaccessible import is_inaccessible
    models = [m for m in models if not is_inaccessible(m.litellm_id)]

    return models


async def list_provider_status(db: Any) -> list[dict[str, Any]]:
    """Return only providers currently reachable with keys."""
    from .model_discovery import _ollama_reachable

    _ensure_initialized()

    keys = await get_db_keys(db)
    statuses = []

    # Check Ollama
    if await _ollama_reachable():
        statuses.append({
            "id": "ollama",
            "label": "Ollama",
            "state": "local",
        })

    # Check cloud providers
    for pid in ["openai", "anthropic", "nvidia", "together", "groq",
                "openrouter", "deepseek", "mistral", "gemini", "omniroute"]:
        api_key = keys.get(pid) or get_static_env_key(pid)
        if api_key and isinstance(api_key, str):
            try:
                config = registry.get_config(pid)
                if config and await _provider_reachable(config, api_key):
                    statuses.append({
                        "id": pid,
                        "label": config.label,
                        "state": "online",
                    })
            except Exception:
                pass

    return statuses


async def _provider_reachable(config: ProviderConfig, api_key: str) -> bool:
    """Check if provider endpoint is reachable with given key."""
    import httpx

    headers = {"Accept": "application/json"}
    if config.auth_type == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"
    elif config.auth_type == "header":
        headers[config.auth_header_name] = api_key
    if config.extra_headers:
        headers.update(config.extra_headers)

    url = config.model_endpoint
    if config.auth_type == "query" and config.query_key:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{config.query_key}={api_key}"

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return True
    except httpx.HTTPError:
        return False


async def default_model_id(db: Any) -> str | None:
    """Pick first available model (prefers Ollama)."""
    models = await list_models(db)
    return models[0].id if models else None


async def stream_completion(
    model_id: str,
    messages: list[dict],
    db: Any,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> AsyncGenerator[str]:
    """Stream completion from the appropriate provider."""
    _ensure_initialized()

    # Resolve which provider this model belongs to
    provider_id, litellm_id = _resolve_model(model_id)

    # Get API key
    api_key = await resolve_api_key(provider_id, db)

    # Get provider class
    provider_class = registry.get_provider_class(provider_id)
    if not provider_class:
        # Fallback to LiteLLM
        from .litellm_fallback import LiteLLMProvider
        provider = LiteLLMProvider(registry.get_config(provider_id) or ProviderConfig(
            provider_id=provider_id, label=provider_id, local=False,
            env_key_name=None, api_base="", model_endpoint="",
            json_path="", id_field="", litellm_prefix=""
        ))
    else:
        config = registry.get_config(provider_id)
        if not config:
            raise ValueError(f"Unknown provider: {provider_id}")
        # Pass API key to provider constructor for validation
        provider = provider_class(config, api_key)

    # Stream
    async for chunk in provider.stream_completion(
        model_id=model_id,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        api_key=api_key,
    ):
        yield chunk


def _resolve_model(model_id: str) -> tuple[str, str]:
    """Parse app-side model ID (provider::litellm_id) into components."""
    if "::" not in model_id:
        raise ValueError(f"Invalid model ID format: {model_id}")
    provider_id, litellm_id = model_id.split("::", 1)
    return provider_id, litellm_id


def list_providers_static() -> dict[str, dict]:
    """Return provider metadata without exposing keys.

    ``env_key_set`` reflects *actual* availability of a key in the
    environment — not just whether a config slot exists — so the
    Settings UI correctly shows only linked providers.
    """
    _ensure_initialized()
    return {
        pid: {
            "label": cfg.label,
            "local": cfg.local,
            "env_key_set": bool(get_static_env_key(pid)),
        }
        for pid, cfg in registry.get_all_configs().items()
    }


def clear_inaccessible_models() -> int:
    """Clear the inaccessible model cache."""
    return clear_inaccessible()

MAX_TOOL_ROUNDS = 10
DEFAULT_TOOL_TIMEOUT = 30.0

async def stream_response_events(
    model_id: str,
    messages: list[dict],
    db: Any,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
    message_id: str | None = None,
    request_id: str | None = None,
) -> AsyncGenerator[ResponseEvent]:
    """Stream canonical Sangam response events with tool execution support."""
    _ensure_initialized()
    provider_id, litellm_id = _resolve_model(model_id)
    api_key = await resolve_api_key(provider_id, db)
    provider_class = registry.get_provider_class(provider_id)
    if not provider_class:
        from .litellm_fallback import LiteLLMProvider
        provider = LiteLLMProvider(registry.get_config(provider_id) or ProviderConfig(
            provider_id=provider_id, label=provider_id, local=False,
            env_key_name=None, api_base="", model_endpoint="",
            json_path="", id_field="", litellm_prefix=""
        ))
    else:
        config = registry.get_config(provider_id)
        if not config:
            raise ValueError(f"Unknown provider: {provider_id}")
        provider = provider_class(config, api_key)
    model_info = None
    models = await list_models(db)
    for m in models:
        if m.id == model_id:
            model_info = m
            break
    builder = ResponseEventBuilder(
        provider=provider_id,
        model=model_id,
        message_id=message_id,
        request_id=request_id,
    )
    yield builder.message_start()
    collected_text = ""
    collected_reasoning = ""
    tool_round = 0
    current_messages = messages
    received_terminal = False
    while tool_round < MAX_TOOL_ROUNDS:
        tools = None
        if model_info and model_info.capabilities and model_info.capabilities.tools:
            enabled_tools = tool_registry.get_enabled()
            if enabled_tools:
                # Phase 7: Capability orchestration - filter tools based on request
                # Get the last user message for capability decision
                last_user_msg = ""
                for msg in reversed(current_messages):
                    if msg.get("role") == "user":
                        last_user_msg = msg.get("content", "")
                        break
                if last_user_msg:
                    # Run Phase 6 analysis
                    from backend.response_intelligence import analyze_request, capability_decide
                    try:
                        guidance = await analyze_request(
                            messages=current_messages,
                            model_id=model_id,
                            temperature=temperature,
                            chat_id=None,  # Could be enhanced with actual chat_id
                            db=db,
                        )
                        # Run Phase 7 capability decision
                        decision = capability_decide(
                            user_message=last_user_msg,
                            enabled_tools=enabled_tools,
                            guidance=guidance,
                        )
                        # Use filtered tools from capability decision
                        from backend.tools.schemas import tool_definition_to_openai_function
                        tools = [tool_definition_to_openai_function(t) for t in decision.filtered_tools]
                    except Exception:
                        # On any error, fall back to all enabled tools (conservative)
                        from backend.tools.schemas import tool_definition_to_openai_function
                        tools = [tool_definition_to_openai_function(t) for t in enabled_tools]
                else:
                    # No user message, fall back to all enabled tools
                    from backend.tools.schemas import tool_definition_to_openai_function
                    tools = [tool_definition_to_openai_function(t) for t in enabled_tools]
        provider_stream = provider.stream_completion(
            model_id=litellm_id,
            messages=current_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            api_key=api_key,
            tools=tools,
        )
        accumulated_tool_calls = {}
        chunk = None
        try:
            async for chunk in provider_stream:
                if chunk.text:
                    collected_text += chunk.text
                    for e in builder.text_delta(chunk.text): yield e
                if chunk.reasoning:
                    collected_reasoning += chunk.reasoning
                    for e in builder.reasoning_delta(chunk.reasoning): yield e
                if chunk.tool_calls:
                    for tc in chunk.tool_calls:
                        idx_tc = tc.get("index", 0)
                        # Handle both string (OpenAI streaming) and dict (Ollama) arguments
                        raw_args = tc.get("function", {}).get("arguments", {})
                        if isinstance(raw_args, dict):
                            import json as _json
                            raw_args = _json.dumps(raw_args)
                        if idx_tc not in accumulated_tool_calls:
                            accumulated_tool_calls[idx_tc] = {
                                "id": tc.get("id"),
                                "type": tc.get("type", "function"),
                                "function": {
                                    "name": tc.get("function", {}).get("name"),
                                    "arguments": raw_args,
                                },
                            }
                        else:
                            accumulated_tool_calls[idx_tc]["function"]["arguments"] += raw_args
                if chunk.citations:
                    for citation in chunk.citations:
                        yield builder.event(ResponseEventType.CITATION, content=citation.get("text", ""), metadata=citation)
                if chunk.artifacts:
                    for artifact in chunk.artifacts:
                        yield builder.event(ResponseEventType.ARTIFACT_START, content=artifact.get("content", ""), metadata=artifact)
                        if artifact.get("delta"):
                            yield builder.event(ResponseEventType.ARTIFACT_DELTA, content=artifact.get("delta"), metadata=artifact)
                        yield builder.event(ResponseEventType.ARTIFACT_END, content=artifact.get("content", ""), metadata=artifact)
                if chunk.tool_results:
                    for tool_result in chunk.tool_results:
                        yield builder.event(ResponseEventType.TOOL_RESULT, content=tool_result.get("content", ""), metadata={"tool_call_id": tool_result.get("tool_call_id"), "name": tool_result.get("name"), "error": tool_result.get("error"), "is_error": tool_result.get("is_error", False)})
                if chunk.finish_reason:
                    received_terminal = True
                    if chunk.finish_reason == FinishReason.TOOL:
                        break
                    elif chunk.finish_reason in (FinishReason.STOP, FinishReason.LENGTH, FinishReason.CANCELLED, FinishReason.CONTENT_FILTER, FinishReason.ERROR):
                        if builder._text_open:
                            yield builder.text_end()
                        if builder._reasoning_open:
                            yield builder.reasoning_end()
                        if chunk.usage:
                            yield builder.usage(chunk.usage)
                        yield builder.message_end(chunk.finish_reason, metadata=chunk.metadata)
                        return
        except Exception as e:
            # Stream error - emit ERROR event and end
            if builder._text_open:
                yield builder.text_end()
            if builder._reasoning_open:
                yield builder.reasoning_end()
            yield builder.error(normalize_error(e, provider=provider_id, model=model_id))
            return
        if accumulated_tool_calls:
            tool_calls_to_execute = []
            import json as _json
            for idx_tc, tc_data in accumulated_tool_calls.items():
                if not tc_data.get("id") or not tc_data.get("function", {}).get("name"):
                    continue
                # Parse accumulated arguments string to dict
                args_str = tc_data["function"].get("arguments", "") or "{}"
                try:
                    args_dict = _json.loads(args_str)
                except _json.JSONDecodeError:
                    args_dict = {}
                tool_call = ToolCall(id=tc_data["id"], name=tc_data["function"]["name"], arguments=args_dict)
                tool_calls_to_execute.append(tool_call)
                yield builder.event(ResponseEventType.TOOL_START, content="", metadata={"tool_call_id": tool_call.id, "name": tool_call.name, "arguments": tool_call.arguments})
            if not tool_calls_to_execute:
                continue
            for tool_call in tool_calls_to_execute:
                yield builder.event(ResponseEventType.TOOL_INPUT_DELTA, content="", metadata={"tool_call_id": tool_call.id, "arguments": tool_call.arguments})
            for tool_call in tool_calls_to_execute:
                yield builder.event(ResponseEventType.TOOL_END, content="", metadata={"tool_call_id": tool_call.id, "name": tool_call.name})
            tool_results = await executor.execute_multiple(tool_calls_to_execute)
            tool_results_for_model = []
            for tool_result in tool_results:
                yield builder.event(ResponseEventType.TOOL_RESULT, content=tool_result.content, metadata={"tool_call_id": tool_result.tool_call_id, "name": tool_result.name, "error": tool_result.error, "is_error": tool_result.is_error, "data": tool_result.data})
                tool_results_for_model.append({"role": "tool", "tool_call_id": tool_result.tool_call_id, "content": tool_result.content})
            current_messages = current_messages + [{"role": "assistant", "content": collected_text, "tool_calls": [{"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": tc.arguments}} for tc in tool_calls_to_execute]}, *tool_results_for_model]
            collected_text = ""
            tool_round += 1
            continue
        if builder._text_open:
            yield builder.text_end()
        if builder._reasoning_open:
            yield builder.reasoning_end()
        if not received_terminal:
            # Stream ended without terminal chunk - this is a stream error
            yield builder.error(normalize_error(
                RuntimeError("Stream terminated without finish_reason"),
                provider=provider_id,
                model=model_id
            ))
            return
        break
    if builder._text_open:
        yield builder.text_end()
    if builder._reasoning_open:
        yield builder.reasoning_end()
    yield builder.message_end(FinishReason.LENGTH, metadata={"max_tool_rounds_reached": True})


# Backwards compatibility exports
from .compat import CURATED_MODELS, MODELS, PROVIDERS  # noqa: E402,F401
from .inaccessible import _inaccessible_models  # noqa: F401

__all__ = [
    # Main API
    "list_models",
    "list_provider_status",
    "default_model_id",
    "stream_completion",
    "list_providers_static",
    "clear_inaccessible_models",
    # Key resolution
    "resolve_api_key",
    "get_db_keys",
    # Models
    "ModelInfo",
    "ProviderConfig",
    # Provider registry
    "registry",
    # Legacy (for compatibility)
    "CURATED_MODELS",
    "MODELS",
    "PROVIDERS",
    "_inaccessible_models",
    "cleanup_ollama",
    # Response events
    stream_response_events,
]


