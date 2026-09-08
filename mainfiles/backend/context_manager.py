"""
Context Manager - Token Budget & Safe Truncation (Phase 9 P0)

This module handles token budget management for LLM requests.
It ensures the conversation context fits within the model's context window
while preserving critical context (system prompts, RAG, web search, tools).

Key principles:
- Immutable: never mutates input messages, always returns new list
- Safe: preserves system, tool, RAG, and web context messages
- Model-aware: uses tiktoken with model-specific encodings
- Graceful: falls back to approximation when tiktoken unavailable
"""

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import tiktoken

from backend.providers.base import ModelInfo
from backend.response_events import ModelCapabilities

logger = logging.getLogger(__name__)


# Model-specific encoding mapping
MODEL_ENCODING_MAP = {
    # OpenAI models
    "gpt-4o": "o200k_base",
    "gpt-4o-mini": "o200k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-4": "cl100k_base",
    "gpt-3.5-turbo": "cl100k_base",
    "o1": "o200k_base",
    "o3": "o200k_base",
    # Anthropic models (use cl100k_base as approximation)
    "claude": "cl100k_base",
    # Google models
    "gemini": "cl100k_base",
    # DeepSeek models
    "deepseek": "cl100k_base",
    # Mistral models
    "mistral": "cl100k_base",
    # Default fallback
    "default": "cl100k_base",
}


@lru_cache(maxsize=32)
def _get_encoding_for_model(litellm_id: str) -> tiktoken.Encoding:
    """Get tiktoken encoding for a model ID.

    Falls back to cl100k_base if model-specific encoding not found.
    Uses LRU cache to avoid redundant encoding resolution.
    """
    lower_id = litellm_id.lower()

    # Check for exact matches first
    for key, encoding_name in MODEL_ENCODING_MAP.items():
        if key in lower_id:
            try:
                return tiktoken.get_encoding(encoding_name)
            except Exception:
                pass

    # Try to get encoding by model name (for OpenAI models)
    try:
        return tiktoken.encoding_for_model(litellm_id)
    except Exception:
        pass

    # Final fallback
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str, encoding: tiktoken.Encoding) -> int:
    """Count tokens in a text string using the given encoding."""
    if not text:
        return 0
    try:
        return len(encoding.encode(text))
    except Exception:
        # Fallback: rough approximation (4 chars per token)
        return max(1, len(text) // 4)


def count_message_tokens(message: dict[str, Any], encoding: tiktoken.Encoding) -> int:
    """Count tokens for a single message dict.

    Accounts for role formatting overhead (~3 tokens per message).
    """
    content = message.get("content", "")
    role = message.get("role", "user")

    # Base tokens for role markup
    tokens = 3  # ~3 tokens for role formatting

    # Content tokens
    if isinstance(content, str):
        tokens += count_tokens(content, encoding)
    elif isinstance(content, list):
        # Handle structured content (e.g., vision messages with image_url)
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    tokens += count_tokens(item.get("text", ""), encoding)
                elif item.get("type") == "image_url":
                    # Approximate: images ~ 85 tokens (low-res) to 170+ (high-res)
                    tokens += 170

    # Tool calls
    if message.get("tool_calls"):
        for tc in message["tool_calls"]:
            tokens += count_tokens(str(tc), encoding)

    # Tool call ID for tool messages
    if role == "tool" and message.get("tool_call_id"):
        tokens += count_tokens(message["tool_call_id"], encoding)

    return tokens


@dataclass(frozen=True)
class ContextBudget:
    """Token budget configuration for a request."""
    model_context_window: int
    reserved_output_tokens: int = 1024
    safety_margin: int = 256  # Extra buffer for encoding variance

    @property
    def available_for_context(self) -> int:
        """Tokens available for input context (history + system + RAG + tools)."""
        return max(0, self.model_context_window - self.reserved_output_tokens - self.safety_margin)


@dataclass(frozen=True)
class TruncationResult:
    """Result of context truncation operation."""
    messages: list[dict[str, Any]]
    truncated: bool
    original_token_count: int
    final_token_count: int
    removed_message_count: int
    budget: ContextBudget
    current_user_exceeds_budget: bool = False  # Flag for oversized current user message

    @property
    def utilization_pct(self) -> float:
        """Context utilization as percentage of available budget."""
        if self.budget.available_for_context <= 0:
            return 100.0
        return (self.final_token_count / self.budget.available_for_context) * 100


class ContextManager:
    """Manages token budget and safe truncation for conversation messages."""

    def __init__(
        self,
        model_info: ModelInfo,
        reserved_output_tokens: int = 1024,
        safety_margin: int = 256,
    ):
        """Initialize context manager for a specific model.

        Args:
            model_info: ModelInfo containing context_window and litellm_id
            reserved_output_tokens: Tokens to reserve for model output
            safety_margin: Extra buffer for encoding variance
        """
        self.model_info = model_info
        self.budget = ContextBudget(
            model_context_window=model_info.context_window or 4096,
            reserved_output_tokens=reserved_output_tokens,
            safety_margin=safety_margin,
        )
        self._encoding = _get_encoding_for_model(model_info.litellm_id or "")

        logger.debug(
            "ContextManager initialized for %s: window=%d, budget=%d, encoding=%s",
            model_info.id,
            self.budget.model_context_window,
            self.budget.available_for_context,
            self._encoding.name,
        )

    def count_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Count total tokens for a list of messages."""
        return sum(count_message_tokens(msg, self._encoding) for msg in messages)

    def _classify_system_message(self, message: dict[str, Any]) -> str:
        """Classify a system message by type for priority-based truncation.

        Returns:
            "essential" - Base system instructions (e.g., "You are a helpful assistant")
            "phase6" - Phase 6 Response Intelligence guidance
            "rag" - RAG context (marked with "[RAG context]")
            "web" - Web search context (marked with "[Web search result]")
            "other" - Other system messages (treated as essential)
        """
        content = message.get("content", "")

        if "[RAG context]" in content:
            return "rag"
        if "[Web search result]" in content:
            return "web"
        if "response intelligence" in content.lower() or "guidance" in content.lower():
            return "phase6"
        if "helpful assistant" in content.lower() or "you are" in content.lower():
            return "essential"
        return "other"  # Treat as essential

    def _group_tool_interactions(self, messages: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
        """
        Group tool interactions into atomic units.

        Returns:
            (preserved_tools, truncatable_messages)
            - preserved_tools: Complete tool interaction units (assistant+tool_call + tool results)
            - truncatable_messages: All other messages that can be truncated
        """
        preserved_tools = []
        truncatable = []

        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg.get("role", "")

            # Check for assistant with tool_calls (start of tool interaction)
            if role == "assistant" and msg.get("tool_calls"):
                # Find all corresponding tool results
                tool_call_ids = {tc["id"] for tc in msg["tool_calls"]}
                tool_results = []

                # Look ahead for tool results
                j = i + 1
                while j < len(messages):
                    next_msg = messages[j]
                    if next_msg.get("role") == "tool" and next_msg.get("tool_call_id") in tool_call_ids:
                        tool_results.append(next_msg)
                        tool_call_ids.discard(next_msg["tool_call_id"])
                        if not tool_call_ids:
                            break
                    elif next_msg.get("role") == "assistant" and next_msg.get("tool_calls"):
                        break
                    elif next_msg.get("role") == "user":
                        break
                    j += 1

                # If we found all tool results, preserve the entire interaction
                if not tool_call_ids:
                    preserved_tools.append(msg)
                    preserved_tools.extend(tool_results)
                    i = j
                    continue

            truncatable.append(msg)
            i += 1

        return preserved_tools, truncatable

    def truncate(
        self,
        messages: list[dict[str, Any]],
        preserve_last_user: bool = True,
    ) -> TruncationResult:
        """Truncate messages to fit within token budget using priority-based strategy.

        Priority order (highest to lowest):
        1. Essential system instructions (base prompt)
        2. Current user request
        3. Complete tool-call/tool-result interactions (atomic)
        4. Phase 6 guidance
        5. Recent conversation history
        6. RAG context (oldest first)
        7. Web search context (oldest first)

        Args:
            messages: List of message dicts (chronological order)
            preserve_last_user: Whether to always keep the last user message

        Returns:
            TruncationResult with truncated message list and metadata
        """
        if not messages:
            return TruncationResult(
                messages=[],
                truncated=False,
                original_token_count=0,
                final_token_count=0,
                removed_message_count=0,
                budget=self.budget,
            )

        original_count = self.count_tokens(messages)
        available = self.budget.available_for_context

        # Already fits - no truncation needed
        if original_count <= available:
            return TruncationResult(
                messages=list(messages),
                truncated=False,
                original_token_count=original_count,
                final_token_count=original_count,
                removed_message_count=0,
                budget=self.budget,
            )

        # --- Step 1: Categorize all messages ---
        essential_system = []
        phase6_guidance = []
        rag_context = []
        web_context = []
        last_user = None
        truncatable_history = []

        # Extract tool interactions as atomic units
        tool_preserved, non_tool_messages = self._group_tool_interactions(messages)

        # Categorize non-tool messages
        last_user_idx = -1
        if preserve_last_user:
            for i in range(len(non_tool_messages) - 1, -1, -1):
                if non_tool_messages[i].get("role") == "user":
                    last_user_idx = i
                    break

        for i, msg in enumerate(non_tool_messages):
            role = msg.get("role", "")
            if role == "system":
                sys_type = self._classify_system_message(msg)
                if sys_type == "essential":
                    essential_system.append(msg)
                elif sys_type == "phase6":
                    phase6_guidance.append(msg)
                elif sys_type == "rag":
                    rag_context.append(msg)
                elif sys_type == "web":
                    web_context.append(msg)
                else:
                    essential_system.append(msg)  # Treat unknown as essential
            elif preserve_last_user and i == last_user_idx:
                last_user = msg
            elif role == "tool":
                # Tool messages should have been captured by _group_tool_interactions
                # If we get here, it means the tool message wasn't part of a complete interaction
                # We still preserve it as part of the mandatory set
                tool_preserved.append(msg)
            else:
                truncatable_history.append(msg)

        # --- Step 2: Calculate token counts ---
        essential_tokens = sum(count_message_tokens(m, self._encoding) for m in essential_system)
        phase6_tokens = sum(count_message_tokens(m, self._encoding) for m in phase6_guidance)
        rag_tokens = sum(count_message_tokens(m, self._encoding) for m in rag_context)
        web_tokens = sum(count_message_tokens(m, self._encoding) for m in web_context)
        tool_tokens = sum(count_message_tokens(m, self._encoding) for m in tool_preserved)
        last_user_tokens = count_message_tokens(last_user, self._encoding) if last_user else 0

        # --- Step 3: Handle oversized current user message ---
        if last_user and last_user_tokens > available:
            logger.warning(
                "Current user message (%d tokens) exceeds input budget (%d) for model %s. "
                "Preserving complete message and setting current_user_exceeds_budget=True.",
                last_user_tokens, available, self.model_info.id
            )
            # Return only essential system + current user (even though it exceeds budget)
            result_messages = essential_system + [last_user]
            return TruncationResult(
                messages=result_messages,
                truncated=True,
                original_token_count=original_count,
                final_token_count=sum(count_message_tokens(m, self._encoding) for m in result_messages),
                removed_message_count=len(messages) - len(result_messages),
                budget=self.budget,
                current_user_exceeds_budget=True,
            )

        # --- Step 4: Build result with priority-based inclusion ---
        # Always include: essential system, current user, tool interactions
        mandatory = essential_system + tool_preserved
        mandatory_tokens = essential_tokens + tool_tokens
        if last_user:
            mandatory.append(last_user)
            mandatory_tokens += last_user_tokens

        # If mandatory alone exceeds budget, return mandatory (it's the minimum safe set)
        if mandatory_tokens > available:
            logger.warning(
                "Mandatory messages (%d tokens) exceed budget (%d) for model %s. "
                "Returning mandatory messages only.",
                mandatory_tokens, available, self.model_info.id
            )
            return TruncationResult(
                messages=mandatory,
                truncated=True,
                original_token_count=original_count,
                final_token_count=mandatory_tokens,
                removed_message_count=len(messages) - len(mandatory),
                budget=self.budget,
                current_user_exceeds_budget=bool(last_user and last_user_tokens > available),
            )

        # Start with mandatory messages
        result_messages = list(mandatory)
        current_tokens = mandatory_tokens

        # Add Phase 6 guidance if it fits
        if phase6_tokens <= available - current_tokens:
            result_messages.extend(phase6_guidance)
            current_tokens += phase6_tokens
        else:
            # Phase 6 guidance doesn't fit - skip it
            logger.debug("Phase 6 guidance (%d tokens) skipped due to budget", phase6_tokens)

        # Add conversation history (newest first)
        for msg in reversed(truncatable_history):
            msg_tokens = count_message_tokens(msg, self._encoding)
            if current_tokens + msg_tokens > available:
                break
            result_messages.insert(-1 if last_user else len(result_messages), msg)
            current_tokens += msg_tokens

        # Add RAG context (oldest first = lowest priority)
        # We insert before the last user message (if present)
        rag_insert_idx = len(result_messages) - (1 if last_user else 0)
        for msg in rag_context:
            msg_tokens = count_message_tokens(msg, self._encoding)
            if current_tokens + msg_tokens > available:
                logger.debug("RAG context truncated (budget exceeded)")
                break
            result_messages.insert(rag_insert_idx, msg)
            rag_insert_idx += 1
            current_tokens += msg_tokens

        # Add Web context (oldest first = lowest priority)
        web_insert_idx = rag_insert_idx
        for msg in web_context:
            msg_tokens = count_message_tokens(msg, self._encoding)
            if current_tokens + msg_tokens > available:
                logger.debug("Web context truncated (budget exceeded)")
                break
            result_messages.insert(web_insert_idx, msg)
            web_insert_idx += 1
            current_tokens += msg_tokens

        final_count = current_tokens
        truncated = final_count < original_count
        removed_count = len(messages) - len(result_messages)

        logger.info(
            "Context truncated for %s: %d -> %d tokens (removed %d messages, utilization=%.1f%%)",
            self.model_info.id, original_count, final_count, removed_count, final_count / available * 100
        )

        return TruncationResult(
            messages=result_messages,
            truncated=truncated,
            original_token_count=original_count,
            final_token_count=final_count,
            removed_message_count=removed_count,
            budget=self.budget,
            current_user_exceeds_budget=False,
        )

    def prepare_messages(
        self,
        messages: list[dict[str, Any]],
        preserve_last_user: bool = True,
    ) -> TruncationResult:
        """Prepare messages for provider call with automatic truncation.

        This is the main entry point - call this before sending to provider.

        Args:
            messages: Conversation messages in chronological order
            preserve_last_user: Always preserve the final user message

        Returns:
            TruncationResult with ready-to-use messages
        """
        return self.truncate(messages, preserve_last_user=preserve_last_user)


def create_context_manager(
    model_info: ModelInfo,
    reserved_output_tokens: int = 1024,
    safety_margin: int = 256,
) -> ContextManager:
    """Factory function to create ContextManager.

    Allows for potential future extension (e.g., different strategies).
    """
    return ContextManager(model_info, reserved_output_tokens, safety_margin)