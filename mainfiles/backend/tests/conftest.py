"""Pytest configuration and fixtures for Phase 4 Adaptive Response Intelligence tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass
from typing import AsyncGenerator, List, Dict, Any, Optional, Protocol


# =============================================================================
# Core Domain Models (to be implemented)
# =============================================================================

@dataclass(frozen=True)
class ResponsePolicy:
    """Configuration for adaptive response behavior."""
    max_tokens: int = 4096
    temperature: float = 0.7
    top_p: float = 0.9
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    stop_sequences: List[str] = None
    stream: bool = True
    adaptive_timeout: float = 30.0  # seconds
    fallback_provider: Optional[str] = None
    enable_reasoning: bool = False
    reasoning_budget: int = 1024

    def __post_init__(self):
        if self.stop_sequences is None:
            object.__setattr__(self, 'stop_sequences', [])


@dataclass(frozen=True)
class ChatMessage:
    """Immutable chat message."""
    role: str  # "user", "assistant", "system", "tool"
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to provider-compatible dict."""
        result = {"role": self.role, "content": self.content}
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
    policy: ResponsePolicy
    metadata: Dict[str, Any] = None
    request_id: str = ""

    def __post_init__(self):
        if self.metadata is None:
            object.__setattr__(self, 'metadata', {})
        if not self.request_id:
            import uuid
            object.__setattr__(self, 'request_id', str(uuid.uuid4()))


@dataclass(frozen=True)
class ChatResponse:
    """Immutable chat completion response."""
    content: str
    model: str
    finish_reason: str  # "stop", "length", "tool_calls", "error"
    usage: Dict[str, int]  # prompt_tokens, completion_tokens, total_tokens
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


# =============================================================================
# Provider Protocol (to be implemented)
# =============================================================================

class LLMProvider(Protocol):
    """Protocol for LLM providers."""

    async def complete(self, request: ChatRequest) -> ChatResponse:
        """Non-streaming completion."""
        ...

    async def stream(self, request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        """Streaming completion."""
        ...

    async def health_check(self) -> bool:
        """Check provider availability."""
        ...

    @property
    def name(self) -> str:
        """Provider identifier."""
        ...

    @property
    def supported_models(self) -> List[str]:
        """Models this provider supports."""
        ...


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def default_policy() -> ResponsePolicy:
    """Default response policy for testing."""
    return ResponsePolicy(
        max_tokens=1024,
        temperature=0.7,
        top_p=0.9,
        stream=True,
        adaptive_timeout=10.0,
    )


@pytest.fixture
def reasoning_policy() -> ResponsePolicy:
    """Policy with reasoning enabled."""
    return ResponsePolicy(
        max_tokens=2048,
        temperature=0.5,
        top_p=0.95,
        stream=True,
        adaptive_timeout=30.0,
        enable_reasoning=True,
        reasoning_budget=512,
    )


@pytest.fixture
def sample_messages() -> List[ChatMessage]:
    """Sample conversation messages."""
    return [
        ChatMessage(role="system", content="You are a helpful assistant."),
        ChatMessage(role="user", content="Hello, how are you?"),
        ChatMessage(role="assistant", content="I'm doing well, thank you!"),
        ChatMessage(role="user", content="What's the weather like?"),
    ]


@pytest.fixture
def sample_request(sample_messages: List[ChatMessage], default_policy: ResponsePolicy) -> ChatRequest:
    """Sample chat request."""
    return ChatRequest(
        messages=sample_messages,
        model="gpt-4o-mini",
        policy=default_policy,
        metadata={"user_id": "test-user", "session_id": "test-session"},
    )


@pytest.fixture
def mock_provider() -> MagicMock:
    """Mock LLM provider for testing."""
    provider = MagicMock(spec=LLMProvider)
    provider.name = "mock"
    provider.supported_models = ["gpt-4o-mini", "gpt-4o"]

    # Default successful response
    async def mock_complete(request: ChatRequest) -> ChatResponse:
        return ChatResponse(
            content="This is a mock response.",
            model=request.model,
            finish_reason="stop",
            usage={"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70},
            request_id=request.request_id,
            provider=provider.name,
            latency_ms=150.0,
        )

    async def mock_stream(request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        chunks = [
            StreamChunk(delta="This "),
            StreamChunk(delta="is "),
            StreamChunk(delta="a "),
            StreamChunk(delta="mock "),
            StreamChunk(delta="response.", finish_reason="stop"),
        ]
        for chunk in chunks:
            yield chunk

    provider.complete = mock_complete
    provider.stream = mock_stream
    provider.health_check = AsyncMock(return_value=True)

    return provider


@pytest.fixture
def failing_provider() -> MagicMock:
    """Mock provider that fails."""
    provider = MagicMock(spec=LLMProvider)
    provider.name = "failing"
    provider.supported_models = ["gpt-4o-mini"]

    async def mock_complete(request: ChatRequest) -> ChatResponse:
        raise ConnectionError("Provider unavailable")

    async def mock_stream(request: ChatRequest) -> AsyncGenerator[StreamChunk, None]:
        raise ConnectionError("Provider unavailable")
        yield  # type: ignore

    provider.complete = mock_complete
    provider.stream = mock_stream
    provider.health_check = AsyncMock(return_value=False)

    return provider