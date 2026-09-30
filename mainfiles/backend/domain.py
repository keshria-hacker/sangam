"""
domain.py — shared domain types used across the backend.

These are plain dataclasses (not HTTP schemas): the response-policy layer,
the request builder and the agentic-reasoning service all speak this shape.
They used to live in ``tests/conftest.py``, which forced production code to
import test fixtures — they now live here so everything imports from one
canonical place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ChatMessage:
    """Immutable chat message."""

    role: str  # "user" | "assistant" | "system" | "tool"
    content: str
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to provider-compatible dict."""
        result: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            result["name"] = self.name
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result


@dataclass(frozen=True)
class ChatRequest:
    """Immutable chat completion request."""

    messages: list[ChatMessage]
    model: str
    policy: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    request_id: str = ""

    def __post_init__(self) -> None:
        if not self.request_id:
            import uuid

            object.__setattr__(self, "request_id", str(uuid.uuid4()))


@dataclass(frozen=True)
class ChatResponse:
    """Immutable chat completion response."""

    content: str
    model: str
    finish_reason: str  # "stop" | "length" | "tool_calls" | "error"
    usage: dict[str, int]  # prompt/completion/total tokens
    request_id: str
    provider: str
    latency_ms: float
    tool_calls: list[dict[str, Any]] | None = None
    reasoning: str | None = None


@dataclass(frozen=True)
class StreamChunk:
    """Single chunk in a streaming response."""

    delta: str
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    tool_calls: list[dict[str, Any]] | None = None
    reasoning: str | None = None


class LLMProvider(Protocol):
    """Protocol every LLM provider adapter implements."""

    async def complete(self, request: ChatRequest) -> ChatResponse: ...

    async def stream(self, request: ChatRequest): ...

    async def health_check(self) -> bool: ...

    @property
    def name(self) -> str: ...

    @property
    def supported_models(self) -> list[str]: ...
