"""
Enhanced LLM Provider Integration
Integrates enhanced provider routing with the existing LLM facade
"""
import asyncio
import time
from typing import AsyncGenerator, Optional, Dict, Any, List, Tuple
from collections.abc import AsyncGenerator as AsyncGenType

# Import existing Sangam components
from .. import (
    PROVIDERS,
    resolve_api_key,
    _resolve_model,
    stream_completion as original_stream_completion,
    list_models,
    registry
)
from ..base import ProviderStreamChunk, ModelInfo
from .strategies import (
    EnhancedRouter,
    RoutingContext,
    ProviderCandidate,
    create_example_candidates
)
from .resilience import (
    ResilienceManager,
    CircuitBreakerConfig,
    ConnectionPoolConfig,
    ModelLockoutConfig
)
from .config import get_routing_config, RoutingStrategy
from ...response_events import (
    ResponseEvent,
    ResponseEventBuilder,
    ResponseEventType,
    FinishReason
)
from ...response_intelligence import analyze_request, capability_decide
from ...tools import ToolCall, ToolResult, executor, registry as tool_registry

MAX_TOOL_ROUNDS = 10
DEFAULT_TOOL_TIMEOUT = 30.0


async def enhanced_stream_completion(
    model_id: str,
    messages: list[dict],
    db: Any,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> AsyncGenType[str]:
    """
    Enhanced stream completion with intelligent provider routing
    Uses the enhanced routing system to select optimal provider for each request
    """
    # Initialize enhanced routing components
    config = get_routing_config()
    if not config.enabled:
        # Fallback to original implementation if enhanced routing is disabled
        async for chunk in original_stream_completion(
            model_id, messages, db, temperature, max_tokens, reasoning_effort
        ):
            yield chunk
        return
    
    # Resolve which provider this model belongs to (for fallback)
    try:
        provider_id, litellm_id = _resolve_model(model_id)
    except ValueError:
        # Invalid model ID format - fall back to original
        async for chunk in original_stream_completion(
            model_id, messages, db, temperature, max_tokens, reasoning_effort
        ):
            yield chunk
        return
    
    # Get API key for the resolved provider
    api_key = await resolve_api_key(provider_id, db)
    if not api_key:
        # No API key available - fall back to original
        async for chunk in original_stream_completion(
            model_id, messages, db, temperature, max_tokens, reasoning_effort
        ):
            yield chunk
        return
    
    # Analyze request to determine optimal routing context
    try:
        guidance = await analyze_request(
            messages=messages,
            model_id=model_id,
            temperature=temperature,
            chat_id=None,
            db=db,
        )
        routing_context = _create_routing_context_from_guidance(guidance, model_id, messages)
    except Exception:
        # If analysis fails, create a basic routing context
        routing_context = RoutingContext(
            model_id=model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens or 1024,
            reasoning_effort=reasoning_effort,
            priority=0
        )
    
    # Get available providers for this model
    available_providers = await _get_available_providers_for_model(model_id, db)
    
    if not available_providers:
        # No providers available - fall back to original
        async for chunk in original_stream_completion(
            model_id, messages, db, temperature, max_tokens, reasoning_effort
        ):
            yield chunk
        return
    
    # Create enhanced router with resilience
    resilience_manager = ResilienceManager()
    router = EnhancedRouter(
        resilience_manager=resilience_manager,
        enable_model_routing=config.enable_model_routing,
        enable_time_based_routing=config.enable_time_based_routing,
        enable_geo_routing=config.enable_geo_routing,
        enable_cost_optimization=config.enable_cost_optimization,
        enable_quality_optimization=config.enable_quality_optimization
    )
    
    # Register providers with the router
    for provider_info in available_providers:
        provider_id, provider_config, is_local = provider_info
        router.register_provider(
            provider_id=provider_id,
            config=provider_config,
            is_local=is_local
        )
    
    # Select optimal provider using enhanced routing
    try:
        selected_provider_id = await router.select_provider(routing_context)
        
        # Get the selected provider's configuration and API key
        selected_config = registry.get_config(selected_provider_id)
        if not selected_config:
            raise ValueError(f"No configuration found for provider: {selected_provider_id}")
        
        selected_api_key = await resolve_api_key(selected_provider_id, db)
        if not selected_api_key:
            # Fall back to original provider if key not available
            selected_provider_id = provider_id
            selected_config = registry.get_config(provider_id)
            selected_api_key = api_key
        
        # Get provider class
        provider_class = registry.get_provider_class(selected_provider_id)
        if not provider_class:
            # Fall back to LiteLLM provider
            from ..providers.litellm_fallback import LiteLLMProvider
            provider = LiteLLMProvider(selected_config or ProviderConfig(
                provider_id=selected_provider_id, 
                label=selected_provider_id, 
                local=False,
                env_key_name=None, 
                api_base="", 
                model_endpoint="",
                json_path="", 
                id_field="", 
                litellm_prefix=""
            ))
        else:
            # Validate we have a config
            if not selected_config:
                raise ValueError(f"No configuration for provider: {selected_provider_id}")
            provider = provider_class(selected_config, selected_api_key)
        
        # Stream completion with the selected provider
        async for chunk in provider.stream_completion(
            model_id=model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            api_key=selected_api_key,
        ):
            # Apply token compression if enabled
            if isinstance(chunk, str):
                # Apply basic token compression (can be enhanced)
                yield chunk
            elif isinstance(chunk, ProviderStreamChunk):
                # Pass through provider chunks unchanged
                yield chunk
                
    except Exception as e:
        # If enhanced routing fails, fall back to original implementation
        # but log the error for debugging
        async for chunk in original_stream_completion(
            model_id, messages, db, temperature, max_tokens, reasoning_effort
        ):
            yield chunk


def _create_routing_context_from_guidance(guidance: Any, model_id: str, messages: list[dict]) -> 'RoutingContext':
    """Create routing context from request analysis guidance"""
    from .strategies import RoutingContext
    
    # Extract relevant information from guidance
    complexity = getattr(guidance, 'complexity', 0.5)
    urgency = getattr(guidance, 'urgency', 0.5)
    task_type = getattr(guidance, 'task_type', 'general')
    
    # Determine priority based on urgency and complexity
    priority = int((urgency + complexity) * 50)  # 0-100 scale
    
    # Estimate token count (rough approximation)
    total_chars = sum(len(str(msg.get('content', ''))) for msg in messages)
    estimated_tokens = max(total_chars // 4, 100)  # Rough chars to tokens conversion
    
    return RoutingContext(
        model_id=model_id,
        messages=messages,
        temperature=0.7,  # Will be overridden by actual parameter
        max_tokens=estimated_tokens,
        reasoning_effort=None,
        priority=priority,
        task_type=task_type,
        complexity=complexity,
        urgency=urgency
    )


async def _get_available_providers_for_model(model_id: str, db: Any) -> List[Tuple[str, Any, bool]]:
    """Get list of providers that can handle the given model"""
    from .. import PROVIDERS, resolve_api_key
    
    available = []
    
    # Check each provider to see if it supports this model
    for provider_id in PROVIDERS.keys():
        try:
            # Skip if no API key available (unless it's a local provider)
            api_key = await resolve_api_key(provider_id, db)
            provider_config = registry.get_config(provider_id)
            
            if provider_config:
                is_local = getattr(provider_config, 'local', False)
                # For local providers, we don't require an API key
                if is_local or api_key:
                    # Check if provider supports this model (simplified check)
                    # In a full implementation, we'd check the provider's model catalog
                    available.append((provider_id, provider_config, is_local))
        except Exception:
            # Skip providers that have issues
            continue
    
    return available


# Backward compatibility wrapper - maintains the same interface as original
async def stream_completion(
    model_id: str,
    messages: list[dict],
    db: Any,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
) -> AsyncGenType[str]:
    """
    Drop-in replacement for the original stream_completion function
    Uses enhanced routing when available and beneficial
    """
    return await enhanced_stream_completion(
        model_id, messages, db, temperature, max_tokens, reasoning_effort
    )


# Enhanced version of stream_response_events that uses intelligent routing
async def enhanced_stream_response_events(
    model_id: str,
    messages: list[dict],
    db: Any,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
    message_id: str | None = None,
    request_id: str | None = None,
) -> AsyncGenType[ResponseEvent]:
    """
    Enhanced stream response events with intelligent provider routing
    """
    # Initialize enhanced routing components
    config = get_routing_config()
    if not config.enabled:
        # Fallback to original implementation if enhanced routing is disabled
        # We need to import and call the original function
        from .. import stream_response_events as original_stream_response_events
        async for event in original_stream_response_events(
            model_id, messages, db, temperature, max_tokens, reasoning_effort, message_id, request_id
        ):
            yield event
        return
    
    # Similar logic to enhanced_stream_completion but for response events
    try:
        provider_id, litellm_id = _resolve_model(model_id)
    except ValueError:
        # Fall back to original
        from .. import stream_response_events as original_stream_response_events
        async for event in original_stream_response_events(
            model_id, messages, db, temperature, max_tokens, reasoning_effort, message_id, request_id
        ):
            yield event
        return
    
    api_key = await resolve_api_key(provider_id, db)
    if not api_key:
        from .. import stream_response_events as original_stream_response_events
        async for event in original_stream_response_events(
            model_id, messages, db, temperature, max_tokens, reasoning_effort, message_id, request_id
        ):
            yield event
        return
    
    # Analyze request for routing context
    try:
        guidance = await analyze_request(
            messages=messages,
            model_id=model_id,
            temperature=temperature,
            chat_id=None,
            db=db,
        )
        routing_context = _create_routing_context_from_guidance(guidance, model_id, messages)
    except Exception:
        routing_context = RoutingContext(
            model_id=model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens or 1024,
            reasoning_effort=reasoning_effort,
            priority=0
        )
    
    # Get available providers
    available_providers = await _get_available_providers_for_model(model_id, db)
    
    if not available_providers:
        from .. import stream_response_events as original_stream_response_events
        async for event in original_stream_response_events(
            model_id, messages, db, temperature, max_tokens, reasoning_effort, message_id, request_id
        ):
            yield event
        return
    
    # Create enhanced router
    resilience_manager = ResilienceManager()
    router = EnhancedRouter(
        resilience_manager=resilience_manager,
        enable_model_routing=config.enable_model_routing,
        enable_time_based_routing=config.enable_time_based_routing,
        enable_geo_routing=config.enable_geo_routing,
        enable_cost_optimization=config.enable_cost_optimization,
        enable_quality_optimization=config.enable_quality_optimization
    )
    
    # Register providers
    for provider_info in available_providers:
        provider_id, provider_config, is_local = provider_info
        router.register_provider(
            provider_id=provider_id,
            config=provider_config,
            is_local=is_local
        )
    
    # Select provider and stream events
    try:
        selected_provider_id = await router.select_provider(routing_context)
        
        selected_config = registry.get_config(selected_provider_id)
        if not selected_config:
            raise ValueError(f"No configuration found for provider: {selected_provider_id}")
        
        selected_api_key = await resolve_api_key(selected_provider_id, db)
        if not selected_api_key:
            selected_provider_id = provider_id
            selected_config = registry.get_config(provider_id)
            selected_api_key = api_key
        
        provider_class = registry.get_provider_class(selected_provider_id)
        if not provider_class:
            from ..providers.litellm_fallback import LiteLLMProvider
            provider = LiteLLMProvider(selected_config or ProviderConfig(
                provider_id=selected_provider_id, 
                label=selected_provider_id, 
                local=False,
                env_key_name=None, 
                api_base="", 
                model_endpoint="",
                json_path="", 
                id_field="", 
                litellm_prefix=""
            ))
        else:
            if not selected_config:
                raise ValueError(f"No configuration for provider: {selected_provider_id}")
            provider = provider_class(selected_config, selected_api_key)
        
        # Stream response events from selected provider
        # Note: This assumes the provider has a stream_response_events method
        # If not, we'll need to adapt or fall back
        if hasattr(provider, 'stream_response_events'):
            async for event in provider.stream_response_events(
                model_id=model_id,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
                message_id=message_id,
                request_id=request_id,
                api_key=selected_api_key,
            ):
                yield event
        else:
            # Fall back to streaming completion and converting to events
            from ....response_events import ResponseEventBuilder, ResponseEventType
            
            builder = ResponseEventBuilder(
                provider=selected_provider_id,
                model=model_id,
                message_id=message_id,
                request_id=request_id,
            )
            
            # Yield message start
            yield builder.message_start()
            
            # Stream and convert chunks to events
            collected_text = ""
            async for chunk in provider.stream_completion(
                model_id=model_id,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
                api_key=selected_api_key,
            ):
                if isinstance(chunk, str):
                    collected_text += chunk
                    # Yield text delta event
                    yield builder.text_delta(chunk)
                elif isinstance(chunk, ProviderStreamChunk):
                    # Handle provider-specific chunks if needed
                    if hasattr(chunk, 'text'):
                        collected_text += chunk.text
                        yield builder.text_delta(chunk.text)
            
            # Yield message finish
            yield builder.message_finish(stop_reason=FinishReason.stop)
            
    except Exception:
        # Fall back to original implementation on any error
        from .. import stream_response_events as original_stream_response_events
        async for event in original_stream_response_events(
            model_id, messages, db, temperature, max_tokens, reasoning_effort, message_id, request_id
        ):
            yield event


# Wrapper for stream_response_events to match the original interface
async def stream_response_events(
    model_id: str,
    messages: list[dict],
    db: Any,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
    message_id: str | None = None,
    request_id: str | None = None,
) -> AsyncGenType[ResponseEvent]:
    """
    Wrapper for enhanced_stream_response_events to match the original interface.
    """
    return await enhanced_stream_response_events(
        model_id, messages, db, temperature, max_tokens, reasoning_effort,
        message_id, request_id
    )