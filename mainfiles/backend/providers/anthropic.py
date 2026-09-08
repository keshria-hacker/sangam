"""
Anthropic provider implementation.
"""
from typing import Any

import httpx
import litellm

from .base import BaseProvider, ModelInfo, parse_litellm_stream_chunk


class AnthropicProvider(BaseProvider):
    """Anthropic provider using LiteLLM for unified streaming."""

    async def list_models(self, api_key: str | None = None) -> list[ModelInfo]:
        # Use validated API key from base class
        effective_key = api_key or self.api_key
        if not effective_key:
            return []

        headers = self.prepare_headers(effective_key)
        models = []

        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                # Anthropic uses a different endpoint format
                url = "https://api.anthropic.com/v1/models"
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                payload = response.json()

                for entry in payload.get("data", []) or []:
                    if not isinstance(entry, dict):
                        continue

                    raw_id = entry.get("id")
                    if not raw_id or not isinstance(raw_id, str):
                        continue

                    model_id = raw_id
                    if model_id.startswith("models/"):
                        model_id = model_id[len("models/"):]

                    if model_id.startswith("claude"):
                        name = model_id
                        litellm_id = f"anthropic/{model_id}"
                        models.append(ModelInfo(
                            id=f"anthropic::{litellm_id}",
                            name=name,
                            provider_id="anthropic",
                            provider_label="Anthropic",
                            litellm_id=litellm_id,
                        ))
            except (httpx.HTTPError, ValueError, KeyError):
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
        # Strip provider prefix from app-side model ID to get litellm_id
        litellm_id = model_id
        if "::" in model_id:
            litellm_id = model_id.split("::", 1)[1]

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
            if normalized.reasoning:
                yield normalized.reasoning
            if normalized.text:
                yield normalized.text
