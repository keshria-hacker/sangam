"""
OpenAI-compatible provider implementations.
Covers: OpenAI, Together AI, Groq, OpenRouter, DeepSeek, Mistral, OmniRoute
"""
import json
from typing import Any

import httpx

from .base import NON_CHAT_MARKERS, BaseProvider, ModelInfo, parse_litellm_stream_chunk


class OpenAICompatibleProvider(BaseProvider):
    """Base provider for OpenAI-compatible APIs (OpenAI, Together, Groq, OpenRouter, DeepSeek, Mistral, OmniRoute)."""

    async def list_models(self, api_key: str | None = None) -> list[ModelInfo]:
        # Use validated API key from base class
        effective_key = api_key or self.api_key
        if not effective_key:
            return []

        headers = self.prepare_headers(effective_key)
        models = []

        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                url = self.build_model_list_url(effective_key)
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                payload = response.json()

                seen = set()
                for entry in payload.get(self.config.json_path, []) or []:
                    if not isinstance(entry, dict):
                        continue

                    raw_id = entry.get(self.config.id_field)
                    if not raw_id or not isinstance(raw_id, str):
                        continue

                    model_id = str(raw_id)
                    if self.config.strip_prefix and model_id.startswith(self.config.strip_prefix):
                        model_id = model_id[len(self.config.strip_prefix):]
                    if not model_id or model_id in seen:
                        continue

                    lowered = model_id.lower()
                    if any(marker in lowered for marker in NON_CHAT_MARKERS):
                        continue

                    seen.add(model_id)
                    name = model_id.split("/")[-1] if "/" in model_id else model_id

                    litellm_id = model_id
                    if self.config.litellm_prefix:
                        litellm_id = f"{self.config.litellm_prefix}{model_id}"

                    models.append(ModelInfo(
                        id=f"{self.config.provider_id}::{litellm_id}",
                        name=name,
                        provider_id=self.config.provider_id,
                        provider_label=self.config.label,
                        litellm_id=litellm_id,
                    ))
            except (httpx.HTTPError, ValueError, json.JSONDecodeError):
                pass

        return models

    async def stream_completion(  # noqa: PLR0917
        self,
        model_id: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Stream from OpenAI-compatible endpoint (including LiteLLM for non-native providers)."""
        # Strip provider prefix from app-side model ID to get litellm_id
        litellm_id = model_id
        if "::" in model_id:
            litellm_id = model_id.split("::", 1)[1]

        # Use LiteLLM for unified streaming
        import litellm

        base_url = None
        if self.config.api_base:
            base_url = self.config.api_base

        # Use validated API key from base class
        effective_key = api_key or self.api_key

        completion_kwargs = {
            "model": litellm_id,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "timeout": 60,
        }
        if max_tokens:
            completion_kwargs["max_tokens"] = max_tokens
        if base_url:
            completion_kwargs["api_base"] = base_url
        if effective_key:
            completion_kwargs["api_key"] = effective_key
        if reasoning_effort and reasoning_effort != "none":
            completion_kwargs["reasoning_effort"] = reasoning_effort
        if kwargs.get("tools"):
            completion_kwargs["tools"] = kwargs["tools"]

        response = await litellm.acompletion(**completion_kwargs)
        include_metadata = bool(kwargs.get("include_metadata"))
        async for chunk in response:
            normalized = parse_litellm_stream_chunk(chunk)
            if normalized is None:
                continue
            if include_metadata:
                yield normalized
                continue
            # Yield the full ProviderStreamChunk to preserve reasoning, tool_calls, citations, etc.
            yield normalized


class OpenAIProvider(OpenAICompatibleProvider):
    """OpenAI provider - uses native streaming for reasoning models."""
    pass


class TogetherProvider(OpenAICompatibleProvider):
    """Together AI provider."""
    pass


class GroqProvider(OpenAICompatibleProvider):
    """Groq provider."""
    pass


class OpenRouterProvider(OpenAICompatibleProvider):
    """OpenRouter provider."""
    pass


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek provider."""
    pass


class MistralProvider(OpenAICompatibleProvider):
    """Mistral provider."""
    pass


class OmniRouteProvider(OpenAICompatibleProvider):
    """OmniRoute provider (custom OpenAI-compatible)."""
    pass
