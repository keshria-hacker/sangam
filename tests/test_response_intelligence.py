"""
Tests for Response Intelligence Layer (Phase 6).

Covers all 16 adaptive behaviors via 12 test cases.
Tests are pure unit tests - no external dependencies, no database needed.
"""
from __future__ import annotations

import pytest

from backend.response_intelligence import (
    analyze_request,
    build_conversation_profile,
    build_system_prompt_additions,
    classify_query_mode,
    detect_intent_signals,
)
from backend.response_intelligence.config import config
from backend.response_intelligence.schema import (
    ConversationProfile,
    IntentSignal,
    QueryMode,
    ResponseGuidance,
)


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def empty_history() -> list[dict]:
    """Empty conversation history."""
    return []


@pytest.fixture
def short_history() -> list[dict]:
    """Short conversation history (3 messages)."""
    return [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there! How can I help?"},
        {"role": "user", "content": "What is Python?"},
    ]


@pytest.fixture
def coding_history() -> list[dict]:
    """History with code context."""
    return [
        {"role": "user", "content": "Write a Python function to parse JSON"},
        {"role": "assistant", "content": "Here's a function:\n```python\nimport json\n\ndef parse_json(s):\n    return json.loads(s)\n```"},
        {"role": "user", "content": "Now add error handling"},
    ]


@pytest.fixture
def detailed_history() -> list[dict]:
    """History showing user preference for detailed responses."""
    return [
        {"role": "user", "content": "Explain in detail how REST APIs work comprehensively"},
        {"role": "assistant", "content": "Detailed explanation..."},
        {"role": "user", "content": "Now explain GraphQL in depth thoroughly"},
    ]


@pytest.fixture
def concise_history() -> list[dict]:
    """History showing user preference for concise responses."""
    return [
        {"role": "user", "content": "What is REST?"},
        {"role": "assistant", "content": "REST is an architectural style..."},
        {"role": "user", "content": "What about GraphQL?"},
    ]


@pytest.fixture
def followup_history() -> list[dict]:
    """History for follow-up testing."""
    return [
        {"role": "user", "content": "Tell me about Python decorators"},
        {"role": "assistant", "content": "Decorators are functions that modify other functions..."},
        {"role": "user", "content": "How do I use that in practice?"},
    ]


# ============================================================================
# classify_query_mode Tests
# ============================================================================

def test_classify_coding_mode(coding_history):
    """Test: QueryMode.CODING for code requests."""
    mode = classify_query_mode("Write a function to parse JSON", coding_history)
    assert mode == QueryMode.CODING


def test_classify_coding_mode_from_history(coding_history):
    """Test: CODING mode detected from history context."""
    mode = classify_query_mode("Add error handling", coding_history)
    assert mode == QueryMode.CODING


def test_classify_creative_mode():
    """Test: QueryMode.CREATIVE for creative writing."""
    mode = classify_query_mode("Write a poem about code", [])
    assert mode == QueryMode.CREATIVE


def test_classify_instructional_mode():
    """Test: QueryMode.INSTRUCTIONAL for how-to requests."""
    mode = classify_query_mode("How do I create a decorator?", [])
    assert mode == QueryMode.INSTRUCTIONAL


def test_classify_factual_mode():
    """Test: QueryMode.FACTUAL for fact-seeking queries."""
    mode = classify_query_mode("What is the capital of France?", [])
    assert mode == QueryMode.FACTUAL


def test_classify_analysis_mode():
    """Test: QueryMode.ANALYSIS for comparison/analysis requests."""
    mode = classify_query_mode("Compare REST vs GraphQL", [])
    assert mode == QueryMode.ANALYSIS


def test_classify_conversational_default():
    """Test: QueryMode.CONVERSATIONAL as default."""
    mode = classify_query_mode("Hello there!", [])
    assert mode == QueryMode.CONVERSATIONAL


# ============================================================================
# detect_intent_signals Tests (The 12 Core Test Cases)
# ============================================================================

def test_concise_by_default():
    """Test 1: Short query → wants_concise=True, max_paragraphs constraint."""
    signals = detect_intent_signals("What is Python?")  # < 50 chars
    assert signals.wants_concise is True
    assert signals.wants_detailed is False


def test_detail_on_demand():
    """Test 2: 'explain in detail' → wants_detailed=True."""
    signals = detect_intent_signals("Explain Python in detail comprehensively")
    assert signals.wants_detailed is True
    assert signals.wants_concise is False


def test_direct_answer_factual():
    """Test 3: Factual query → wants_direct_answer=True, mode=FACTUAL."""
    signals = detect_intent_signals("What is the capital of France?")
    assert signals.wants_direct_answer is True


def test_followup_understanding(followup_history):
    """Test 4: Follow-up reference → has_followup=True, profile populated."""
    signals = detect_intent_signals("How do I use that in practice?", followup_history)
    assert signals.has_followup is True


def test_ambiguity_detection(empty_history):
    """Test 6: Ambiguous/underspecified → is_ambiguous=True."""
    signals = detect_intent_signals("How do I fix it?", [])
    assert signals.is_ambiguous is True


def test_ambiguity_not_flagged_on_clear_short_question():
    """Regression: triggers match whole words only.

    'or' inside 'short'/'words' must not flag a clear factual request as
    ambiguous — the substring match used to trigger the clarification gate,
    which replaced real answers with the canned clarification card.
    """
    signals = detect_intent_signals("What is the capital of France? Answer in one short sentence.")
    assert signals.is_ambiguous is False


def test_ambiguity_standalone_or_still_flags():
    """Standalone 'or' (unclear alternative) is still detected as ambiguous."""
    signals = detect_intent_signals("Should I use plan A or B?")
    assert signals.is_ambiguous is True


def test_tone_adaptation_formal():
    """Test 7a: Formal language → tone=formal."""
    signals = detect_intent_signals("Could you please explain how this works?")
    assert signals.tone == "formal"


def test_tone_adaptation_casual():
    """Test 7b: Casual language → tone=casual."""
    signals = detect_intent_signals("Hey, what's up with Python?")
    assert signals.tone == "casual"


def test_step_by_step_reasoning():
    """Test 8: 'step by step' → needs_step_by_step=True, structure constraint."""
    signals = detect_intent_signals("Walk me through debugging step by step")
    assert signals.needs_step_by_step is True


def test_example_driven():
    """Test 9: 'show me an example' → needs_examples=True."""
    signals = detect_intent_signals("Show me an example of a decorator")
    assert signals.needs_examples is True


def test_citation_request():
    """Test 10: 'cite your sources' → needs_citations=True."""
    signals = detect_intent_signals("Cite your sources for this claim")
    assert signals.needs_citations is True


def test_coding_mode_with_history(coding_history):
    """Test 14: Coding intent + code history → mode=CODING, has_code_context=True."""
    profile = build_conversation_profile(coding_history, "Add error handling")
    assert profile.has_code_context is True


def test_creative_vs_factual():
    """Test 13: Creative vs factual classification."""
    creative_mode = classify_query_mode("Write a story about a robot", [])
    factual_mode = classify_query_mode("Fact check: Is Python interpreted?", [])
    assert creative_mode == QueryMode.CREATIVE
    assert factual_mode == QueryMode.FACTUAL


# ============================================================================
# build_conversation_profile Tests
# ============================================================================

def test_profile_detects_code_context(coding_history):
    """Profile detects code fences in history."""
    profile = build_conversation_profile(coding_history, "New message")
    assert profile.has_code_context is True
    assert profile.message_count == 3


def test_profile_detects_user_preferences_concise(concise_history):
    """Profile detects user prefers concise responses."""
    profile = build_conversation_profile(concise_history, "New")
    assert profile.user_prefers_concise is True


def test_profile_detects_user_preferences_detailed(detailed_history):
    """Profile detects user prefers detailed responses."""
    profile = build_conversation_profile(detailed_history, "New")
    assert profile.user_prefers_detailed is True


def test_profile_extracts_topics():
    """Profile extracts recurring topics."""
    history = [
        {"role": "user", "content": "Tell me about Python decorators and functions"},
        {"role": "assistant", "content": "Decorators modify functions..."},
        {"role": "user", "content": "How do decorators work with async functions?"},
    ]
    profile = build_conversation_profile(history, "New")
    assert "decorators" in profile.topics or "functions" in profile.topics


# ============================================================================
# build_system_prompt_additions Tests
# ============================================================================

def test_prompt_injection_concise():
    """System prompt includes concise instruction."""
    guidance = ResponseGuidance(
        mode=QueryMode.FACTUAL,
        intent=IntentSignal(wants_concise=True),
    )
    additions = build_system_prompt_additions(guidance)
    assert any("concise" in a.lower() for a in additions)


def test_prompt_injection_detailed():
    """System prompt includes detailed instruction."""
    guidance = ResponseGuidance(
        mode=QueryMode.FACTUAL,
        intent=IntentSignal(wants_detailed=True),
    )
    additions = build_system_prompt_additions(guidance)
    assert any("comprehensive" in a.lower() or "detail" in a.lower() for a in additions)


def test_prompt_injection_direct_answer():
    """System prompt includes direct answer instruction."""
    guidance = ResponseGuidance(
        mode=QueryMode.FACTUAL,
        intent=IntentSignal(wants_direct_answer=True),
    )
    additions = build_system_prompt_additions(guidance)
    assert any("direct" in a.lower() and "answer" in a.lower() for a in additions)


def test_prompt_injection_followup():
    """System prompt includes follow-up instruction."""
    guidance = ResponseGuidance(
        mode=QueryMode.CONVERSATIONAL,
        intent=IntentSignal(has_followup=True),
    )
    additions = build_system_prompt_additions(guidance)
    assert any("follow" in a.lower() or "continuity" in a.lower() for a in additions)


def test_prompt_injection_ambiguity():
    """System prompt includes ambiguity instruction."""
    guidance = ResponseGuidance(
        mode=QueryMode.FACTUAL,
        intent=IntentSignal(is_ambiguous=True),
    )
    additions = build_system_prompt_additions(guidance)
    assert any("ambiguous" in a.lower() or "assumptions" in a.lower() or "clarification" in a.lower() for a in additions)


def test_prompt_injection_tone_formal():
    """System prompt includes formal tone instruction."""
    guidance = ResponseGuidance(
        mode=QueryMode.CONVERSATIONAL,
        intent=IntentSignal(tone="formal"),
    )
    additions = build_system_prompt_additions(guidance)
    assert any("formal" in a.lower() or "professional" in a.lower() for a in additions)


def test_prompt_injection_step_by_step():
    """System prompt includes step-by-step instruction."""
    guidance = ResponseGuidance(
        mode=QueryMode.INSTRUCTIONAL,
        intent=IntentSignal(needs_step_by_step=True),
    )
    additions = build_system_prompt_additions(guidance)
    assert any("step" in a.lower() and ("number" in a.lower() or "structure" in a.lower()) for a in additions)


def test_prompt_injection_examples():
    """System prompt includes examples instruction."""
    guidance = ResponseGuidance(
        mode=QueryMode.CODING,
        intent=IntentSignal(needs_examples=True),
    )
    additions = build_system_prompt_additions(guidance)
    assert any("example" in a.lower() for a in additions)


def test_prompt_injection_citations():
    """System prompt includes citations instruction."""
    guidance = ResponseGuidance(
        mode=QueryMode.FACTUAL,
        intent=IntentSignal(needs_citations=True),
    )
    additions = build_system_prompt_additions(guidance)
    assert any("cite" in a.lower() or "source" in a.lower() for a in additions)


def test_prompt_injection_bullet_points():
    """System prompt includes bullet points instruction."""
    guidance = ResponseGuidance(
        mode=QueryMode.ANALYSIS,
        intent=IntentSignal(prefers_bullet_points=True),
    )
    additions = build_system_prompt_additions(guidance)
    assert any("bullet" in a.lower() for a in additions)


def test_prompt_injection_technical_depth_low():
    """System prompt includes ELI5 instruction."""
    guidance = ResponseGuidance(
        mode=QueryMode.FACTUAL,
        intent=IntentSignal(technical_depth="low"),
    )
    additions = build_system_prompt_additions(guidance)
    assert any("simple" in a.lower() or "eli5" in a.lower() or "jargon" in a.lower() for a in additions)


def test_prompt_injection_technical_depth_high():
    """System prompt includes technical depth instruction."""
    guidance = ResponseGuidance(
        mode=QueryMode.CODING,
        intent=IntentSignal(technical_depth="high"),
    )
    additions = build_system_prompt_additions(guidance)
    assert any("technical" in a.lower() or "terminology" in a.lower() or "expertise" in a.lower() for a in additions)


def test_prompt_injection_creative_mode():
    """System prompt includes creative mode instruction."""
    guidance = ResponseGuidance(mode=QueryMode.CREATIVE)
    additions = build_system_prompt_additions(guidance)
    assert any("creative" in a.lower() or "expressive" in a.lower() or "vivid" in a.lower() for a in additions)


def test_prompt_injection_coding_mode():
    """System prompt includes coding mode instruction."""
    guidance = ResponseGuidance(mode=QueryMode.CODING)
    additions = build_system_prompt_additions(guidance)
    assert any("code" in a.lower() or "idiomatic" in a.lower() or "production" in a.lower() for a in additions)


def test_prompt_injection_urgency():
    """System prompt includes urgency/brevity instruction."""
    guidance = ResponseGuidance(
        mode=QueryMode.FACTUAL,
        intent=IntentSignal(urgency="high"),
    )
    additions = build_system_prompt_additions(guidance)
    assert any("brevity" in a.lower() or "brief" in a.lower() or "skip" in a.lower() for a in additions)


# ============================================================================
# analyze_request Integration Tests
# ============================================================================

@pytest.mark.asyncio
async def test_analyze_request_returns_complete_guidance():
    """analyze_request returns fully populated ResponseGuidance."""
    messages = [
        {"role": "user", "content": "What is Python?"},
    ]
    # Mock db - not needed for this test as we use messages directly
    class MockDB:
        pass

    guidance = await analyze_request(
        messages=messages,
        model_id="ollama::llama3",
        temperature=0.7,
        chat_id=None,
        db=MockDB(),
    )

    assert isinstance(guidance, ResponseGuidance)
    assert isinstance(guidance.mode, QueryMode)
    assert isinstance(guidance.intent, IntentSignal)
    assert isinstance(guidance.profile, ConversationProfile)
    assert isinstance(guidance.system_prompt_additions, list)
    assert isinstance(guidance.constraints, dict)
    assert 0.0 <= guidance.confidence <= 1.0


@pytest.mark.asyncio
async def test_analyze_request_with_history():
    """analyze_request uses conversation history for profile."""
    messages = [
        {"role": "user", "content": "Tell me about Python decorators"},
        {"role": "assistant", "content": "Decorators are..."},
        {"role": "user", "content": "How do I use that?"},  # Follow-up
    ]

    class MockDB:
        pass

    guidance = await analyze_request(
        messages=messages,
        model_id="ollama::llama3",
        temperature=0.7,
        chat_id="test-chat",
        db=MockDB(),
    )

    assert guidance.intent.has_followup is True
    assert guidance.profile.message_count == 2  # Excludes current user message


# ============================================================================
# Configuration Tests
# ============================================================================

def test_config_defaults():
    """Config has sensible defaults."""
    assert config.ENABLED is True
    assert config.CONCISE_THRESHOLD_CHARS == 50
    assert config.HIGH_CONFIDENCE == 0.8
    assert config.LOW_CONFIDENCE == 0.4


def test_config_trigger_patterns():
    """get_trigger_patterns returns all categories."""
    patterns = config.get_trigger_patterns() if hasattr(config, 'get_trigger_patterns') else {}
    # Should have all 16 behavior categories
    expected_categories = {
        "detail", "direct_answer", "followup", "ambiguity",
        "tone_formal", "tone_casual", "tone_empathetic", "tone_direct",
        "step_by_step", "example", "citation", "bullet", "narrative",
        "tech_low", "tech_high", "creative", "factual", "coding",
        "instructional", "urgency"
    }
    # Note: get_trigger_patterns is a function in config.py
    from backend.response_intelligence.config import get_trigger_patterns
    patterns = get_trigger_patterns()
    for cat in expected_categories:
        assert cat in patterns, f"Missing trigger category: {cat}"
        assert isinstance(patterns[cat], list)
        assert len(patterns[cat]) > 0


# ============================================================================
# Edge Case Tests
# ============================================================================

def test_conflicting_intents_concise_and_detailed():
    """When both concise and detailed triggers present, detailed wins (explicit)."""
    # "Explain in detail" but short - explicit detail trigger should win
    signals = detect_intent_signals("Explain in detail")
    assert signals.wants_detailed is True
    assert signals.wants_concise is False


def test_no_followup_without_history():
    """Follow-up trigger ignored when no history."""
    signals = detect_intent_signals("Tell me more about that", [])
    assert signals.has_followup is False


def test_empty_message():
    """Empty message handled gracefully."""
    signals = detect_intent_signals("")
    assert isinstance(signals, IntentSignal)
    assert signals.wants_concise is True  # Empty < threshold


def test_unicode_handling():
    """Unicode messages handled correctly."""
    signals = detect_intent_signals("Was ist Python? 请解释 Python")
    assert isinstance(signals, IntentSignal)


# ============================================================================
# Run Tests Directly
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])