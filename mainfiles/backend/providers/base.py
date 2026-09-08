"""
Base provider types and abstract interface.
"""
import os
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from backend.response_events import (
    FinishReason,
    ModelCapabilities,
    UsageInfo,
    normalize_finish_reason,
    normalize_usage,
)
from backend.response_events import ResponseEventType


@dataclass
class ProviderConfig:
    """Static configuration for a provider."""
    provider_id: str
    label: str
    local: bool                    # True for Ollama, LM Studio, vLLM
    env_key_name: str              # Name of env var (e.g., "OPENAI_API_KEY")
    api_base: str                  # Provider's /v1/models endpoint
    model_endpoint: str            # Full model listing URL
    auth_type: str = "bearer"      # "bearer", "header", "query"
    auth_header_name: str = "Authorization"
    json_path: str = "data"        # JSON path to model array
    id_field: str = "id"           # Field in model object for ID
    strip_prefix: str = ""         # Prefix to strip from model IDs (e.g., "models/")
    extra_headers: dict[str, str] | None = None
    query_key: str | None = None   # For query-param auth (Gemini)
    # LiteLLM prefix for routing (e.g., "openai/", "nvidia_nim/")
    litellm_prefix: str | None = None
    # Optional: custom field for model display name
    name_field: str | None = None
    # Optional: field for model description
    description_field: str | None = None


@dataclass
class ModelInfo:
    """Standardized model information."""
    id: str                        # Stable app-side identifier
    name: str                      # Human-readable name
    provider_id: str               # Provider identifier
    provider_label: str            # Human-readable provider name
    litellm_id: str | None = None  # Full LiteLLM model string (prefix + catalog id)
    context_window: int | None = None
    supports_streaming: bool = True
    supports_tools: bool = False
    supports_vision: bool = False
    supports_reasoning: bool = False
    capabilities: ModelCapabilities | None = None
    owned_by: str | None = None
    description: str = ""
    model_id: str = ""  # Raw model ID from provider (after strip_prefix, before litellm_prefix)

    def __post_init__(self) -> None:
        if self.capabilities is None:
            self.capabilities = ModelCapabilities(
                streaming=self.supports_streaming,
                tools=self.supports_tools,
                reasoning=self.supports_reasoning,
                vision=self.supports_vision,
            )

    # Backward compatibility property
    @property
    def provider(self) -> str:
        return self.provider_id


@dataclass
class ProviderStreamChunk:
    """Provider-boundary stream data before canonical event serialization.

    Existing callers may continue consuming plain strings. The canonical
    response facade requests these typed chunks so finish reasons and usage are
    not discarded while provider payloads remain private to the adapter.
    """

    text: str | None = None
    reasoning: str | None = None
    # Tool calls: list of dicts with id, type, function:{name,arguments}
    tool_calls: list[dict] | None = None
    # Citations: list of citation objects
    citations: list[dict] | None = None
    # Artifacts: list of artifact objects
    artifacts: list[dict] | None = None
    # Tool results: list of dicts with tool_call_id and result/content
    tool_results: list[dict] | None = None
    finish_reason: FinishReason | None = None
    usage: UsageInfo | None = None
    metadata: dict[str, Any] | None = None
    terminal: bool = False


def parse_litellm_stream_chunk(chunk: Any) -> ProviderStreamChunk | None:
    """Extract canonical provider-boundary data from a LiteLLM chunk."""
    choices = getattr(chunk, "choices", None) or []
    choice = choices[0] if choices else None
    delta = getattr(choice, "delta", None) if choice is not None else None
    raw_finish_reason = getattr(choice, "finish_reason", None) if choice is not None else None
    raw_usage = getattr(chunk, "usage", None)

    text = getattr(delta, "content", None) if delta is not None else None
    reasoning = getattr(delta, "reasoning_content", None) if delta is not None else None
    # Tool calls from LiteLLM/OpenAI format
    raw_tool_calls = getattr(delta, "tool_calls", None) if delta is not None else None
    tool_calls = None
    if raw_tool_calls:
        # Convert tool_calls to serializable dicts
        tool_calls = []
        for tc in raw_tool_calls:
            tc_dict = {
                "id": getattr(tc, "id", None),
                "type": getattr(tc, "type", "function"),
                "function": {
                    "name": getattr(getattr(tc, "function", None), "name", None),
                    "arguments": getattr(getattr(tc, "function", None), "arguments", None),
                },
            }
            tool_calls.append(tc_dict)

    # Citations (provider-specific, check common fields)
    citations = None
    raw_citations = getattr(delta, "citations", None) if delta is not None else None
    if raw_citations:
        citations = raw_citations if isinstance(raw_citations, list) else [raw_citations]

    # Artifacts (provider-specific, check common fields)
    artifacts = None
    raw_artifacts = getattr(delta, "artifacts", None) if delta is not None else None
    if raw_artifacts:
        artifacts = raw_artifacts if isinstance(raw_artifacts, list) else [raw_artifacts]

    usage = normalize_usage(raw_usage)
    finish_reason = normalize_finish_reason(raw_finish_reason) if raw_finish_reason else None
    metadata = {"provider_finish_reason": str(raw_finish_reason)} if raw_finish_reason else None

    if not any((text, reasoning, usage, finish_reason, tool_calls, citations, artifacts)):
        return None
    return ProviderStreamChunk(
        text=text or None,
        reasoning=reasoning or None,
        tool_calls=tool_calls,
        citations=citations,
        artifacts=artifacts,
        usage=usage,
        finish_reason=finish_reason,
        metadata=metadata,
        terminal=raw_finish_reason is not None,
    )


class BaseProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(self, config: ProviderConfig, api_key: str | None = None):
        self.config = config
        self._api_key = api_key

        # Validate API key for non-local providers at initialization
        if not config.local and config.env_key_name:
            # Resolve API key from parameter or environment
            resolved_key = api_key or os.environ.get(config.env_key_name)
            if not resolved_key or not resolved_key.strip():
                raise ValueError(
                    f"{config.label} API key required. Set {config.env_key_name} "
                    f"in environment or .env file, or link it in Settings -> Provider API Keys."
                )
            self._api_key = resolved_key.strip()

    @property
    def api_key(self) -> str | None:
        """Get the resolved API key."""
        return self._api_key

    @abstractmethod
    async def list_models(self, api_key: str | None = None) -> list[ModelInfo]:
        """Fetch available models from the provider's API."""
        pass

    @abstractmethod
    async def stream_completion(self, model_id: str, messages: list[dict], temperature: float = 0.7, max_tokens: int | None = None, reasoning_effort: str | None = None, api_key: str | None = None, **kwargs: Any) -> AsyncGenerator[str | ProviderStreamChunk]:
        """Stream a completion from the provider."""
        pass

    def prepare_headers(self, api_key: str) -> dict[str, str]:
        """Build authentication headers for the provider."""
        headers = {"Accept": "application/json"}
        if self.config.auth_type == "bearer":
            headers["Authorization"] = f"Bearer {api_key}"
        elif self.config.auth_type == "header":
            headers[self.config.auth_header_name] = api_key
        # query auth handled by caller
        if self.config.extra_headers:
            headers.update(self.config.extra_headers)
        return headers

    def build_model_list_url(self, api_key: str | None = None) -> str:
        """Build the model listing URL (handles query-key auth)."""
        if self.config.auth_type == "query" and self.config.query_key and api_key:
            sep = "&" if "?" in self.config.model_endpoint else "?"
            return f"{self.config.model_endpoint}{sep}{self.config.query_key}={api_key}"
        return self.config.model_endpoint

    def parse_model_list(self, payload: dict, api_key: str | None = None) -> list[ModelInfo]:
        """Parse raw provider model list into ModelInfo objects."""
        models = []
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
            seen.add(model_id)

            # Filter non-chat models
            lowered = model_id.lower()
            if any(marker in lowered for marker in NON_CHAT_MARKERS):
                continue

            # Derive name
            name = self._derive_name(model_id, entry)

            # Build litellm_id
            litellm_id = model_id
            if self.config.litellm_prefix:
                litellm_id = f"{self.config.litellm_prefix}{model_id}"

            models.append(ModelInfo(
                id=f"{self.config.provider_id}::{litellm_id}",
                name=name,
                provider_id=self.config.provider_id,
                provider_label=self.config.label,
                litellm_id=litellm_id,
                description=entry.get("description", "") if isinstance(entry.get("description"), str) else "",
            ))
        return models

    def _derive_name(self, model_id: str, entry: dict) -> str:
        """Extract or derive a human-readable name from the model entry."""
        # This can be overridden by subclasses for custom naming
        return model_id.rsplit("/", maxsplit=1)[-1] if "/" in model_id else model_id


# Non-chat model markers (universal)
NON_CHAT_MARKERS = (
    "whisper", "dall-e", "dall_e", "tts", "embedding", "embed",
    "moderation", "rerank", "reranker",
)
