"""Pydantic schemas for Response Intelligence Layer.

Defines the structured guidance object that flows from analyzer → prompt injector.
NO free-form instructions — only typed, validated fields.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QueryMode(StrEnum):
    """High-level query classification modes."""

    FACTUAL = "factual"
    CREATIVE = "creative"
    CODING = "coding"
    ANALYSIS = "analysis"
    CONVERSATIONAL = "conversational"
    INSTRUCTIONAL = "instructional"


class IntentSignal(BaseModel):
    """Detected signals from user message + context.

    Each field maps to one of the 16 adaptive behaviors.
    """

    # 1. Concise by default
    wants_concise: bool = False

    # 2. Detail on demand
    wants_detailed: bool = False

    # 3. Direct answer first
    wants_direct_answer: bool = False

    # 4. Follow-up understanding
    has_followup: bool = False

    # 5. Context preservation (handled via ConversationProfile)
    # 6. Ambiguity detection
    is_ambiguous: bool = False

    # 7. Tone adaptation
    tone: str = "neutral"  # "formal", "casual", "empathetic", "direct", "neutral"

    # 8. Step-by-step reasoning
    needs_step_by_step: bool = False

    # 9. Example-driven
    needs_examples: bool = False

    # 10. Citation request
    needs_citations: bool = False

    # 11. Bullet vs narrative
    prefers_bullet_points: bool = False
    prefers_narrative: bool = False

    # 12. Technical depth
    technical_depth: str = "auto"  # "low", "medium", "high", "auto"

    # 13. Creative vs factual (handled via QueryMode)
    # 14. Coding intent (handled via QueryMode + ConversationProfile)
    # 15. Instructional mode (handled via QueryMode)
    # 16. Urgency / brevity
    urgency: str = "normal"  # "low", "normal", "high"

    # Phase 7: Capability signals (optional hints for orchestration)
    capability_hint: str = "none"  # "none", "tool", "file", "web"
    tool_need: str = "none"  # "none", "possible", "likely"

    model_config = ConfigDict(use_enum_values=True)


class ConversationProfile(BaseModel):
    """Aggregated context from conversation history.

    Built from the last N messages (default 10) to provide context
    for the current request without re-processing full history.
    """

    message_count: int = 0
    avg_user_length: int = 0
    topics: list[str] = Field(default_factory=list)
    has_code_context: bool = False
    has_file_context: bool = False
    last_user_intent: QueryMode | None = None
    user_prefers_concise: bool = False
    user_prefers_detailed: bool = False

    model_config = ConfigDict(use_enum_values=True)


class ResponseGuidance(BaseModel):
    """Complete structured guidance for the model.

    This is the single output of analyze_request() and the single
    input to build_system_prompt_additions().
    """

    # High-level mode
    mode: QueryMode = QueryMode.CONVERSATIONAL

    # Behavioral signals
    intent: IntentSignal = Field(default_factory=IntentSignal)

    # Conversation context
    profile: ConversationProfile = Field(default_factory=ConversationProfile)

    # Direct system prompt additions (injected as system message)
    system_prompt_additions: list[str] = Field(default_factory=list)

    # Structured constraints the model should honor
    constraints: dict[str, Any] = Field(default_factory=dict)

    # Metadata
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: str = "heuristic"  # "heuristic", "user_override"

    # Note: No use_enum_values=True so mode stays as QueryMode enum internally
    # Serialization handled by to_dict() using model_dump(mode="json")

    def to_dict(self) -> dict[str, Any]:
        """Return a dict suitable for logging/debugging."""
        return self.model_dump(mode="json", exclude_none=True)


# Type alias for clarity in function signatures
GuidanceOrNone = ResponseGuidance | None