"""
NVIDIA NIM provider - OpenAI-compatible direct streaming.
"""
import json
from typing import Any

import httpx
from backend.response_events import normalize_finish_reason, normalize_usage

from backend.config import settings

from .base import BaseProvider, ModelInfo, ProviderStreamChunk
from .inaccessible import track_inaccessible


class NVIDIAProvider(BaseProvider):
    """NVIDIA NIM provider - direct OpenAI-compatible streaming."""

    async def list_models(self, api_key: str | None = None) -> list[ModelInfo]:
        # Use the resolved API key from self.api_key if not provided
        effective_key = api_key or self.api_key
        if not effective_key:
            return []

        headers = self.prepare_headers(effective_key)
        models = []

        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                # Use the same base URL as streaming so a local-NIM override in
                # .env (NVIDIA_NIM_BASE_URL) is honored consistently instead of
                # silently splitting model-listing and streaming endpoints.
                base_url = settings.NVIDIA_NIM_BASE_URL.rstrip("/")
                response = await client.get(f"{base_url}/models", headers=headers)
                response.raise_for_status()
                payload = response.json()

                seen = set()
                for entry in payload.get("data", []) or []:
                    if not isinstance(entry, dict):
                        continue
                    raw_id = entry.get("id")
                    if not raw_id or not isinstance(raw_id, str):
                        continue

                    model_id = str(raw_id)
                    if model_id in seen:
                        continue
                    seen.add(model_id)

                    name = model_id.rsplit("/", maxsplit=1)[-1] if "/" in model_id else model_id
                    litellm_id = f"nvidia_nim/{model_id}"

                    models.append(ModelInfo(
                        id=f"nvidia::{litellm_id}",
                        name=name,
                        provider_id="nvidia",
                        provider_label="NVIDIA NIM",
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
        """Direct NVIDIA NIM streaming (OpenAI-compatible)."""
        litellm_id = model_id
        if "::" in model_id:
            litellm_id = model_id.split("::", 1)[1]

        # Strip nvidia_nim/ prefix for the actual model name sent to NIM
        model_name = litellm_id
        for prefix in ("nvidia_nim/", "nvidia/"):
            if model_name.startswith(prefix):
                model_name = model_name[len(prefix):]
                break

        base_url = settings.NVIDIA_NIM_BASE_URL.rstrip("/")
        endpoint = f"{base_url}/chat/completions"

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if kwargs.get("tools"):
            payload["tools"] = kwargs["tools"]

        headers = {
            "Authorization": f"Bearer {api_key or self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        timeout = httpx.Timeout(120.0, connect=10.0)
        yielded_content = False
        saw_terminal = False
        include_metadata = bool(kwargs.get("include_metadata"))

        try:
            async with (
                httpx.AsyncClient(timeout=timeout) as client,
                client.stream("POST", endpoint, json=payload, headers=headers) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                saw_terminal = True
                                if include_metadata:
                                    yield ProviderStreamChunk(terminal=True)
                                break
                            try:
                                chunk = json.loads(data)
                                if chunk.get("error"):
                                    raise RuntimeError(str(chunk["error"]))
                                choices = chunk.get("choices") or []
                                choice = choices[0] if choices else {}
                                content = choice.get("delta", {}).get("content", "")
                                raw_finish = choice.get("finish_reason")
                                usage = normalize_usage(chunk.get("usage"))
                                if content:
                                    yielded_content = True
                                if include_metadata:
                                    if content or raw_finish or usage:
                                        yield ProviderStreamChunk(
                                            text=content or None,
                                            finish_reason=normalize_finish_reason(raw_finish) if raw_finish else None,
                                            usage=usage,
                                            metadata={"provider_finish_reason": str(raw_finish)} if raw_finish else None,
                                            terminal=raw_finish is not None,
                                        )
                                elif content:
                                    yield content
                            except json.JSONDecodeError as exc:
                                raise RuntimeError("NVIDIA NIM returned a malformed JSON stream chunk") from exc
            if include_metadata and not saw_terminal:
                raise RuntimeError("NVIDIA NIM response stream ended before its terminal marker")
            if not yielded_content:
                raise RuntimeError(
                    "NVIDIA NIM returned no visible text. Try increasing max_tokens."
                )
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 404:
                track_inaccessible(litellm_id)
                raise RuntimeError(
                    f"NVIDIA NIM: Model '{model_name}' is not available with your API key. "
                    "It may require a separate subscription on NVIDIA's dashboard."
                ) from exc
            if status in (401, 403):
                raise RuntimeError(
                    "NVIDIA NIM: Your API key is invalid or expired. Update it in Settings."
                ) from exc
            if status == 429:
                raise RuntimeError(
                    "NVIDIA NIM: Rate limit reached. Wait a moment and retry."
                ) from exc
            raise RuntimeError(f"NVIDIA NIM request failed (HTTP {status}): {exc}") from exc
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"NVIDIA NIM request failed: {exc}") from exc
