"""Configuration for Response Intelligence Layer.

Feature flags, trigger keywords, and thresholds for the 16 adaptive behaviors.
All values can be overridden via environment variables.
"""
from pydantic import BaseModel, Field


class ResponseIntelligenceConfig(BaseModel):
    """Configuration for the response intelligence analyzer."""

    # Global feature flag
    ENABLED: bool = True

    # --- Query Length Thresholds ---
    CONCISE_THRESHOLD_CHARS: int = 50

    # --- Behavior Trigger Keywords ---

    # 1. Concise by default - short queries
    # Uses CONCISE_THRESHOLD_CHARS

    # 2. Detail on demand
    DETAIL_TRIGGERS: list[str] = [
        "detail", "comprehensive", "thorough", "explain fully", "in depth",
        "deep dive", "elaborate", "expand on", "more detail"
    ]

    # 3. Direct answer first (factual queries)
    DIRECT_ANSWER_TRIGGERS: list[str] = [
        "what is", "when did", "who is", "where is", "capital of",
        "definition of", "define ", "meaning of", "how many", "how much",
        "which ", "name ", "list ", "give me the"
    ]

    # 4. Follow-up understanding
    FOLLOWUP_TRIGGERS: list[str] = [
        "that", "it", "the previous", "above", "earlier", "before",
        "this", "those", "them", "it's", "its", "his", "her", "their",
        "why", "continue", "more", "elaborate", "go on", "next"
    ]

    # 5. Context preservation - based on conversation history length
    # Uses HISTORY_WINDOW, MIN_HISTORY_FOR_PROFILE

    # 6. Ambiguity detection
    AMBIGUITY_TRIGGERS: list[str] = [
        "it could be", "maybe", "possibly", "depends", "unclear",
        "not sure", "ambiguous", "vague", "either", "or", "something"
    ]

    # 7. Tone adaptation
    TONE_FORMAL: list[str] = [
        "please", "kindly", "would you", "could you", "may i", "i would appreciate"
    ]
    TONE_CASUAL: list[str] = [
        "hey", "hi there", "thanks!", "cool", "awesome", "great", "nice", "lol", "haha"
    ]
    TONE_EMPATHETIC: list[str] = [
        "frustrated", "confused", "worried", "help me understand", "struggling", "difficult", "overwhelmed", "concerned"
    ]
    TONE_DIRECT: list[str] = [
        "just", "only", "quickly", "fast", "brief", "skip", "straight to", "cut to"
    ]

    # 8. Step-by-step reasoning
    STEP_BY_STEP_TRIGGERS: list[str] = [
        "step by step", "walk through", "walk me through", "how to",
        "guide me", "show steps", "break down", "explain each step"
    ]

    # 9. Example-driven
    EXAMPLE_TRIGGERS: list[str] = [
        "example", "show me", "for instance", "like ", "such as", "illustrate", "demonstrate", "sample"
    ]

    # 10. Citation/request evidence
    CITATION_TRIGGERS: list[str] = [
        "cite", "source", "reference", "evidence", "proof", "where did you", "back up", "verify", "citation"
    ]

    # 11. Bullet vs narrative
    BULLET_TRIGGERS: list[str] = [
        "list", "bullet", "summary", "key points", "bullet points", "in bullets", "as a list", "enumerate"
    ]
    NARRATIVE_TRIGGERS: list[str] = [
        "story", "narrative", "describe", "tell me about", "walk me through the story", "explain the journey"
    ]

    # 12. Technical depth
    TECH_LOW_TRIGGERS: list[str] = [
        "eli5", "simple terms", "plain english", "like i'm 5", "like im 5", "explain simply", "non-technical", "layman"
    ]
    TECH_HIGH_TRIGGERS: list[str] = [
        "technical", "detailed", "precise", "specification", "specs", "algorithm", "implementation", "architecture", "internals"
    ]

    # 13. Creative vs factual
    # Note: "write a" / "create a" are intentionally NOT here as they're too generic
    # (e.g., "write a function" = coding, "create a table" = coding/sql)
    # Use more specific patterns like "write a poem" instead
    CREATIVE_TRIGGERS: list[str] = [
        "write a poem", "write a story", "write a song", "write fiction",
        "create a story", "create a poem", "create fiction",
        "compose a poem", "compose a story", "compose music",
        "poem", "story", "imagine", "creative", "fiction", "narrative", "compose", "invent", "make up"
    ]
    FACTUAL_TRIGGERS: list[str] = [
        "fact check", "verify", "accurate", "truth", "reliable", "evidence-based", "data-driven"
    ]

    # 14. Coding intent
    CODING_TRIGGERS: list[str] = [
        "function", "debug", "refactor", "api", "class", "method", "variable",
        "code", "script", "program", "algorithm", "implementation",
        "bug", "error", "exception", "stackoverflow", "github", "repository",
        "module", "package", "library", "framework", "endpoint", "database",
        "query", "schema", "migration", "deploy", "docker", "kubernetes"
    ]

    # Phrases containing "code" that are NOT programming-related
    # These are checked first to prevent false positives
    CODING_EXCEPTIONS: list[str] = [
        "code of conduct",
        "code review",  # This IS coding, but we don't want "code of conduct"
        "honor code", "area code", "zip code", "postal code", "dress code",
        "source code", "bytecode", "opcode", "barcode", "qrcode", "qr code",
        "codex", "codify", "codec", "encode", "decode",
        "morse code", "genetic code", "code breaker", "code breaking",
        "color code", "colour code", "status code", "error code", "exit code",
        "coupon code", "promo code", "discount code", "voucher code",
        "activation code", "verification code", "authentication code",
        "authorization code", "access code", "security code", "pin code",
        "unlock code", "recovery code", "backup code", "tap code",
        "nuclear code", "launch code", "building code", "fire code",
    ]

    # 15. Instructional mode
    INSTRUCTIONAL_TRIGGERS: list[str] = [
        "how do i", "how to", "tutorial", "guide", "steps to", "teach me", "show me how", "instruct", "lesson"
    ]

    # 16. Urgency / brevity
    URGENCY_TRIGGERS: list[str] = [
        "quickly", "briefly", "tl;dr", "tldr", "short on time", "hurry", "asap", "fast", "rapid"
    ]

    # --- History Analysis ---
    HISTORY_WINDOW: int = 10
    MIN_HISTORY_FOR_PROFILE: int = 3

    # --- Confidence Thresholds ---
    HIGH_CONFIDENCE: float = 0.8
    LOW_CONFIDENCE: float = 0.4

    # --- Constraints ---
    MAX_PARAGRAPHS_CONCISE: int = 2
    MAX_TOKENS_URGENCY: int = 500


# Global config instance
config = ResponseIntelligenceConfig()


def get_trigger_patterns() -> dict[str, list[str]]:
    """Return all trigger keyword lists as a flat dict for easy iteration."""
    return {
        "detail": config.DETAIL_TRIGGERS,
        "direct_answer": config.DIRECT_ANSWER_TRIGGERS,
        "followup": config.FOLLOWUP_TRIGGERS,
        "ambiguity": config.AMBIGUITY_TRIGGERS,
        "tone_formal": config.TONE_FORMAL,
        "tone_casual": config.TONE_CASUAL,
        "tone_empathetic": config.TONE_EMPATHETIC,
        "tone_direct": config.TONE_DIRECT,
        "step_by_step": config.STEP_BY_STEP_TRIGGERS,
        "example": config.EXAMPLE_TRIGGERS,
        "citation": config.CITATION_TRIGGERS,
        "bullet": config.BULLET_TRIGGERS,
        "narrative": config.NARRATIVE_TRIGGERS,
        "tech_low": config.TECH_LOW_TRIGGERS,
        "tech_high": config.TECH_HIGH_TRIGGERS,
        "creative": config.CREATIVE_TRIGGERS,
        "factual": config.FACTUAL_TRIGGERS,
        "coding": config.CODING_TRIGGERS,
        "instructional": config.INSTRUCTIONAL_TRIGGERS,
        "urgency": config.URGENCY_TRIGGERS,
    }