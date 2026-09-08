"""Prompt injection for Response Intelligence.

Translates structured ResponseGuidance into system prompt additions.
Provider-neutral: works with all providers that support system messages.
"""
from __future__ import annotations

from backend.response_intelligence.schema import ResponseGuidance, QueryMode


def build_system_prompt_additions(guidance: ResponseGuidance) -> list[str]:
    """Convert structured guidance into system prompt lines.

    Each addition is a single instructional sentence.
    Multiple additions are joined with newlines and injected as
    a single system message.
    """
    additions: list[str] = []

    # --- Mode-specific base instructions ---
    _add_mode_instructions(guidance.mode, additions)

    # --- Intent-driven behavioral instructions ---
    intent = guidance.intent

    if intent.wants_concise:
        additions.append("Be concise. Maximum 2-3 short paragraphs. No fluff or preamble.")

    if intent.wants_detailed:
        additions.append("Provide comprehensive coverage. Include nuances, edge cases, and relevant context.")

    if intent.wants_direct_answer:
        additions.append("START with the direct, specific answer. Only then add supporting context if needed.")

    if intent.has_followup:
        additions.append("This is a follow-up question. Maintain continuity with prior context. Reference previous details explicitly.")

    if intent.is_ambiguous:
        additions.append("The request is ambiguous. State your assumptions clearly before answering, or ask for clarification.")

    if intent.needs_step_by_step:
        additions.append("Structure your response as clear, numbered steps. Each step should be self-contained and actionable.")

    if intent.needs_examples:
        additions.append("Include concrete, practical examples for each key concept or step.")

    if intent.needs_citations:
        additions.append("Cite sources inline using [source] format. Distinguish between established facts and inferences.")

    if intent.prefers_bullet_points:
        additions.append("Use bullet points for lists and key points. Group related items logically.")

    if intent.prefers_narrative:
        additions.append("Write in flowing narrative form. Connect ideas smoothly with transitions.")

    # Technical depth
    if intent.technical_depth == "low":
        additions.append("Explain in simple terms (ELI5). Avoid jargon. Use analogies where helpful.")
    elif intent.technical_depth == "high":
        additions.append("Use precise technical terminology. Assume professional expertise. Include implementation details.")

    # Tone adaptation
    _add_tone_instruction(intent.tone, additions)

    # Urgency
    if intent.urgency == "high":
        additions.append("Prioritize brevity. Skip background, caveats, and pleasantries unless essential.")

    # --- Structured constraints ---
    for key, val in guidance.constraints.items():
        if key == "max_paragraphs":
            additions.append(f"Limit response to {val} paragraphs maximum.")
        elif key == "max_tokens":
            additions.append(f"Target approximately {val} tokens. Be succinct.")
        elif key == "structure":
            if val == "numbered_steps":
                additions.append("Use numbered step format (1., 2., 3...).")
            elif val == "bullet_points":
                additions.append("Use bullet point format for structured content.")
        elif key == "include_examples":
            additions.append("Include at least one concrete example per major point.")
        elif key == "cite_sources":
            additions.append("Provide inline citations for factual claims.")

    return additions


def _add_mode_instructions(mode: QueryMode, additions: list[str]) -> None:
    """Add mode-specific base instructions."""
    mode_instructions = {
        QueryMode.FACTUAL: (
            "Prioritize factual accuracy above all. Lead with the direct answer. "
            "Distinguish verified facts from speculation. Cite sources when possible."
        ),
        QueryMode.CREATIVE: (
            "Be creative, expressive, and engaging. Use vivid language, metaphor, and narrative flair. "
            "Prioritize originality and emotional resonance over strict accuracy."
        ),
        QueryMode.CODING: (
            "Provide working, idiomatic, production-ready code. Explain non-obvious parts. "
            "Follow best practices for the target language/framework. Include error handling."
        ),
        QueryMode.ANALYSIS: (
            "Structure as rigorous analysis: observation → evidence → reasoning → conclusion. "
            "Present multiple perspectives. Quantify trade-offs. Avoid unsubstantiated claims."
        ),
        QueryMode.CONVERSATIONAL: (
            "Be helpful, natural, and context-aware. Match the user's tone and depth. "
            "Ask clarifying questions when genuinely uncertain."
        ),
        QueryMode.INSTRUCTIONAL: (
            "Teach step-by-step. Use clear numbered steps with prerequisites. "
            "Check understanding at each stage. Anticipate common pitfalls."
        ),
    }
    if mode in mode_instructions:
        additions.append(mode_instructions[mode])


def _add_tone_instruction(tone: str, additions: list[str]) -> None:
    """Add tone-specific instruction."""
    tone_map = {
        "formal": "Use formal, professional language. Complete sentences. Polite address.",
        "casual": "Use conversational, friendly language. Contractions and informal phrasing welcome.",
        "empathetic": "Show understanding and validation. Acknowledge concerns before solving. Warm, supportive tone.",
        "direct": "Be direct and action-oriented. Minimize pleasantries. Focus on what to do.",
        "neutral": "",  # No special instruction needed
    }
    if tone in tone_map and tone_map[tone]:
        additions.append(tone_map[tone])


def format_guidance_for_debug(guidance: ResponseGuidance) -> str:
    """Format guidance for logging/debugging."""
    lines = [
        f"=== Response Intelligence Guidance ===",
        f"Mode: {guidance.mode.value}",
        f"Confidence: {guidance.confidence:.2f}",
        f"Source: {guidance.source}",
        f"",
        f"Intent Signals:",
        f"  wants_concise: {guidance.intent.wants_concise}",
        f"  wants_detailed: {guidance.intent.wants_detailed}",
        f"  wants_direct_answer: {guidance.intent.wants_direct_answer}",
        f"  has_followup: {guidance.intent.has_followup}",
        f"  is_ambiguous: {guidance.intent.is_ambiguous}",
        f"  needs_step_by_step: {guidance.intent.needs_step_by_step}",
        f"  needs_examples: {guidance.intent.needs_examples}",
        f"  needs_citations: {guidance.intent.needs_citations}",
        f"  prefers_bullet_points: {guidance.intent.prefers_bullet_points}",
        f"  prefers_narrative: {guidance.intent.prefers_narrative}",
        f"  technical_depth: {guidance.intent.technical_depth}",
        f"  tone: {guidance.intent.tone}",
        f"  urgency: {guidance.intent.urgency}",
        f"",
        f"Profile:",
        f"  message_count: {guidance.profile.message_count}",
        f"  avg_user_length: {guidance.profile.avg_user_length}",
        f"  topics: {guidance.profile.topics}",
        f"  has_code_context: {guidance.profile.has_code_context}",
        f"  has_file_context: {guidance.profile.has_file_context}",
        f"  user_prefers_concise: {guidance.profile.user_prefers_concise}",
        f"  user_prefers_detailed: {guidance.profile.user_prefers_detailed}",
        f"",
        f"Constraints: {guidance.constraints}",
        f"",
        f"System Prompt Additions ({len(guidance.system_prompt_additions)}):",
    ]
    for i, addition in enumerate(guidance.system_prompt_additions, 1):
        lines.append(f"  {i}. {addition}")

    return "\n".join(lines)