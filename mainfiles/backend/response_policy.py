"""
Response policy module for Phase 4 Adaptive Response Intelligence.

This module provides policy selection, adaptation, and management logic
for dynamically adjusting LLM behavior based on context, user tier,
and performance metrics.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Shared domain types live in one canonical place (domain.py)
from .domain import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    StreamChunk,
    LLMProvider,
)

# Define ResponsePolicy in this module to avoid circular imports and ensure
# we're using the correct class throughout the backend
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


@dataclass
class PolicySelector:
    """Selects appropriate policies based on context and user characteristics."""

    def select(
        self,
        query: str,
        context_length: int = 0,
        user_tier: str = "free",
        enable_reasoning: bool | None = None,
    ) -> ResponsePolicy:
        """
        Select policy based on query complexity, context length, and user tier.

        Args:
            query: The user's query/text
            context_length: Current conversation context length in tokens
            user_tier: User's subscription tier (free, pro, enterprise)
            enable_reasoning: Override for reasoning enablement

        Returns:
            Selected ResponsePolicy
        """
        # Determine base values based on user tier
        if user_tier == "enterprise":
            max_tokens = 8192
            temperature = 0.7
        elif user_tier == "pro":
            max_tokens = 4096
            temperature = 0.7
        else:  # free
            max_tokens = 2048
            temperature = 0.5

        # Adjust based on context length (leave room for response)
        if context_length > 6000:
            max_tokens = min(max_tokens, 1024)
            temperature = max(temperature - 0.2, 0.1)
        elif context_length > 3000:
            max_tokens = min(max_tokens, 2048)

        # Adjust based on query characteristics
        query_lower = query.lower().strip()
        reasoning_enabled = None  # Will determine if we should enable reasoning

        # Simple queries get faster, more deterministic responses
        if len(query) < 20 and any(word in query_lower for word in
                                ["hi", "hello", "hey", "thanks", "thank you", "bye", "goodbye"]):
            max_tokens = min(max_tokens, 512)
            temperature = 0.3

        # Code generation requests
        elif any(word in query_lower for word in
                ["code", "function", "class", "debug", "error", "fix", "implement", "write", "script"]):
            max_tokens = min(max_tokens * 2, 8192)
            temperature = 0.2  # Lower temp for code
            reasoning_enabled = True

        # Creative writing requests
        elif any(word in query_lower for word in
                ["story", "poem", "creative", "imagine", "write", "essay", "narrative"]):
            temperature = min(temperature + 0.2, 1.0)
            max_tokens = min(max_tokens * 1.5, 8192)
            reasoning_enabled = False  # Creative usually doesn't need reasoning

        # Complex reasoning requests
        elif any(word in query_lower for word in
                ["explain", "analyze", "compare", "evaluate", "reason", "logic", "prove", "theorem"]):
            max_tokens = min(max_tokens * 1.5, 8192)
            temperature = 0.4
            reasoning_enabled = True

        # Mathematical/logical requests
        elif any(word in query_lower for word in
                ["calculate", "compute", "math", "equation", "solve", "proof", "logic"]):
            temperature = 0.1  # Very deterministic for math
            max_tokens = min(max_tokens, 2048)
            reasoning_enabled = True

        # Apply reasoning override if specified
        if enable_reasoning is not None:
            reasoning_enabled = enable_reasoning

        # Set reasoning budget if reasoning is enabled
        reasoning_budget = 0
        if reasoning_enabled or (reasoning_enabled is None and False):  # Default to False
            reasoning_budget = min(2048, max_tokens // 4)

        # Create and return new policy instance
        return ResponsePolicy(
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=0.9,
            presence_penalty=0.0,
            frequency_penalty=0.0,
            stop_sequences=[],
            stream=True,
            adaptive_timeout=30.0,
            fallback_provider=None,
            enable_reasoning=reasoning_enabled or False,
            reasoning_budget=reasoning_budget,
        )


@dataclass
class PolicyAdapter:
    """Adapts policies dynamically during conversation based on performance."""

    def __init__(self):
        self.performance_history: List[Dict[str, Any]] = []

    def adapt_policy_on_timeout(self, policy: ResponsePolicy, error: Exception) -> ResponsePolicy:
        """Adapt policy when requests timeout."""
        if "timeout" in str(error).lower() or isinstance(error, TimeoutError):
            # Reduce max_tokens and increase timeout
            adapted = ResponsePolicy(
                max_tokens=max(512, policy.max_tokens // 2),
                temperature=policy.temperature,
                top_p=policy.top_p,
                presence_penalty=policy.presence_penalty,
                frequency_penalty=policy.frequency_penalty,
                stop_sequences=policy.stop_sequences.copy(),
                stream=policy.stream,
                adaptive_timeout=min(60.0, policy.adaptive_timeout * 1.5),
                fallback_provider=policy.fallback_provider,
                enable_reasoning=policy.enable_reasoning,
                reasoning_budget=max(128, policy.reasoning_budget // 2),
            )
            return adapted
        return policy

    def adapt_policy_on_error_rate(self, policy: ResponsePolicy, error_rate: float) -> ResponsePolicy:
        """Adapt policy when error rate increases."""
        if error_rate > 0.5:  # High error rate
            # More conservative settings
            adapted = ResponsePolicy(
                max_tokens=max(512, policy.max_tokens // 2),
                temperature=max(0.1, policy.temperature - 0.2),
                top_p=policy.top_p,
                presence_penalty=policy.presence_penalty,
                frequency_penalty=policy.frequency_penalty,
                stop_sequences=policy.stop_sequences.copy(),
                stream=policy.stream,
                adaptive_timeout=policy.adaptive_timeout,
                fallback_provider=policy.fallback_provider,
                enable_reasoning=False,  # Disable reasoning to reduce complexity
                reasoning_budget=0,
            )
            return adapted
        elif error_rate > 0.2:  # Moderate error rate
            # Slightly more conservative
            adapted = ResponsePolicy(
                max_tokens=max(1024, int(policy.max_tokens * 0.75)),
                temperature=policy.temperature,
                top_p=policy.top_p,
                presence_penalty=policy.presence_penalty,
                frequency_penalty=policy.frequency_penalty,
                stop_sequences=policy.stop_sequences.copy(),
                stream=policy.stream,
                adaptive_timeout=policy.adaptive_timeout * 1.2,
                fallback_provider=policy.fallback_provider,
                enable_reasoning=policy.enable_reasoning,
                reasoning_budget=max(128, int(policy.reasoning_budget * 0.75)),
            )
            return adapted
        return policy

    def adapt_policy_on_latency(self, policy: ResponsePolicy, avg_latency: float) -> ResponsePolicy:
        """Adapt policy when latency is high."""
        # Latency in seconds, adapt if > 5s average
        if avg_latency > 5.0:
            adapted = ResponsePolicy(
                max_tokens=max(512, policy.max_tokens // 2),
                temperature=policy.temperature,
                top_p=policy.top_p,
                presence_penalty=policy.presence_penalty,
                frequency_penalty=policy.frequency_penalty,
                stop_sequences=policy.stop_sequences.copy(),
                stream=policy.stream,
                adaptive_timeout=min(30.0, policy.adaptive_timeout * 1.3),
                fallback_provider=policy.fallback_provider,
                enable_reasoning=policy.enable_reasoning,
                reasoning_budget=max(128, policy.reasoning_budget // 2),
            )
            return adapted
        return policy

    def adapt_policy_reduces_tokens_on_length_finish(self, policy: ResponsePolicy, finish_reason: str) -> ResponsePolicy:
        """Reduce max_tokens when finish_reason is 'length' (hit token limit)."""
        if finish_reason == "length":
            adapted = ResponsePolicy(
                max_tokens=max(512, policy.max_tokens // 2),
                temperature=policy.temperature,
                top_p=policy.top_p,
                presence_penalty=policy.presence_penalty,
                frequency_penalty=policy.frequency_penalty,
                stop_sequences=policy.stop_sequences.copy(),
                stream=policy.stream,
                adaptive_timeout=policy.adaptive_timeout,
                fallback_provider=policy.fallback_provider,
                enable_reasoning=policy.enable_reasoning,
                reasoning_budget=max(128, policy.reasoning_budget // 2),
            )
            return adapted
        return policy

    def adapt_policy_increases_temperature_on_repetition(self, policy: ResponsePolicy, repetition_score: float) -> ResponsePolicy:
        """Increase temperature when responses are repetitive."""
        if repetition_score > 0.7:  # High repetition
            adapted = ResponsePolicy(
                max_tokens=policy.max_tokens,
                temperature=min(1.0, policy.temperature + 0.3),
                top_p=policy.top_p,
                presence_penalty=policy.presence_penalty,
                frequency_penalty=policy.frequency_penalty,
                stop_sequences=policy.stop_sequences.copy(),
                stream=policy.stream,
                adaptive_timeout=policy.adaptive_timeout,
                fallback_provider=policy.fallback_provider,
                enable_reasoning=policy.enable_reasoning,
                reasoning_budget=policy.reasoning_budget,
            )
            return adapted
        return policy

    def adapt_policy_enables_reasoning_on_complex_queries(self, policy: ResponsePolicy, query: str) -> ResponsePolicy:
        """Enable reasoning for detected complex queries."""
        complex_indicators = [
            "explain", "analyze", "compare", "evaluate", "reason", "logic",
            "prove", "theorem", "derive", "calculate", "compute", "solve",
            "code", "function", "algorithm", "debug", "optimize"
        ]

        query_lower = query.lower()
        complexity_score = sum(1 for indicator in complex_indicators if indicator in query_lower)

        if complexity_score >= 3 and not policy.enable_reasoning:
            adapted = ResponsePolicy(
                max_tokens=min(policy.max_tokens * 1.5, 8192),
                temperature=policy.temperature,
                top_p=policy.top_p,
                presence_penalty=policy.presence_penalty,
                frequency_penalty=policy.frequency_penalty,
                stop_sequences=policy.stop_sequences.copy(),
                stream=policy.stream,
                adaptive_timeout=policy.adaptive_timeout,
                fallback_provider=policy.fallback_provider,
                enable_reasoning=True,
                reasoning_budget=min(2048, policy.max_tokens // 2),
            )
            return adapted
        return policy


@dataclass
class PolicyManager:
    """Centralized policy management."""

    def __init__(self):
        self._policies: Dict[str, ResponsePolicy] = {}
        self.selector = PolicySelector()
        self.adapter = PolicyAdapter()
        self._register_default_policies()

    def _register_default_policies(self):
        """Register built-in policy presets."""
        self._policies["balanced"] = ResponsePolicy(
            max_tokens=2048,
            temperature=0.7,
            top_p=0.9,
            stream=True,
            adaptive_timeout=15.0,
        )

        self._policies["fast"] = ResponsePolicy(
            max_tokens=1024,
            temperature=0.5,
            top_p=0.95,
            stream=True,
            adaptive_timeout=5.0,
        )

        self._policies["thorough"] = ResponsePolicy(
            max_tokens=4096,
            temperature=0.7,
            top_p=0.9,
            stream=True,
            adaptive_timeout=30.0,
            enable_reasoning=True,
            reasoning_budget=1024,
        )

        self._policies["creative"] = ResponsePolicy(
            max_tokens=3072,
            temperature=0.9,
            top_p=0.95,
            stream=True,
            adaptive_timeout=20.0,
        )

        self._policies["precise"] = ResponsePolicy(
            max_tokens=1024,
            temperature=0.2,
            top_p=0.9,
            stream=True,
            adaptive_timeout=10.0,
            enable_reasoning=False,
        )

        self._policies["reasoning"] = ResponsePolicy(
            max_tokens=4096,
            temperature=0.3,
            top_p=0.9,
            stream=True,
            adaptive_timeout=60.0,
            enable_reasoning=True,
            reasoning_budget=2048,
        )

    def get_default_policy(self) -> ResponsePolicy:
        """Get default policy."""
        return self._policies["balanced"]

    def get_policy_by_name(self, name: str) -> ResponsePolicy:
        """Get named policy preset."""
        return self._policies.get(name, self.get_default_policy())

    def register_custom_policy(self, name: str, policy: ResponsePolicy) -> None:
        """Register custom policy."""
        self._policies[name] = policy

    def list_available_policies(self) -> List[str]:
        """List all available policies."""
        return list(self._policies.keys())

    def policy_validation(self, policy: ResponsePolicy) -> List[str]:
        """Validate policy parameters and return list of issues."""
        issues = []

        if policy.max_tokens <= 0:
            issues.append("max_tokens must be positive")
        if policy.max_tokens > 32768:
            issues.append("max_tokens exceeds maximum allowed value (32768)")

        if not 0.0 <= policy.temperature <= 2.0:
            issues.append("temperature must be between 0.0 and 2.0")

        if not 0.0 <= policy.top_p <= 1.0:
            issues.append("top_p must be between 0.0 and 1.0")

        if policy.presence_penalty < -2.0 or policy.presence_penalty > 2.0:
            issues.append("presence_penalty must be between -2.0 and 2.0")

        if policy.frequency_penalty < -2.0 or policy.frequency_penalty > 2.0:
            issues.append("frequency_penalty must be between -2.0 and 2.0")

        if policy.adaptive_timeout <= 0:
            issues.append("adaptive_timeout must be positive")

        if policy.reasoning_budget < 0:
            issues.append("reasoning_budget cannot be negative")
        if policy.reasoning_budget > policy.max_tokens:
            issues.append("reasoning_budget cannot exceed max_tokens")

        return issues


def build_chat_request(
    messages: List[ChatMessage],
    model: str,
    policy: ResponsePolicy,
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: Dict[str, Any] | None = None,
) -> ChatRequest:
    """
    Build a chat request with the given policy applied.

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
    # Combine metadata
    combined_metadata = metadata or {}
    if user_id:
        combined_metadata["user_id"] = user_id
    if session_id:
        combined_metadata["session_id"] = session_id

    return ChatRequest(
        messages=messages,
        model=model,
        policy=policy,
        metadata=combined_metadata if combined_metadata else None,
    )


# Global instances for convenience
default_policy_selector = PolicySelector()
default_policy_adapter = PolicyAdapter()
default_policy_manager = PolicyManager()