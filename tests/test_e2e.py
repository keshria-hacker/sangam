"""
End-to-end tests for tool execution with providers.

Tests cover:
- Tool execution with OpenAI, Anthropic, and Ollama.
- Tool result formatting and streaming.
- Error handling for unknown tools.
"""
import asyncio
import json
import os
import sys
import base64
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mainfiles"))

# Enable test mode
os.environ["TEST_MODE"] = "1"
# Generate a test master key dynamically - never hardcode
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key

from backend.providers import stream_response_events
from backend.providers.base import ModelInfo, ProviderConfig, ProviderStreamChunk
from backend.tools import ToolCall, ToolResult
from backend.tools.registry import registry
from backend.tools.schemas import ToolDefinition
from backend.response_events import (
    ResponseEventType,
    FinishReason,
    UsageInfo,
    normalize_finish_reason,
    normalize_usage,
)
import litellm


class TestToolExecutionE2E(unittest.IsolatedAsyncioTestCase):
    """End-to-end tests for tool execution with providers."""

    async def asyncSetUp(self):
        """Set up test fixtures."""
        # Clear the registry first to avoid built-in tools interfering
        registry.clear()

        # Register a test tool
        registry.register(
            ToolDefinition(
                name="test_tool",
                description="A test tool for E2E testing.",
                parameters={"type": "object", "properties": {"query": {"type": "string"}}},
                handler=self._test_tool_handler,
            )
        )

    async def asyncTearDown(self):
        """Clean up test fixtures."""
        registry.unregister("test_tool")

    async def _test_tool_handler(self, query: str) -> str:
        """Test tool handler."""
        return f"Test tool result for: {query}"

    def _create_mock_db(self):
        """Create a mock database for the tests."""
        return MagicMock()

    def _make_fake_provider(self, round_responses):
        """Create a fake provider that yields different responses per round."""
        from backend.providers.base import ProviderStreamChunk

        class FakeProvider:
            def __init__(self, config=None, api_key=None):
                self.config = config
                self._api_key = api_key
                self.round = 0

            @property
            def api_key(self):
                return self._api_key

            async def stream_completion(self, *args, **kwargs):
                self.round += 1
                responses = round_responses.get(self.round, round_responses.get("default", []))
                for chunk in responses:
                    if isinstance(chunk, str):
                        yield ProviderStreamChunk(text=chunk)
                    elif isinstance(chunk, ProviderStreamChunk):
                        yield chunk
                    else:
                        yield ProviderStreamChunk(text=str(chunk))

        return FakeProvider

    async def test_tool_execution_with_openai_compatible(self):
        """Test tool execution with OpenAI-compatible provider (e.g., OpenAI, Together, Groq)."""
        # Round 1: tool calls, Round 2: final text response
        round_responses = {
            1: [
                ProviderStreamChunk(
                    tool_calls=[{
                        "id": "test_tool_call_id",
                        "type": "function",
                        "function": {
                            "name": "test_tool",
                            "arguments": json.dumps({"query": "test"}),
                        },
                        "index": 0,
                    }],
                ),
                ProviderStreamChunk(
                    finish_reason=FinishReason.TOOL,
                    terminal=True,
                ),
            ],
            2: [
                ProviderStreamChunk(text="Tool executed successfully"),
                ProviderStreamChunk(
                    finish_reason=FinishReason.STOP,
                    terminal=True,
                ),
            ],
        }

        from backend.providers.registry import registry as provider_registry
        original_get = provider_registry.get_provider_class

        try:
            provider_registry.get_provider_class = lambda pid: self._make_fake_provider(round_responses)

            with patch("backend.providers.resolve_api_key", return_value="test-key"):
                with patch("backend.providers.list_models", return_value=[
                    ModelInfo(
                        id="openai::openai/gpt-4o",
                        name="gpt-4o",
                        provider_id="openai",
                        provider_label="OpenAI",
                        litellm_id="openai/gpt-4o",
                        capabilities=MagicMock(tools=True),
                    )
                ]):
                    events = []
                    async for event in stream_response_events(
                        model_id="openai::openai/gpt-4o",
                        messages=[{"role": "user", "content": "Test tool execution"}],
                        db=self._create_mock_db(),
                    ):
                        events.append(event)

            # Verify tool execution
            tool_start_events = [e for e in events if e.type == ResponseEventType.TOOL_START]
            tool_result_events = [e for e in events if e.type == ResponseEventType.TOOL_RESULT]

            self.assertEqual(len(tool_start_events), 1)
            self.assertEqual(len(tool_result_events), 1)
            self.assertEqual(tool_result_events[0].content, "Test tool result for: test")
        finally:
            provider_registry.get_provider_class = original_get

    async def test_tool_execution_with_anthropic(self):
        """Test tool execution with Anthropic provider."""
        round_responses = {
            1: [
                ProviderStreamChunk(
                    tool_calls=[{
                        "id": "test_tool_call_id",
                        "type": "function",
                        "function": {
                            "name": "test_tool",
                            "arguments": json.dumps({"query": "test"}),
                        },
                        "index": 0,
                    }],
                ),
                ProviderStreamChunk(
                    finish_reason=FinishReason.TOOL,
                    terminal=True,
                ),
            ],
            2: [
                ProviderStreamChunk(text="Tool executed successfully"),
                ProviderStreamChunk(
                    finish_reason=FinishReason.STOP,
                    terminal=True,
                ),
            ],
        }

        from backend.providers.registry import registry as provider_registry
        original_get = provider_registry.get_provider_class

        try:
            provider_registry.get_provider_class = lambda pid: self._make_fake_provider(round_responses)

            with patch("backend.providers.resolve_api_key", return_value="test-key"):
                with patch("backend.providers.list_models", return_value=[
                    ModelInfo(
                        id="anthropic::anthropic/claude-3-5-sonnet",
                        name="claude-3-5-sonnet",
                        provider_id="anthropic",
                        provider_label="Anthropic",
                        litellm_id="anthropic/claude-3-5-sonnet",
                        capabilities=MagicMock(tools=True),
                    )
                ]):
                    events = []
                    async for event in stream_response_events(
                        model_id="anthropic::anthropic/claude-3-5-sonnet",
                        messages=[{"role": "user", "content": "Test tool execution"}],
                        db=self._create_mock_db(),
                    ):
                        events.append(event)

            # Verify tool execution
            tool_start_events = [e for e in events if e.type == ResponseEventType.TOOL_START]
            tool_result_events = [e for e in events if e.type == ResponseEventType.TOOL_RESULT]

            self.assertEqual(len(tool_start_events), 1)
            self.assertEqual(len(tool_result_events), 1)
            self.assertEqual(tool_result_events[0].content, "Test tool result for: test")
        finally:
            provider_registry.get_provider_class = original_get

    async def test_tool_execution_with_ollama(self):
        """Test tool execution with Ollama provider."""
        round_responses = {
            1: [
                ProviderStreamChunk(
                    tool_calls=[{
                        "id": "test_tool_call_id",
                        "type": "function",
                        "function": {
                            "name": "test_tool",
                            "arguments": json.dumps({"query": "test"}),
                        },
                        "index": 0,
                    }],
                ),
                ProviderStreamChunk(
                    finish_reason=FinishReason.TOOL,
                    terminal=True,
                ),
            ],
            2: [
                ProviderStreamChunk(text="Tool executed successfully"),
                ProviderStreamChunk(
                    finish_reason=FinishReason.STOP,
                    terminal=True,
                ),
            ],
        }

        from backend.providers.registry import registry as provider_registry
        original_get = provider_registry.get_provider_class

        try:
            provider_registry.get_provider_class = lambda pid: self._make_fake_provider(round_responses)

            with patch("backend.providers.resolve_api_key", return_value=None):  # Local provider
                with patch("backend.providers.list_models", return_value=[
                    ModelInfo(
                        id="ollama::ollama/llama3.1",
                        name="llama3.1",
                        provider_id="ollama",
                        provider_label="Ollama",
                        litellm_id="ollama/llama3.1",
                        capabilities=MagicMock(tools=True),
                    )
                ]):
                    events = []
                    async for event in stream_response_events(
                        model_id="ollama::ollama/llama3.1",
                        messages=[{"role": "user", "content": "Test tool execution"}],
                        db=self._create_mock_db(),
                    ):
                        events.append(event)

            # Verify tool execution
            tool_start_events = [e for e in events if e.type == ResponseEventType.TOOL_START]
            tool_result_events = [e for e in events if e.type == ResponseEventType.TOOL_RESULT]

            self.assertEqual(len(tool_start_events), 1)
            self.assertEqual(len(tool_result_events), 1)
            self.assertEqual(tool_result_events[0].content, "Test tool result for: test")
        finally:
            provider_registry.get_provider_class = original_get

    async def test_unknown_tool_error(self):
        """Test error handling for unknown tools."""
        round_responses = {
            1: [
                ProviderStreamChunk(
                    tool_calls=[{
                        "id": "test_tool_call_id",
                        "type": "function",
                        "function": {
                            "name": "unknown_tool",
                            "arguments": json.dumps({}),
                        },
                        "index": 0,
                    }],
                ),
                ProviderStreamChunk(
                    finish_reason=FinishReason.TOOL,
                    terminal=True,
                ),
            ],
            2: [
                ProviderStreamChunk(text="Tool error handled"),
                ProviderStreamChunk(
                    finish_reason=FinishReason.STOP,
                    terminal=True,
                ),
            ],
        }

        from backend.providers.registry import registry as provider_registry
        original_get = provider_registry.get_provider_class

        try:
            provider_registry.get_provider_class = lambda pid: self._make_fake_provider(round_responses)

            with patch("backend.providers.resolve_api_key", return_value="test-key"):
                with patch("backend.providers.list_models", return_value=[
                    ModelInfo(
                        id="openai::openai/gpt-4o",
                        name="gpt-4o",
                        provider_id="openai",
                        provider_label="OpenAI",
                        litellm_id="openai/gpt-4o",
                        capabilities=MagicMock(tools=True),
                    )
                ]):
                    events = []
                    async for event in stream_response_events(
                        model_id="openai::openai/gpt-4o",
                        messages=[{"role": "user", "content": "Test unknown tool"}],
                        db=self._create_mock_db(),
                    ):
                        events.append(event)

            # Verify error handling
            tool_result_events = [e for e in events if e.type == ResponseEventType.TOOL_RESULT]
            self.assertEqual(len(tool_result_events), 1)
            self.assertTrue(tool_result_events[0].metadata.get("is_error", False))
            self.assertIn("Unknown tool", tool_result_events[0].content)
        finally:
            provider_registry.get_provider_class = original_get


if __name__ == "__main__":
    unittest.main()