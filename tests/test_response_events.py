import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mainfiles"))

os.environ["TEST_MODE"] = "1"
from cryptography.fernet import Fernet
_test_key = Fernet.generate_key().decode()
os.environ["MASTER_KEY"] = _test_key

import backend.providers as providers  # noqa: E402
from backend.providers.base import ProviderStreamChunk  # noqa: E402
from backend.response_events import (  # noqa: E402
    ErrorCategory,
    FinishReason,
    ResponseEventBuilder,
    ResponseEventType,
    normalize_error,
    normalize_finish_reason,
    normalize_usage,
)
from backend.providers.key_resolver import resolve_api_key  # noqa: E402


class ResponseEventLifecycleTests(unittest.TestCase):
    def test_lifecycle_and_ordering(self):
        builder = ResponseEventBuilder(provider="openai", model="openai::openai/gpt-4o", message_id="m1")
        events = [builder.message_start()]
        events.extend(builder.text_delta("Hel"))
        events.extend(builder.text_delta("lo"))
        text_end = builder.text_end()
        if text_end:
            events.append(text_end)
        events.append(builder.message_end(FinishReason.STOP))

        self.assertEqual([e.type for e in events], [
            ResponseEventType.MESSAGE_START,
            ResponseEventType.TEXT_START,
            ResponseEventType.TEXT_DELTA,
            ResponseEventType.TEXT_DELTA,
            ResponseEventType.TEXT_END,
            ResponseEventType.MESSAGE_END,
        ])
        self.assertEqual([e.sequence for e in events], list(range(len(events))))
        self.assertTrue(all(e.message_id == "m1" for e in events))

    def test_no_text_after_terminal(self):
        builder = ResponseEventBuilder(provider="openai", model="m")
        builder.message_start()
        builder.message_end()
        with self.assertRaises(RuntimeError):
            builder.text_delta("late")

    def test_message_start_is_required_and_cannot_repeat(self):
        builder = ResponseEventBuilder(provider="openai", model="m")
        with self.assertRaises(RuntimeError):
            builder.text_delta("early")
        builder.message_start()
        events = builder.text_delta("valid")
        self.assertEqual(
            [event.type for event in events],
            [ResponseEventType.TEXT_START, ResponseEventType.TEXT_DELTA],
        )
        with self.assertRaises(RuntimeError):
            builder.message_start()

    def test_open_blocks_must_close_before_message_end(self):
        builder = ResponseEventBuilder(provider="openai", model="m")
        builder.message_start()
        builder.text_delta("partial")
        with self.assertRaises(RuntimeError):
            builder.message_end()


class NormalizationHelpersTests(unittest.TestCase):
    def test_finish_reasons(self):
        self.assertEqual(normalize_finish_reason("stop"), FinishReason.STOP)
        self.assertEqual(normalize_finish_reason("max_tokens"), FinishReason.LENGTH)
        self.assertEqual(normalize_finish_reason("tool_calls"), FinishReason.TOOL)
        self.assertEqual(normalize_finish_reason("content_filter"), FinishReason.CONTENT_FILTER)
        self.assertEqual(normalize_finish_reason("aborted"), FinishReason.CANCELLED)
        self.assertEqual(normalize_finish_reason("something-new"), FinishReason.UNKNOWN)

    def test_usage_does_not_fabricate_missing_fields(self):
        usage = normalize_usage({"prompt_tokens": 3, "completion_tokens": 4})
        self.assertEqual(usage.input_tokens, 3)
        self.assertEqual(usage.output_tokens, 4)
        self.assertIsNone(usage.total_tokens)
        self.assertIsNone(normalize_usage({}))

    def test_error_categories_and_redaction(self):
        cases = [
            (RuntimeError("Invalid API key sk-testabcdefghijklmnopqrstuvwxyz"), ErrorCategory.AUTHENTICATION_ERROR),
            (RuntimeError("rate limit exceeded"), ErrorCategory.RATE_LIMIT),
            (RuntimeError("provider timeout"), ErrorCategory.TIMEOUT),
            (RuntimeError("model not found"), ErrorCategory.MODEL_NOT_FOUND),
            (RuntimeError("malformed json chunk in stream"), ErrorCategory.STREAM_ERROR),
        ]
        for exc, category in cases:
            err = normalize_error(exc, provider="openai", model="m")
            self.assertEqual(err.category, category)
            self.assertNotIn("sk-test", err.message)


class ProviderEventFacadeTests(unittest.IsolatedAsyncioTestCase):
    def _make_fake_provider(self, fake_stream_completion):
        """Create a fake provider class with the given stream_completion method."""
        from backend.providers.base import ProviderStreamChunk

        class FakeProvider:
            def __init__(self, config=None, api_key=None):
                self.config = config
                self._api_key = api_key

            @property
            def api_key(self):
                return self._api_key

            async def stream_completion(self, *args, **kwargs):
                async for chunk in fake_stream_completion(*args, **kwargs):
                    if isinstance(chunk, str):
                        yield ProviderStreamChunk(text=chunk)
                    elif isinstance(chunk, ProviderStreamChunk):
                        yield chunk
                    else:
                        yield ProviderStreamChunk(text=str(chunk))

        return FakeProvider

    async def _collect_for_provider(self, provider_id: str, fake_stream_completion, message_id: str | None = None):
        FakeProvider = self._make_fake_provider(fake_stream_completion)

        import backend.providers as providers_module
        from backend.providers.registry import registry

        # Store original
        original_get = registry.get_provider_class

        try:
            # Mock the registry to return our fake provider
            registry.get_provider_class = lambda pid: FakeProvider

            with patch.object(providers_module, "resolve_api_key", return_value="test-key"):
                with patch.object(providers_module, "list_models", return_value=[]):
                    events = []
                    async for event in providers_module.stream_response_events(
                        f"{provider_id}::{provider_id}/model",
                        [{"role": "user", "content": "hi"}],
                        MagicMock(),  # db mock - won't be used due to patch
                        message_id=message_id,
                    ):
                        events.append(event)
            return events
        finally:
            registry.get_provider_class = original_get

    async def test_supported_provider_text_becomes_canonical_text_delta(self):
        async def fake_stream_completion(*args, **kwargs):
            yield "Hello"
            yield " world"
            # Send terminal chunk to indicate normal completion
            from backend.providers.base import ProviderStreamChunk
            from backend.response_events import FinishReason
            yield ProviderStreamChunk(finish_reason=FinishReason.STOP, terminal=True)

        provider_ids = [
            "openai", "anthropic", "gemini", "nvidia", "together",
            "groq", "openrouter", "deepseek", "mistral", "ollama", "omniroute",
        ]
        for provider_id in provider_ids:
            events = await self._collect_for_provider(provider_id, fake_stream_completion)
            text = "".join(e.content or "" for e in events if e.type == ResponseEventType.TEXT_DELTA)
            self.assertEqual(text, "Hello world")
            self.assertEqual(events[0].type, ResponseEventType.MESSAGE_START)
            self.assertEqual(events[-1].type, ResponseEventType.MESSAGE_END)
            self.assertEqual([e.sequence for e in events], list(range(len(events))))

    async def test_stream_interruption_becomes_error_event(self):
        async def broken_stream_completion(*args, **kwargs):
            yield "partial"
            raise RuntimeError("malformed json chunk in stream")

        events = await self._collect_for_provider("openai", broken_stream_completion)
        self.assertEqual(events[-1].type, ResponseEventType.ERROR)
        self.assertEqual(events[-1].error.category, ErrorCategory.STREAM_ERROR)

    async def test_typed_provider_chunk_preserves_usage_and_finish_reason(self):
        async def typed_stream_completion(*args, **kwargs):
            yield ProviderStreamChunk(text="Hello")
            yield ProviderStreamChunk(
                finish_reason=FinishReason.LENGTH,
                usage=normalize_usage({"prompt_tokens": 3, "completion_tokens": 4}),
                metadata={"provider_finish_reason": "max_tokens"},
                terminal=True,
            )

        events = await self._collect_for_provider("openai", typed_stream_completion, message_id="assistant-1")

        self.assertEqual([event.sequence for event in events], list(range(len(events))))
        self.assertTrue(all(event.message_id == "assistant-1" for event in events))
        usage_event = next(event for event in events if event.type == ResponseEventType.USAGE)
        self.assertEqual(usage_event.usage.input_tokens, 3)
        self.assertEqual(usage_event.usage.output_tokens, 4)
        self.assertEqual(events[-1].finish_reason, FinishReason.LENGTH)
        self.assertEqual(events[-1].metadata["provider_finish_reason"], "max_tokens")

    async def test_typed_stream_without_terminal_becomes_stream_error(self):
        async def incomplete_stream_completion(*args, **kwargs):
            yield ProviderStreamChunk(text="partial")

        events = await self._collect_for_provider("openai", incomplete_stream_completion)

        self.assertEqual(events[-1].type, ResponseEventType.ERROR)
        self.assertEqual(events[-1].error.category, ErrorCategory.STREAM_ERROR)


if __name__ == "__main__":
    unittest.main()
