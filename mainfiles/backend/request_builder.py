"""
Request builder module for constructing chat requests with policies.

This module provides utilities for building chat requests that incorporate
adaptive response policies based on context, user preferences, and system state.
"""

from __future__ import annotations

from typing import Any

from .domain import ChatMessage, ChatRequest
from .response_policy import ResponsePolicy
from .response_policy import build_chat_request as policy_build_chat_request


def build_chat_request(
    messages: list[ChatMessage],
    model: str,
    policy: ResponsePolicy,
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ChatRequest:
    """
    Build a chat request with the given policy applied.

    This function serves as a wrapper around the policy module's build_chat_request
    to provide a clean interface for API endpoints and other components.

    Args:
        messages: Conversation messages
        model: Model identifier
        policy: Response policy to apply
        user_id: Optional user identifier
        session_id: Optional session identifier
        metadata: Optional metadata dictionary

    Returns:
        ChatRequest with policy applied
    """
    return policy_build_chat_request(
        messages=messages,
        model=model,
        policy=policy,
        user_id=user_id,
        session_id=session_id,
        metadata=metadata,
    )


def build_chat_request_from_conversation(
    messages: list[ChatMessage],
    model: str,
    policy: ResponsePolicy,
    user_id: str | None = None,
    session_id: str | None = None,
) -> ChatRequest:
    """
    Build a chat request from conversation history with policy applied.

    This is a convenience function that mirrors what the integration tests expect.

    Args:
        messages: Conversation messages
        model: Model identifier
        policy: Response policy to apply
        user_id: Optional user identifier
        session_id: Optional session identifier

    Returns:
        ChatRequest with policy applied
    """
    return build_chat_request(
        messages=messages,
        model=model,
        policy=policy,
        user_id=user_id,
        session_id=session_id,
    )