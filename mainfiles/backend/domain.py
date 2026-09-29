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
from typing import Any, Dict, List, Optional, Protocol


@dataclass(frozen=True)
class ChatMessage:
    """Immutable chat message."""

    role: str  # "user" | "assistant" | "system" | "tool"
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to provider-compatible dict."""
        result: Dict[str, Any] = {"role": self.role, "content": self.content}
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

    messages: List[ChatMessage]
    model: str
    policy: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)
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
    usage: Dict[str, int]  # prompt/completion/total tokens
    request_id: str
    provider: str
    latency_ms: float
    tool_calls: Optional[List[Dict[str, Any]]] = None
    reasoning: Optional[str] = None


@dataclass(frozen=True)
class StreamChunk:
    """Single chunk in a streaming response."""

    delta: str
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, int]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    reasoning: Optional[str] = None


class LLMProvider(Protocol):
    """Protocol every LLM provider adapter implements."""

    async def complete(self, request: ChatRequest) -> ChatResponse: ...

    async def stream(self, request: ChatRequest): ...

    async def health_check(self) -> bool: ...

    @property
    def name(self) -> str: ...

    @property
    def supported_models(self) -> List[str]: ...
