"""Canonical Sangam response event protocol.

This module is intentionally provider-independent. Provider adapters may still
parse provider-specific chunks internally, but application transport and UI code
should consume these events instead of raw provider payloads.
"""
from __future__ import annotations

import re
import uuid
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field


class ResponseEventType(StrEnum):
    MESSAGE_START = "message_start"
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"
    REASONING_START = "reasoning_start"
    REASONING_DELTA = "reasoning_delta"
    REASONING_END = "reasoning_end"
    TOOL_START = "tool_start"
    TOOL_INPUT_DELTA = "tool_input_delta"
    TOOL_END = "tool_end"
    TOOL_RESULT = "tool_result"
    CITATION = "citation"
    CLARIFICATION_REQUEST = "clarification_request"
    ARTIFACT_START = "artifact_start"
    ARTIFACT_DELTA = "artifact_delta"
    ARTIFACT_END = "artifact_end"
    USAGE = "usage"
    MESSAGE_END = "message_end"
    ERROR = "error"


class FinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    TOOL = "tool"
    CANCELLED = "cancelled"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"
    UNKNOWN = "unknown"


class ErrorCategory(StrEnum):
    AUTHENTICATION_ERROR = "authentication_error"
    RATE_LIMIT = "rate_limit"
    QUOTA_EXCEEDED = "quota_exceeded"
    INVALID_REQUEST = "invalid_request"
    MODEL_NOT_FOUND = "model_not_found"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    CONTEXT_LENGTH = "context_length"
    CONTENT_FILTER = "content_filter"
    STREAM_ERROR = "stream_error"
    UNKNOWN = "unknown"


class ModelCapabilities(BaseModel):
    """Forward-looking model capability flags."""

    streaming: bool = True
    tools: bool = False
    reasoning: bool = False
    vision: bool = False
    documents: bool = False
    citations: bool = False
    structured_output: bool = False


class UsageInfo(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None


class NormalizedError(BaseModel):
    category: ErrorCategory = ErrorCategory.UNKNOWN
    message: str
    retryable: bool = False
    provider: str | None = None
    model: str | None = None
    status: int | None = None
    code: str | None = None


class ResponseEvent(BaseModel):
    """Single canonical response event sent through the response pipeline."""

    model_config = ConfigDict(use_enum_values=True)

    type: ResponseEventType
    message_id: str
    sequence: int
    request_id: str | None = None
    provider: str | None = None
    model: str | None = None
    content: str | None = None
    usage: UsageInfo | None = None
    finish_reason: FinishReason | None = None
    error: NormalizedError | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_json(self) -> str:
        return self.model_dump_json(exclude_none=True)


class ResponseEventBuilder:
    """Small lifecycle/sequencing guard for one assistant response."""

    def __init__(
        self,
        provider: str | None,
        model: str | None,
        message_id: str | None = None,
        request_id: str | None = None,
    ):
        self.provider = provider
        self.model = model
        self.message_id = message_id or uuid.uuid4().hex[:12]
        self.request_id = request_id or uuid.uuid4().hex[:12]
        self.sequence = 0
        self._message_started = False
        self._message_terminal = False
        self._text_open = False
        self._reasoning_open = False

    def event(self, event_type: ResponseEventType, **kwargs: Any) -> ResponseEvent:
        if self._message_terminal:
            raise RuntimeError("Cannot emit events after response termination")
        if event_type == ResponseEventType.MESSAGE_START:
            if self._message_started:
                raise RuntimeError("Response has already started")
            self._message_started = True
        elif not self._message_started:
            raise RuntimeError("message_start must be the first response event")
        ev = ResponseEvent(
            type=event_type,
            message_id=self.message_id,
            request_id=self.request_id,
            sequence=self.sequence,
            provider=self.provider,
            model=self.model,
            **kwargs,
        )
        self.sequence += 1
        if event_type in {ResponseEventType.MESSAGE_END, ResponseEventType.ERROR}:
            self._message_terminal = True
        return ev

    def message_start(self) -> ResponseEvent:
        return self.event(ResponseEventType.MESSAGE_START)

    def text_start(self) -> ResponseEvent | None:
        if self._text_open:
            return None
        event = self.event(ResponseEventType.TEXT_START)
        self._text_open = True
        return event

    def text_delta(self, content: str) -> list[ResponseEvent]:
        if not content:
            return []
        events: list[ResponseEvent] = []
        start = self.text_start()
        if start is not None:
            events.append(start)
        events.append(self.event(ResponseEventType.TEXT_DELTA, content=content))
        return events

    def text_end(self) -> ResponseEvent | None:
        if not self._text_open:
            return None
        self._text_open = False
        return self.event(ResponseEventType.TEXT_END)

    def reasoning_delta(self, content: str) -> list[ResponseEvent]:
        if not content:
            return []
        events: list[ResponseEvent] = []
        if not self._reasoning_open:
            events.append(self.event(ResponseEventType.REASONING_START))
            self._reasoning_open = True
        events.append(self.event(ResponseEventType.REASONING_DELTA, content=content))
        return events

    def reasoning_end(self) -> ResponseEvent | None:
        if not self._reasoning_open:
            return None
        self._reasoning_open = False
        return self.event(ResponseEventType.REASONING_END)

    def usage(self, usage: UsageInfo) -> ResponseEvent:
        return self.event(ResponseEventType.USAGE, usage=usage)

    def message_end(self, finish_reason: FinishReason = FinishReason.STOP, metadata: dict[str, Any] | None = None) -> ResponseEvent:
        if self._reasoning_open or self._text_open:
            raise RuntimeError("Open response blocks must end before message_end")
        return self.event(ResponseEventType.MESSAGE_END, finish_reason=finish_reason, metadata=metadata or {})

    def error(self, error: NormalizedError) -> ResponseEvent:
        return self.event(ResponseEventType.ERROR, finish_reason=FinishReason.ERROR, error=error)


_SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9-_]{20,}"),
    re.compile(r"sk-ant-[a-zA-Z0-9-_]{20,}"),
    re.compile(r"AIza[a-zA-Z0-9-_]{35}"),
    re.compile(r"nvapi-[a-zA-Z0-9-_]{20,}"),
    re.compile(r"tgp_v1_[a-zA-Z0-9-_]{20,}"),
    re.compile(r"gsk_[a-zA-Z0-9-_]{20,}"),
    re.compile(r"sk-or-v1-[a-zA-Z0-9-_]{20,}"),
    re.compile(r"Bearer\s+[a-zA-Z0-9\-_=]{20,}"),
]


def redact_secrets(text: str) -> str:
    out = text or ""
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("***REDACTED***", out)
    return out


def normalize_finish_reason(reason: Any) -> FinishReason:  # noqa: PLR0911
    value = str(reason or "").lower()
    if value in {"stop", "end_turn", "done", "complete", "completed"}:
        return FinishReason.STOP
    if value in {"length", "max_tokens", "max_output_tokens", "token_limit"}:
        return FinishReason.LENGTH
    if value in {"tool_calls", "tool_use", "function_call", "tool"}:
        return FinishReason.TOOL
    if value in {"cancelled", "canceled", "abort", "aborted"}:
        return FinishReason.CANCELLED
    if value in {"content_filter", "safety", "blocked", "recitation"}:
        return FinishReason.CONTENT_FILTER
    if value in {"error", "failed"}:
        return FinishReason.ERROR
    return FinishReason.UNKNOWN if value else FinishReason.STOP


def normalize_usage(raw: Any) -> UsageInfo | None:
    if raw is None:
        return None
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    elif not isinstance(raw, dict):
        raw = {k: getattr(raw, k) for k in dir(raw) if not k.startswith("_")}

    def first(*keys: str) -> int | None:
        for key in keys:
            val = raw.get(key)
            if isinstance(val, int):
                return val
        return None

    prompt_details = raw.get("prompt_tokens_details") or raw.get("input_tokens_details") or {}
    completion_details = raw.get("completion_tokens_details") or raw.get("output_tokens_details") or {}
    usage = UsageInfo(
        input_tokens=first("input_tokens", "prompt_tokens"),
        output_tokens=first("output_tokens", "completion_tokens"),
        total_tokens=first("total_tokens"),
        cached_input_tokens=prompt_details.get("cached_tokens") if isinstance(prompt_details, dict) else None,
        reasoning_tokens=completion_details.get("reasoning_tokens") if isinstance(completion_details, dict) else None,
    )
    return usage if any(v is not None for v in usage.model_dump().values()) else None


def normalize_error(  # noqa: PLR0912
    exc: BaseException, provider: str | None = None, model: str | None = None
) -> NormalizedError:
    status = None
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
    msg = redact_secrets(str(exc))
    lower = msg.lower()
    category = ErrorCategory.UNKNOWN
    retryable = False
    code = None
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            body = response.json()
            raw_code = body.get("error", {}).get("code") if isinstance(body, dict) else None
            code = str(raw_code) if raw_code is not None else None
        except (ValueError, TypeError, AttributeError):
            code = None

    if "quota" in lower or "insufficient_quota" in lower or code == "insufficient_quota":
        category = ErrorCategory.QUOTA_EXCEEDED
    elif status in {401, 403} or "api key" in lower or "unauthorized" in lower or "authentication" in lower:
        category = ErrorCategory.AUTHENTICATION_ERROR
    elif status == 429 or "rate limit" in lower:
        category = ErrorCategory.RATE_LIMIT
        retryable = True
    elif status == 404 or "model not found" in lower or "does not exist" in lower or "not available" in lower:
        category = ErrorCategory.MODEL_NOT_FOUND
    elif isinstance(exc, (TimeoutError, httpx.TimeoutException)) or "timeout" in lower or "timed out" in lower:
        category = ErrorCategory.TIMEOUT
        retryable = True
    elif isinstance(exc, httpx.NetworkError) or "connection" in lower or "network" in lower:
        category = ErrorCategory.NETWORK_ERROR
        retryable = True
    elif status and 500 <= status <= 599:
        category = ErrorCategory.PROVIDER_UNAVAILABLE
        retryable = True
    elif "context" in lower and ("length" in lower or "token" in lower):
        category = ErrorCategory.CONTEXT_LENGTH
    elif "content filter" in lower or "safety" in lower or "blocked" in lower:
        category = ErrorCategory.CONTENT_FILTER
    elif "json" in lower or "stream" in lower or "chunk" in lower:
        category = ErrorCategory.STREAM_ERROR
    elif status and 400 <= status <= 499:
        category = ErrorCategory.INVALID_REQUEST
    return NormalizedError(
        category=category,
        message=msg or "Provider request failed",
        retryable=retryable,
        provider=provider,
        model=model,
        status=status,
        code=code,
    )


def model_capabilities_from_flags(  # noqa: PLR0913
    *,
    streaming: bool = True,
    tools: bool = False,
    reasoning: bool = False,
    vision: bool = False,
    documents: bool = False,
    citations: bool = False,
    structured_output: bool = False,
) -> ModelCapabilities:
    return ModelCapabilities(
        streaming=streaming,
        tools=tools,
        reasoning=reasoning,
        vision=vision,
        documents=documents,
        citations=citations,
        structured_output=structured_output,
    )
