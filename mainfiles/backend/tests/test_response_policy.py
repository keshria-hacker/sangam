"""
Unit tests for the ResponsePolicy module - Phase 4 Adaptive Response Intelligence.

These tests define the expected behavior BEFORE implementation (TDD Red phase).
"""

import pytest
from dataclasses import FrozenInstanceError
from typing import List

from backend.tests.conftest import (
    ResponsePolicy,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    StreamChunk,
)


# =============================================================================
# ResponsePolicy Tests
# =============================================================================

class TestResponsePolicy:
    """Test ResponsePolicy configuration and validation."""

    def test_default_policy_creation(self):
        """Test creating a policy with defaults."""
        policy = ResponsePolicy()

        assert policy.max_tokens == 4096
        assert policy.temperature == 0.7
        assert policy.top_p == 0.9
        assert policy.presence_penalty == 0.0
        assert policy.frequency_penalty == 0.0
        assert policy.stop_sequences == []
        assert policy.stream is True
        assert policy.adaptive_timeout == 30.0
        assert policy.fallback_provider is None
        assert policy.enable_reasoning is False
        assert policy.reasoning_budget == 1024

    def test_custom_policy_creation(self):
        """Test creating a policy with custom values."""
        policy = ResponsePolicy(
            max_tokens=2048,
            temperature=0.5,
            top_p=0.95,
            presence_penalty=0.1,
            frequency_penalty=0.2,
            stop_sequences=["STOP", "END"],
            stream=False,
            adaptive_timeout=60.0,
            fallback_provider="anthropic",
            enable_reasoning=True,
            reasoning_budget=2048,
        )

        assert policy.max_tokens == 2048
        assert policy.temperature == 0.5
        assert policy.top_p == 0.95
        assert policy.presence_penalty == 0.1
        assert policy.frequency_penalty == 0.2
        assert policy.stop_sequences == ["STOP", "END"]
        assert policy.stream is False
        assert policy.adaptive_timeout == 60.0
        assert policy.fallback_provider == "anthropic"
        assert policy.enable_reasoning is True
        assert policy.reasoning_budget == 2048

    def test_policy_immutability(self):
        """Test that ResponsePolicy is immutable (frozen dataclass)."""
        policy = ResponsePolicy(max_tokens=1024)

        with pytest.raises(FrozenInstanceError):
            policy.max_tokens = 2048

        with pytest.raises(FrozenInstanceError):
            policy.temperature = 0.5

    def test_policy_equality(self):
        """Test policy equality comparison."""
        policy1 = ResponsePolicy(max_tokens=1024, temperature=0.7)
        policy2 = ResponsePolicy(max_tokens=1024, temperature=0.7)
        policy3 = ResponsePolicy(max_tokens=2048, temperature=0.7)

        assert policy1 == policy2
        assert policy1 != policy3

    def test_policy_repr(self):
        """Test policy string representation."""
        policy = ResponsePolicy(max_tokens=1024, temperature=0.5)
        repr_str = repr(policy)

        assert "ResponsePolicy" in repr_str
        assert "max_tokens=1024" in repr_str
        assert "temperature=0.5" in repr_str

    def test_stop_sequences_defaults_to_empty_list(self):
        """Test stop_sequences defaults to empty list, not None."""
        policy = ResponsePolicy()
        assert policy.stop_sequences == []
        assert isinstance(policy.stop_sequences, list)

    @pytest.mark.parametrize("temperature", [0.0, 0.5, 1.0, 1.5, 2.0])
    def test_temperature_range(self, temperature):
        """Test various temperature values."""
        policy = ResponsePolicy(temperature=temperature)
        assert policy.temperature == temperature

    @pytest.mark.parametrize("top_p", [0.1, 0.5, 0.9, 0.95, 1.0])
    def test_top_p_range(self, top_p):
        """Test various top_p values."""
        policy = ResponsePolicy(top_p=top_p)
        assert policy.top_p == top_p

    def test_reasoning_budget_only_used_when_enabled(self):
        """Test reasoning_budget is only relevant when enable_reasoning=True."""
        policy_disabled = ResponsePolicy(enable_reasoning=False, reasoning_budget=512)
        policy_enabled = ResponsePolicy(enable_reasoning=True, reasoning_budget=512)

        assert policy_disabled.enable_reasoning is False
        assert policy_enabled.enable_reasoning is True
        assert policy_disabled.reasoning_budget == 512
        assert policy_enabled.reasoning_budget == 512


# =============================================================================
# ChatMessage Tests
# =============================================================================

class TestChatMessage:
    """Test ChatMessage immutable data structure."""

    def test_user_message_creation(self):
        """Test creating a user message."""
        msg = ChatMessage(role="user", content="Hello, world!")

        assert msg.role == "user"
        assert msg.content == "Hello, world!"
        assert msg.name is None
        assert msg.tool_calls is None
        assert msg.tool_call_id is None

    def test_assistant_message_with_tool_calls(self):
        """Test assistant message with tool calls."""
        tool_calls = [
            {"id": "call_123", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}
        ]
        msg = ChatMessage(
            role="assistant",
            content="",
            tool_calls=tool_calls,
        )

        assert msg.role == "assistant"
        assert msg.tool_calls == tool_calls

    def test_tool_message_creation(self):
        """Test creating a tool result message."""
        msg = ChatMessage(
            role="tool",
            content='{"temperature": 72, "condition": "sunny"}',
            tool_call_id="call_123",
        )

        assert msg.role == "tool"
        assert msg.content == '{"temperature": 72, "condition": "sunny"}'
        assert msg.tool_call_id == "call_123"

    def test_system_message_creation(self):
        """Test creating a system message."""
        msg = ChatMessage(
            role="system",
            content="You are a helpful assistant.",
            name="system_prompt",
        )

        assert msg.role == "system"
        assert msg.name == "system_prompt"

    def test_to_dict_conversion(self):
        """Test conversion to provider-compatible dict."""
        msg = ChatMessage(
            role="user",
            content="Test message",
            name="test_user",
        )

        result = msg.to_dict()

        assert result == {
            "role": "user",
            "content": "Test message",
            "name": "test_user",
        }

    def test_to_dict_excludes_none_fields(self):
        """Test to_dict excludes None optional fields."""
        msg = ChatMessage(role="assistant", content="Response")

        result = msg.to_dict()

        assert "name" not in result
        assert "tool_calls" not in result
        assert "tool_call_id" not in result

    def test_message_immutability(self):
        """Test that ChatMessage is immutable."""
        msg = ChatMessage(role="user", content="Original")

        with pytest.raises(FrozenInstanceError):
            msg.content = "Modified"

    def test_message_equality(self):
        """Test message equality."""
        msg1 = ChatMessage(role="user", content="Hello")
        msg2 = ChatMessage(role="user", content="Hello")
        msg3 = ChatMessage(role="user", content="World")

        assert msg1 == msg2
        assert msg1 != msg3


# =============================================================================
# ChatRequest Tests
# =============================================================================

class TestChatRequest:
    """Test ChatRequest immutable data structure."""

    def test_request_creation(self, sample_messages, default_policy):
        """Test creating a chat request."""
        request = ChatRequest(
            messages=sample_messages,
            model="gpt-4o-mini",
            policy=default_policy,
        )

        assert request.messages == sample_messages
        assert request.model == "gpt-4o-mini"
        assert request.policy == default_policy
        assert request.metadata == {}
        assert request.request_id != ""

    def test_request_with_metadata(self, sample_messages, default_policy):
        """Test request with custom metadata."""
        metadata = {"user_id": "123", "session_id": "abc", "custom": "data"}
        request = ChatRequest(
            messages=sample_messages,
            model="gpt-4o-mini",
            policy=default_policy,
            metadata=metadata,
        )

        assert request.metadata == metadata

    def test_request_with_custom_id(self, sample_messages, default_policy):
        """Test request with custom request_id."""
        request = ChatRequest(
            messages=sample_messages,
            model="gpt-4o-mini",
            policy=default_policy,
            request_id="custom-request-id",
        )

        assert request.request_id == "custom-request-id"

    def test_request_generates_uuid_when_empty(self, sample_messages, default_policy):
        """Test that request generates UUID when request_id is empty."""
        request = ChatRequest(
            messages=sample_messages,
            model="gpt-4o-mini",
            policy=default_policy,
            request_id="",
        )

        import uuid
        # Should be a valid UUID
        uuid.UUID(request.request_id)

    def test_request_immutability(self, sample_messages, default_policy):
        """Test that ChatRequest is immutable."""
        request = ChatRequest(
            messages=sample_messages,
            model="gpt-4o-mini",
            policy=default_policy,
        )

        with pytest.raises(FrozenInstanceError):
            request.model = "gpt-4o"

        with pytest.raises(FrozenInstanceError):
            request.messages = []

    def test_request_metadata_defaults_to_empty_dict(self, sample_messages, default_policy):
        """Test metadata defaults to empty dict."""
        request = ChatRequest(
            messages=sample_messages,
            model="gpt-4o-mini",
            policy=default_policy,
        )

        assert request.metadata == {}
        assert isinstance(request.metadata, dict)


# =============================================================================
# ChatResponse Tests
# =============================================================================

class TestChatResponse:
    """Test ChatResponse immutable data structure."""

    def test_response_creation(self):
        """Test creating a chat response."""
        response = ChatResponse(
            content="Hello! How can I help you?",
            model="gpt-4o-mini",
            finish_reason="stop",
            usage={"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
            request_id="req-123",
            provider="openai",
            latency_ms=150.5,
        )

        assert response.content == "Hello! How can I help you?"
        assert response.model == "gpt-4o-mini"
        assert response.finish_reason == "stop"
        assert response.usage == {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25}
        assert response.request_id == "req-123"
        assert response.provider == "openai"
        assert response.latency_ms == 150.5
        assert response.tool_calls is None
        assert response.reasoning is None

    def test_response_with_tool_calls(self):
        """Test response with tool calls."""
        tool_calls = [
            {"id": "call_123", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}
        ]
        response = ChatResponse(
            content="",
            model="gpt-4o-mini",
            finish_reason="tool_calls",
            usage={"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            request_id="req-123",
            provider="openai",
            latency_ms=200.0,
            tool_calls=tool_calls,
        )

        assert response.finish_reason == "tool_calls"
        assert response.tool_calls == tool_calls

    def test_response_with_reasoning(self):
        """Test response with reasoning content."""
        response = ChatResponse(
            content="The answer is 42.",
            model="gpt-4o-mini",
            finish_reason="stop",
            usage={"prompt_tokens": 30, "completion_tokens": 40, "total_tokens": 70},
            request_id="req-123",
            provider="openai",
            latency_ms=500.0,
            reasoning="Let me think step by step...",
        )

        assert response.reasoning == "Let me think step by step..."

    def test_response_finish_reasons(self):
        """Test all valid finish reasons."""
        for reason in ["stop", "length", "tool_calls", "content_filter", "error"]:
            response = ChatResponse(
                content="test",
                model="gpt-4o-mini",
                finish_reason=reason,
                usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                request_id="req-123",
                provider="openai",
                latency_ms=100.0,
            )
            assert response.finish_reason == reason

    def test_response_immutability(self):
        """Test that ChatResponse is immutable."""
        response = ChatResponse(
            content="test",
            model="gpt-4o-mini",
            finish_reason="stop",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            request_id="req-123",
            provider="openai",
            latency_ms=100.0,
        )

        with pytest.raises(FrozenInstanceError):
            response.content = "modified"


# =============================================================================
# StreamChunk Tests
# =============================================================================

class TestStreamChunk:
    """Test StreamChunk immutable data structure."""

    def test_basic_chunk(self):
        """Test basic stream chunk."""
        chunk = StreamChunk(delta="Hello")

        assert chunk.delta == "Hello"
        assert chunk.finish_reason is None
        assert chunk.usage is None
        assert chunk.tool_calls is None
        assert chunk.reasoning is None

    def test_final_chunk(self):
        """Test final chunk with finish reason."""
        chunk = StreamChunk(delta="", finish_reason="stop")

        assert chunk.delta == ""
        assert chunk.finish_reason == "stop"

    def test_chunk_with_usage(self):
        """Test chunk with usage info."""
        chunk = StreamChunk(
            delta="final",
            finish_reason="stop",
            usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )

        assert chunk.usage == {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}

    def test_chunk_with_tool_calls(self):
        """Test chunk with tool call delta."""
        tool_calls = [{"index": 0, "delta": {"arguments": '{"city": "NYC"}'}}]
        chunk = StreamChunk(delta="", tool_calls=tool_calls)

        assert chunk.tool_calls == tool_calls

    def test_chunk_with_reasoning(self):
        """Test chunk with reasoning delta."""
        chunk = StreamChunk(delta="", reasoning="Thinking...")

        assert chunk.reasoning == "Thinking..."

    def test_chunk_immutability(self):
        """Test that StreamChunk is immutable."""
        chunk = StreamChunk(delta="test")

        with pytest.raises(FrozenInstanceError):
            chunk.delta = "modified"