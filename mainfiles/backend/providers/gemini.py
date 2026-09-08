"""
Gemini provider implementation - uses query-key auth and models/ endpoint.
"""
from typing import Any

import httpx
import litellm

from .base import BaseProvider, ModelInfo, parse_litellm_stream_chunk


class GeminiProvider(BaseProvider):
    """Gemini provider - uses query parameter for API key, /models/ endpoint."""

    def prepare_headers(self, api_key: str) -> dict[str, str]:
        """Gemini uses query auth, not headers."""
        return {"Accept": "application/json"}

    def build_model_list_url(self, api_key: str | None = None) -> str:
        """Build URL with query key for Gemini."""
        if api_key and self.config.auth_type == "query" and self.config.query_key:
            sep = "&" if "?" in self.config.model_endpoint else "?"
            return f"{self.config.model_endpoint}{sep}{self.config.query_key}={api_key}"
        return self.config.model_endpoint

    async def list_models(self, api_key: str | None = None) -> list[ModelInfo]:
        # Use the resolved API key from self.api_key if not provided
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
                for entry in payload.get("models", []) or []:
                    if not isinstance(entry, dict):
                        continue

                    raw_id = entry.get("name")
                    if not raw_id or not isinstance(raw_id, str):
                        continue

                    model_id = raw_id
                    if model_id.startswith("models/"):
                        model_id = model_id[len("models/"):]

                    if not model_id or model_id in seen:
                        continue

                    # Filter non-generative models
                    lowered = model_id.lower()
                    if any(marker in lowered for marker in ("embedding", "embed", "rerank", "whisper")):
                        continue

                    seen.add(model_id)

                    # Use display name or derive from ID
                    name = entry.get("displayName") or model_id
                    litellm_id = f"gemini/{model_id}"

                    models.append(ModelInfo(
                        id=f"gemini::{litellm_id}",
                        name=name,
                        provider_id="gemini",
                        provider_label="Gemini",
                        litellm_id=litellm_id,
                        description=entry.get("description", "") if isinstance(entry.get("description"), str) else "",
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
        """Use LiteLLM for Gemini streaming."""
        litellm_id = model_id
        if "::" in model_id:
            litellm_id = model_id.split("::", 1)[1]

        completion_kwargs = {
            "model": litellm_id,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            "timeout": 60,
        }
        if max_tokens:
            completion_kwargs["max_tokens"] = max_tokens
        # Use self.api_key if not provided
        effective_key = api_key or self.api_key
        if effective_key:
            completion_kwargs["api_key"] = effective_key
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
