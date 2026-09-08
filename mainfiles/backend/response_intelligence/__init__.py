"""
Response Intelligence Package — Phase 6 + Phase 7

Lightweight, provider-neutral response-intelligence layer that analyzes
user requests + conversation context and emits structured guidance (16
adaptive behaviors) to shape model behavior — WITHOUT a second LLM call.

Public API:
    analyze_request()          # Main entry point - returns ResponseGuidance
    ResponseGuidance           # Structured guidance object
    IntentSignal               # Behavioral signals (16 flags + capability hints)
    ConversationProfile        # Aggregated conversation context
    QueryMode                  # High-level query classification
    build_system_prompt_additions()  # Translate guidance → system prompt
    config                     # Configuration instance
    capability_decide()        # Phase 7: Determine tool/capability availability
    CapabilityDecision         # Phase 7: Capability decision result
"""

from backend.response_intelligence.classification import (
    analyze_request,
    build_conversation_profile,
    classify_query_mode,
    detect_intent_signals,
)
from backend.response_intelligence.config import config, get_trigger_patterns
from backend.response_intelligence.prompt_injector import (
    build_system_prompt_additions,
    format_guidance_for_debug,
)
from backend.response_intelligence.schema import (
    ConversationProfile,
    IntentSignal,
    QueryMode,
    ResponseGuidance,
)
from backend.capability_orchestration import (
    capability_decide,
    CapabilityDecision,
)

__all__ = [
    # Main API
    "analyze_request",
    # Types
    "ResponseGuidance",
    "IntentSignal",
    "ConversationProfile",
    "QueryMode",
    # Phase 7 Capability Orchestration
    "capability_decide",
    "CapabilityDecision",
    # Classification functions
    "classify_query_mode",
    "detect_intent_signals",
    "build_conversation_profile",
    # Prompt injection
    "build_system_prompt_additions",
    "format_guidance_for_debug",
    # Config
    "config",
    "get_trigger_patterns",
]

# Version
__version__ = "1.0.0"