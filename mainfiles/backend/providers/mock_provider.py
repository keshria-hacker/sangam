"""
Mock LLM provider for smoke testing.

Registered ONLY when ``SANGAM_MOCK_PROVIDER=1`` is set in the environment.
This is test infrastructure, not a user-facing feature: it lets the Playwright
smoke test send a real chat message through the real backend completion path
(chat_stream_routes -> llm.stream_completion -> provider) without an LLM key.

The model answers with a short canned response that echoes the last user
message, so the frontend streaming path is exercised end to end.
"""
from __future__ import annotations

import os
from typing import Any, AsyncGenerator

from .base import BaseProvider, ModelInfo, ProviderStreamChunk

MOCK_MODEL_ID = "mock::smoke-test"
MOCK_MODEL_NAME = "Mock (smoke test)"


def mock_enabled() -> bool:
    return os.environ.get("SANGAM_MOCK_PROVIDER") == "1"


def mock_model_info() -> ModelInfo:
    return ModelInfo(
        id=MOCK_MODEL_ID,
        name=MOCK_MODEL_NAME,
        provider_id="mock",
        provider_label="Mock",
        litellm_id="mock/smoke-test",
    )


class MockProvider(BaseProvider):
    """Canned streaming provider for the smoke test."""

    async def list_models(self, api_key: str | None = None) -> list[ModelInfo]:
        return [mock_model_info()]

    async def stream_response_events(  # noqa: PLR0913
        self,
        model_id: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        **kwargs: Any,
    ):
        """Yield canonical response events for the canned reply."""
        # Import here to avoid circular imports.
        from backend.response_events import FinishReason, ResponseEventBuilder

        last_user = ""
        for m in reversed(messages or []):
            if m.get("role") == "user":
                last_user = str(m.get("content", ""))[:200]
                break
        reply = (
            "Smoke test reply. You said: "
            + (last_user or "(no message)")
            + " This is a canned mock-provider response."
        )
        builder = ResponseEventBuilder(
            provider="mock",
            model=model_id,
            message_id=kwargs.get("message_id"),
            request_id=kwargs.get("request_id"),
        )
        yield builder.message_start()
        yield builder.text_start()
        # Yield in small chunks to exercise the streaming path.
        for i in range(0, len(reply), 24):
            for event in builder.text_delta(reply[i : i + 24]):
                yield event
        text_end = builder.text_end()
        if text_end:
            yield text_end
        yield builder.message_end(FinishReason.STOP)

    async def stream_completion(  # noqa: PLR0913
        self,
        model_id: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        api_key: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str | ProviderStreamChunk]:
        last_user = ""
        for m in reversed(messages or []):
            if m.get("role") == "user":
                last_user = str(m.get("content", ""))[:200]
                break
        reply = (
            "Smoke test reply. You said: "
            + (last_user or "(no message)")
            + " This is a canned mock-provider response."
        )
        # Yield in small chunks to exercise the streaming path.
        for i in range(0, len(reply), 24):
            yield ProviderStreamChunk(text=reply[i : i + 24])
        # Terminal chunk: without a finish_reason the response-event adapter
        # treats the stream as broken ("Stream terminated without
        # finish_reason") and the UI shows an error instead of the reply.
        from backend.response_events import FinishReason

        yield ProviderStreamChunk(text="", finish_reason=FinishReason.STOP)
