"""Query classification for Response Intelligence.

Determines the high-level QueryMode from user message + context.
Pure functions, no external dependencies, easily testable.
"""
from __future__ import annotations

import re
from collections import Counter

from backend.response_intelligence.config import config, get_trigger_patterns
from backend.response_intelligence.schema import (
    ConversationProfile,
    IntentSignal,
    QueryMode,
    ResponseGuidance,
)


# Pre-compiled regex patterns for common code indicators
CODE_FENCE_PATTERN = re.compile(r"```[\s\S]*?```")
INLINE_CODE_PATTERN = re.compile(r"`[^`]+`")
CODE_KEYWORDS = {
    "function", "class", "method", "variable", "import", "export", "const", "let", "var",
    "async", "await", "return", "if", "else", "for", "while", "try", "catch", "finally",
    "def", "lambda", "async def", "public", "private", "protected", "interface", "type",
    "struct", "enum", "impl", "trait", "mod", "use", "pub", "fn", "let mut", "match",
}


def classify_query_mode(
    user_message: str,
    conversation_history: list[dict] | None = None,
    profile: ConversationProfile | None = None,
) -> QueryMode:
    """Classify the query into a high-level mode.

    Priority order (first match wins):
    1. CREATIVE - explicit creative writing request (write a poem, story, etc.)
    2. INSTRUCTIONAL - how-to / tutorial request
    3. FACTUAL - fact-seeking query (what is, when, who, etc.)
    4. CODING - explicit code request or code in history
    5. ANALYSIS - analysis/comparison request
    6. CONVERSATIONAL - default

    Args:
        user_message: The latest user message content
        conversation_history: Recent messages for context (optional)
        profile: Pre-computed ConversationProfile (optional)

    Returns:
        QueryMode enum value
    """
    msg_lower = user_message.lower().strip()

    # 1. CREATIVE - explicit creative writing (comes before coding to avoid "code" false positive)
    if _is_creative_request(msg_lower):
        return QueryMode.CREATIVE

    # 2. INSTRUCTIONAL
    if _is_instructional_request(msg_lower):
        return QueryMode.INSTRUCTIONAL

    # 3. FACTUAL
    if _is_factual_request(msg_lower):
        return QueryMode.FACTUAL

    # 4. CODING - explicit code request or code in history
    if _is_coding_request(msg_lower, conversation_history, profile):
        return QueryMode.CODING

    # 5. ANALYSIS
    if _is_analysis_request(msg_lower):
        return QueryMode.ANALYSIS

    # 6. Default
    return QueryMode.CONVERSATIONAL


def _is_coding_request(
    msg_lower: str,
    conversation_history: list[dict] | None = None,
    profile: ConversationProfile | None = None,
) -> bool:
    """Check if request is explicitly coding-related."""
    # Check for coding exceptions first - phrases containing "code" that are NOT programming
    matched_exception = None
    for exception in config.CODING_EXCEPTIONS:
        if exception in msg_lower:
            matched_exception = exception
            break

    has_exception = matched_exception is not None

    # Check for ALL coding triggers (not just "code")
    # Count how many non-exception coding triggers are present
    non_code_triggers_present = []
    for trigger in config.CODING_TRIGGERS:
        if trigger == "code":
            continue
        if trigger in msg_lower:
            non_code_triggers_present.append(trigger)

    has_code_trigger = "code" in msg_lower
    has_non_code_trigger = len(non_code_triggers_present) > 0

    # If an exception phrase is found, we need to be very careful.
    # Only allow coding if there's a STRONG non-exception coding signal.
    if has_exception:
        # The exception phrase was found. Only allow coding if there are
        # clear programming context patterns (like "write code", "debug code", etc.)
        # OR if there's a code fence/inline code
        # OR if profile has code context
        # OR if there are multiple non-code coding triggers (strong signal)
        if profile and profile.has_code_context:
            return True
        if CODE_FENCE_PATTERN.search(msg_lower) or INLINE_CODE_PATTERN.search(msg_lower):
            return True
        if len(non_code_triggers_present) >= 2:
            # Multiple non-code triggers (e.g., "write function" -> "write" + "function")
            return True
        # Check for strong programming context patterns
        # IMPORTANT: Avoid matching when the pattern overlaps with exception phrases
        # e.g., "write source code" -> exception "source code" but also matches "write.*code"
        # We need to exclude patterns where the object is an exception phrase
        def pattern_matches_without_exception(pattern, text, exceptions):
            """Check if pattern matches but the matched portion is not an exception."""
            match = re.search(pattern, text)
            if not match:
                return False
            # For patterns like "write.*code", check if what's between "write" and "code"
            # contains an exception phrase
            matched_text = match.group(0)
            # Check if any exception is contained in the matched text
            for exc in exceptions:
                if exc in matched_text:
                    return False
            return True

        strong_programming_patterns = [
            (r"write.*code", True),
            (r"debug.*code", True),
            (r"refactor.*code", True),
            (r"review.*code", True),
            (r"code\s+(snippet|example|sample|piece|block|section|line)", False),
            (r"lines?\s+of\s+code", False),
            (r"block\s+of\s+code", False),
            (r"section\s+of\s+code", False),
            (r"generate.*code", True),
            (r"produce.*code", True),
            (r"create.*code", True),
            (r"build.*code", True),
            (r"clean\s+code", False),
            (r"legacy\s+code", False),
            (r"production\s+code", False),
            (r"test\s+code", False),
            # Exception-like phrases that should NOT trigger coding even with patterns
            (r"source\s+code", True),  # Must check exception overlap
            (r"application\s+code", True),
            (r"library\s+code", True),
            (r"framework\s+code", True),
            (r"code\s+(for|to|that)\s", False),
            (r"write.*(function|script|program|class|module|api|feature)", False),
            (r"create.*(function|script|program|class|module|api|feature)", False),
            (r"debug.*(function|script|program|module)", False),
            (r"fix.*(function|script|program|bug|error|issue)", False),
            (r"refactor.*(function|script|program|class|module)", False),
            (r"implement.*(function|script|program|class|module|feature)", False),
            (r"generate.*(function|script|program|class|module)", False),
        ]
        for pattern, check_exception in strong_programming_patterns:
            if check_exception:
                if pattern_matches_without_exception(pattern, msg_lower, config.CODING_EXCEPTIONS):
                    return True
            else:
                if re.search(pattern, msg_lower):
                    return True
        # If we only have the exception + incidental triggers (like "error"), don't code
        return False

    # No exception found - normal coding detection

    # Case 1: Multiple non-code triggers present (strong signal)
    # e.g., "write function" -> "write" + "function" (both in CODING_TRIGGERS)
    # But wait - "write" is not in CODING_TRIGGERS. Let's check actual triggers.
    if has_non_code_trigger and len(non_code_triggers_present) >= 2:
        return True

    # Case 2: Has "code" trigger + at least one other non-code trigger
    if has_code_trigger and has_non_code_trigger:
        return True

    # Case 3: Has non-code trigger and programming context patterns
    if has_non_code_trigger:
        # Check for action words combined with coding objects
        # e.g., "write function", "debug script", "create class"
        action_context_patterns = [
            r"write.*(function|script|program|code|class|module|api)",
            r"create.*(function|script|program|code|class|module|api)",
            r"debug.*(function|script|program|code|class|module)",
            r"fix.*(function|script|program|code|class|module|bug)",
            r"refactor.*(function|script|program|code|class|module)",
            r"implement.*(function|script|program|code|class|module|feature)",
            r"generate.*(function|script|program|code|class|module)",
        ]
        for pattern in action_context_patterns:
            if re.search(pattern, msg_lower):
                return True

        # Also check code fences/inline code
        if CODE_FENCE_PATTERN.search(msg_lower) or INLINE_CODE_PATTERN.search(msg_lower):
            return True

    # Case 4: Has "code" trigger but no exception - check context
    if has_code_trigger:
        # Check for non-"code" triggers first (already handled above)
        # Only "code" trigger - check programming context
        code_programming_context_patterns = [
            r"write.*code", r"debug.*code", r"refactor.*code", r"review.*code",
            r"code\s+(snippet|example|sample|piece|block|section|line)",
            r"lines?\s+of\s+code", r"block\s+of\s+code", r"section\s+of\s+code",
            r"generate.*code", r"produce.*code", r"create.*code", r"build.*code",
            r"clean\s+code", r"legacy\s+code", r"production\s+code", r"test\s+code",
            r"source\s+code", r"application\s+code", r"library\s+code", r"framework\s+code",
            r"code\s+(for|to|that)\s",
        ]
        for pattern in code_programming_context_patterns:
            if re.search(pattern, msg_lower):
                return True
        # Also check for code fence or inline code
        if CODE_FENCE_PATTERN.search(msg_lower) or INLINE_CODE_PATTERN.search(msg_lower):
            return True
        # If just "code" alone without context, don't trigger
        return False

    # Code fences or inline code in current message
    if CODE_FENCE_PATTERN.search(msg_lower) or INLINE_CODE_PATTERN.search(msg_lower):
        return True

    # Code context from profile
    if profile and profile.has_code_context:
        return True

    # Code in recent history
    if conversation_history:
        for msg in conversation_history[-config.HISTORY_WINDOW :]:
            content = msg.get("content", "").lower()
            if CODE_FENCE_PATTERN.search(content) or INLINE_CODE_PATTERN.search(content):
                return True
            # Check for code keywords density
            words = set(re.findall(r"\b\w+\b", content))
            if len(words & CODE_KEYWORDS) >= 3:
                return True

    return False


def _is_creative_request(msg_lower: str) -> bool:
    """Check if request is creative writing."""
    for trigger in config.CREATIVE_TRIGGERS:
        if trigger in msg_lower:
            return True
    return False


def _is_instructional_request(msg_lower: str) -> bool:
    """Check if request is instructional/how-to."""
    for trigger in config.INSTRUCTIONAL_TRIGGERS:
        if trigger in msg_lower:
            return True
    return False


def _is_factual_request(msg_lower: str) -> bool:
    """Check if request is fact-seeking."""
    # Direct answer triggers (what is, when, who, where, capital of, etc.)
    for trigger in config.DIRECT_ANSWER_TRIGGERS:
        if trigger in msg_lower:
            return True

    # Factual triggers
    for trigger in config.FACTUAL_TRIGGERS:
        if trigger in msg_lower:
            return True

    # Question patterns for factual queries
    factual_patterns = [
        r"^what (is|are|was|were)",
        r"^when (is|was|did|do|does)",
        r"^who (is|was|did|do|does)",
        r"^where (is|was|did|do|does)",
        r"^which (is|was|are|were)",
        r"^how (many|much|long|old|tall|wide|deep|high)",
        r"^define ",
        r"^definition of",
    ]
    for pattern in factual_patterns:
        if re.search(pattern, msg_lower):
            return True

    return False


def _is_analysis_request(msg_lower: str) -> bool:
    """Check if request is analysis/comparison."""
    analysis_triggers = [
        "compare", "contrast", "analyze", "analysis", "evaluate", "assess",
        "pros and cons", "advantages", "disadvantages", "trade.?off",
        "difference between", "similarities", "versus", " vs ", "better",
        "recommend", "suggestion", "opinion", "thoughts on", "review",
    ]
    for trigger in analysis_triggers:
        if re.search(trigger, msg_lower):
            return True
    return False


def detect_intent_signals(
    user_message: str,
    conversation_history: list[dict] | None = None,
    profile: ConversationProfile | None = None,
) -> IntentSignal:
    """Detect all 16 behavioral signals from message + context.

    Returns an IntentSignal with boolean flags for each behavior.
    """
    msg_lower = user_message.lower().strip()
    signals = IntentSignal()

    # Check for negation of detail request (e.g., "don't give me detailed", "no detail", "not detailed")
    negation_patterns = [
        "don't give me a detailed", "dont give me a detailed", "do not give me a detailed",
        "don't give me detailed", "dont give me detailed", "do not give me detailed",
        "don't give me detail", "dont give me detail", "do not give me detail",
        "no detail", "not detailed", "not detail", "without detail", "skip detail",
        "don't explain", "dont explain", "do not explain", "not explain",
        "brief", "concise", "short", "tldr", "tl;dr"
    ]
    has_negation = any(pattern in msg_lower for pattern in negation_patterns)

    # 1. Concise by default - short query
    is_short = len(user_message.strip()) <= config.CONCISE_THRESHOLD_CHARS
    if is_short:
        signals.wants_concise = True

    # 2. Detail on demand
    if any(t in msg_lower for t in config.DETAIL_TRIGGERS) and not has_negation:
        signals.wants_detailed = True
        # Explicit detail request overrides concise default
        signals.wants_concise = False
    elif has_negation:
        # Negation of detail forces concise
        signals.wants_concise = True
        signals.wants_detailed = False

    # 3. Direct answer first (factual query)
    if any(t in msg_lower for t in config.DIRECT_ANSWER_TRIGGERS):
        signals.wants_direct_answer = True

    # 4. Follow-up understanding
    if _has_followup_reference(msg_lower, conversation_history):
        signals.has_followup = True

    # 5. Context preservation - handled via profile

    # 6. Ambiguity detection
    if _is_ambiguous(msg_lower, conversation_history):
        signals.is_ambiguous = True

    # 7. Tone adaptation
    signals.tone = _detect_tone(msg_lower)

    # 8. Step-by-step reasoning
    if any(t in msg_lower for t in config.STEP_BY_STEP_TRIGGERS):
        signals.needs_step_by_step = True

    # 9. Example-driven
    if any(t in msg_lower for t in config.EXAMPLE_TRIGGERS):
        signals.needs_examples = True

    # 10. Citation request
    if any(t in msg_lower for t in config.CITATION_TRIGGERS):
        signals.needs_citations = True

    # 11. Bullet vs narrative
    if any(t in msg_lower for t in config.BULLET_TRIGGERS):
        signals.prefers_bullet_points = True
    if any(t in msg_lower for t in config.NARRATIVE_TRIGGERS):
        signals.prefers_narrative = True

    # 12. Technical depth
    if any(t in msg_lower for t in config.TECH_LOW_TRIGGERS):
        signals.technical_depth = "low"
    elif any(t in msg_lower for t in config.TECH_HIGH_TRIGGERS):
        signals.technical_depth = "high"

    # 13. Creative vs factual - handled via QueryMode

    # 14. Coding intent - handled via QueryMode + profile

    # 15. Instructional mode - handled via QueryMode

    # 16. Urgency / brevity
    if any(t in msg_lower for t in config.URGENCY_TRIGGERS):
        signals.urgency = "high"

    # Phase 7: Capability hints
    signals.capability_hint = _detect_capability_hint(msg_lower, signals)
    signals.tool_need = _detect_tool_need(msg_lower, signals)

    return signals


def _has_followup_reference(msg_lower: str, conversation_history: list[dict] | None) -> bool:
    """Check if message references prior conversation."""
    # Explicit follow-up triggers
    if any(t in msg_lower for t in config.FOLLOWUP_TRIGGERS):
        # But only if there IS prior context
        if conversation_history and len(conversation_history) > 0:
            return True
    return False


def _is_ambiguous(msg_lower: str, conversation_history: list[dict] | None) -> bool:
    """Detect ambiguous/underspecified requests."""
    # Explicit ambiguity triggers
    if any(t in msg_lower for t in config.AMBIGUITY_TRIGGERS):
        return True

    # Very short query with pronouns but no context
    if len(msg_lower) < 20:
        pronouns = {"it", "that", "this", "them", "those", "he", "she", "they"}
        words = set(msg_lower.split())
        if words & pronouns and not conversation_history:
            return True

    # Underspecified "how to" / "how do i" without domain
    if (msg_lower.startswith("how to ") or msg_lower.startswith("how do i ")) and len(msg_lower) < 30:
        # Check if it's a complete request (has a verb after the opener)
        incomplete_phrases = ["fix it", "solve it", "resolve it", "handle it", "do it", "make it work"]
        for phrase in incomplete_phrases:
            if phrase in msg_lower:
                return True

    return False


def _detect_tone(msg_lower: str) -> str:
    """Detect user tone from message."""
    # Count matches for each tone category
    tone_scores = Counter()

    for trigger in config.TONE_FORMAL:
        if trigger in msg_lower:
            tone_scores["formal"] += 1

    for trigger in config.TONE_CASUAL:
        if trigger in msg_lower:
            tone_scores["casual"] += 1

    for trigger in config.TONE_EMPATHETIC:
        if trigger in msg_lower:
            tone_scores["empathetic"] += 1

    for trigger in config.TONE_DIRECT:
        if trigger in msg_lower:
            tone_scores["direct"] += 1

    # Return highest scoring tone, or neutral
    if tone_scores:
        return tone_scores.most_common(1)[0][0]
    return "neutral"


def build_conversation_profile(
    conversation_history: list[dict],
    current_user_message: str,
) -> ConversationProfile:
    """Build ConversationProfile from recent message history.

    Analyzes the last N messages (default 10) to extract:
    - Message count
    - Average user message length
    - Recurring topics
    - Code context presence
    - File context presence
    - User preferences (concise vs detailed)
    """
    profile = ConversationProfile()

    if not conversation_history:
        return profile

    # Limit to history window
    recent = conversation_history[-config.HISTORY_WINDOW :]
    profile.message_count = len(recent)

    # Calculate average user message length
    user_messages = [m for m in recent if m.get("role") == "user"]
    if user_messages:
        profile.avg_user_length = sum(len(m.get("content", "")) for m in user_messages) // len(user_messages)

        # Detect user preference for concise vs detailed
        short_count = sum(1 for m in user_messages if len(m.get("content", "")) <= config.CONCISE_THRESHOLD_CHARS)
        long_count = sum(1 for m in user_messages if any(t in m.get("content", "").lower() for t in config.DETAIL_TRIGGERS))
        profile.user_prefers_concise = short_count > len(user_messages) * 0.6
        profile.user_prefers_detailed = long_count > len(user_messages) * 0.3

    # Extract topics (simple keyword extraction from user messages)
    all_user_content = " ".join(m.get("content", "").lower() for m in user_messages)
    # Simple noun phrase extraction - words > 4 chars that appear multiple times
    words = re.findall(r"\b[a-z]{5,}\b", all_user_content)
    word_counts = Counter(words)
    profile.topics = [w for w, c in word_counts.most_common(5) if c >= 2]

    # Detect code context
    for msg in recent:
        content = msg.get("content", "")
        if CODE_FENCE_PATTERN.search(content) or INLINE_CODE_PATTERN.search(content):
            profile.has_code_context = True
            break
        # Check recent user messages for code keywords
        if msg.get("role") == "user":
            words = set(re.findall(r"\b\w+\b", content.lower()))
            if len(words & CODE_KEYWORDS) >= 2:
                profile.has_code_context = True
                break

    # Detect file context (heuristic: mentions of file-like patterns)
    file_patterns = [r"\.[a-z]{2,4}\b", r"file", r"document", r"pdf", r"csv", r"xlsx", r"upload"]
    for msg in recent:
        content = msg.get("content", "").lower()
        if any(re.search(p, content) for p in file_patterns):
            profile.has_file_context = True
            break

    return profile


async def analyze_request(
    messages: list[dict],
    model_id: str,
    temperature: float,
    chat_id: str | None,
    db: any,  # AsyncSession - typed as any to avoid circular import
    user_override: ResponseGuidance | None = None,
) -> ResponseGuidance:
    """Main entry point: analyze request and return complete guidance.

    This is the ONLY function that should be called from api.py.

    Args:
        messages: Full conversation messages (including system, user, assistant)
        model_id: Selected model identifier
        temperature: User temperature setting
        chat_id: Chat ID for history lookup (if continuing)
        db: Database session for fetching chat history
        user_override: Optional user preference override (future feature)

    Returns:
        ResponseGuidance with all signals, profile, and prompt additions
    """
    # For now, extract conversation history from messages parameter
    # (In production, could fetch full history from db using chat_id)
    conversation_history = messages[:-1] if len(messages) > 1 else []
    current_user_msg = messages[-1].get("content", "") if messages else ""

    # If user_override provided, use it as base
    if user_override:
        guidance = user_override
    else:
        # Build profile from history
        profile = build_conversation_profile(conversation_history, current_user_msg)

        # Classify mode
        mode = classify_query_mode(current_user_msg, conversation_history, profile)

        # Detect intent signals
        intent = detect_intent_signals(current_user_msg, conversation_history, profile)

        # Adjust for profile preferences
        if profile.user_prefers_concise and not intent.wants_detailed:
            intent.wants_concise = True
        if profile.user_prefers_detailed and not intent.wants_concise:
            intent.wants_detailed = True

        if profile.has_code_context:
            intent.technical_depth = "high"

        guidance = ResponseGuidance(
            mode=mode,
            intent=intent,
            profile=profile,
        )

    # Build system prompt additions
    from backend.response_intelligence.prompt_injector import build_system_prompt_additions
    guidance.system_prompt_additions = build_system_prompt_additions(guidance)

    # Add constraints based on signals
    _apply_constraints(guidance)

    return guidance


def _apply_constraints(guidance: ResponseGuidance) -> None:
    """Apply structured constraints based on guidance signals."""
    intent = guidance.intent
    config_obj = config

    if intent.wants_concise:
        guidance.constraints["max_paragraphs"] = config_obj.MAX_PARAGRAPHS_CONCISE

    if intent.urgency == "high":
        guidance.constraints["max_tokens"] = config_obj.MAX_TOKENS_URGENCY

    if intent.needs_step_by_step:
        guidance.constraints["structure"] = "numbered_steps"

    if intent.prefers_bullet_points:
        guidance.constraints["structure"] = "bullet_points"

    if intent.needs_examples:
        guidance.constraints["include_examples"] = True

    if intent.needs_citations:
        guidance.constraints["cite_sources"] = True


def _detect_capability_hint(msg_lower: str, signals: IntentSignal) -> str:
    """Detect high-level capability hint from message and signals."""
    # Explicit file operations
    if any(phrase in msg_lower for phrase in ["list files", "show files", "read file", "list the files", "show me the files"]):
        return "file"
    # Explicit web search
    if any(phrase in msg_lower for phrase in ["search web", "web search", "google", "look up", "find information", "search for"]):
        return "web"
    # Explicit code execution
    if any(phrase in msg_lower for phrase in ["execute code", "run code", "run this code", "execute this", "run python"]):
        return "tool"
    # File-related context
    if any(word in msg_lower for word in ["file", "files", "directory", "folder", "project", "codebase", "repository", "repo"]):
        # But only if not just explaining
        if not signals.wants_direct_answer and not signals.technical_depth == "low":
            return "file"
    # Research context
    if any(word in msg_lower for word in ["news", "latest", "current", "today", "recent", "up to date", "who won", "what happened"]):
        return "web"
    return "none"


def _detect_tool_need(msg_lower: str, signals: IntentSignal) -> str:
    """Detect tool need level from message and signals."""
    # High confidence: explicit tool requests
    if any(phrase in msg_lower for phrase in ["list files", "read file", "search web", "execute code", "run code"]):
        return "likely"
    # Medium: context suggests tool but not explicit
    if signals.capability_hint != "none":
        return "possible"
    # Low: pure explanation/understanding
    if signals.wants_direct_answer or signals.technical_depth == "low":
        return "none"
    return "none"