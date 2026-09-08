"""
prompt_injection.py — heuristic-based prompt injection detection for chat
messages and file uploads.

This is a **first-pass filter**, not a replacement for a dedicated model-based
detector. It flags common prompt injection patterns using lightweight rules
that run in <1ms, giving the app a chance to warn the user before sending
questionable content to the LLM.

The detector is intentionally conservative — high precision over recall.
If you need stronger protection, integrate a dedicated detection model
(e.g. ``protectai/deberta-v3-base-prompt-injection`` via HuggingFace).
"""
from __future__ import annotations

import re
from typing import Any

# Threshold score above which content is flagged as suspicious
# (0.0 = completely clean, 1.0 = definitely an injection)
FLAG_THRESHOLD = 0.6

# Patterns that strongly suggest prompt injection attempts.
# Each pattern has (regex, weight) — the weight is added to the suspicion score
# when the pattern matches.
_INJECTION_PATTERNS: list[tuple[re.Pattern, float]] = [
    # Direct system prompt override attempts
    (re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|directions|prompts|messages|context)", re.IGNORECASE), 0.8),
    (re.compile(r"forget\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|directions|prompts)", re.IGNORECASE), 0.8),
    (re.compile(r"disregard\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions|directions|prompts)", re.IGNORECASE), 0.8),
    (re.compile(r"you\s+(?:are\s+)?(?:now|are free from|no longer)\s+(?:an?|the)\s+AI", re.IGNORECASE), 0.7),
    (re.compile(r"you\s+are\s+(?:now\s+)?(?:a |an |the )?(?:jailbroken|unleashed|unconstrained)", re.IGNORECASE), 0.9),

    # Role-play / DAN-style attacks
    (re.compile(r"Do\s+Anything\s+Now|DAN\b", re.IGNORECASE), 0.9),
    (re.compile(r"you\s+(?:don'?t|do\s+not)\s+have\s+(?:to\s+)?(?:follow|obey|respect)", re.IGNORECASE), 0.7),

    # Output format override attempts
    (re.compile(r"output\s+(?:must\s+)?(?:start|begin)\s+with\s+\"\[?block\]?\"?", re.IGNORECASE), 0.6),
    (re.compile(r"repeat\s+(?:the\s+)?(?:above\s+)?(?:text|message|prompt|words|everything)\s+(?:above|back|verbatim)", re.IGNORECASE), 0.8),
    (re.compile(r"output\s+(?:the\s+)?(?:above\s+)?(?:text|in\s+your\s+prompt)", re.IGNORECASE), 0.7),
    (re.compile(r"show\s+(?:me\s+)?the\s+(?:first|above|initial)\s+\d+\s+words", re.IGNORECASE), 0.5),

    # Encoded / obfuscated payloads
    (re.compile(r"base64\s*(?:decode|encod)", re.IGNORECASE), 0.5),
    (re.compile(r"(?:rot13|rot-13|caesar)\s*(?:decode|decipher)", re.IGNORECASE), 0.4),
    (re.compile(r"hex\s*(?:decode|encod)", re.IGNORECASE), 0.4),
    (re.compile(r"character\s+codes?\s+(?:for|of|separated)", re.IGNORECASE), 0.3),

    # System prompt extraction
    (re.compile(r"what\s+(?:is|are|were|was)\s+(?:your|the)\s+((?:system\s+)?prompt|initial\s+instructions)", re.IGNORECASE), 0.6),
    (re.compile(r"(?:print|reveal|show|display|output|leak|expose)\s+(?:your|the)\s+((?:system\s+)?prompt|instructions|context)", re.IGNORECASE), 0.7),
    (re.compile(r"how\s+are\s+you\s+(?:instructed|programmed|prompted)", re.IGNORECASE), 0.5),
]

# Patterns that are **always** legitimate — used to lower false positives.
_SAFE_PATTERNS: list[re.Pattern] = [
    # Educational contexts
    re.compile(r"(?:example|tutorial|lesson|exercise|homework|assignment).*(?:prompt|injection|jailbreak)", re.IGNORECASE),
    re.compile(r"(?:what|how)\s+(?:is|are|does)\s+(?:a\s+)?(?:prompt\s+)?injection", re.IGNORECASE),
    re.compile(r"(?:defend|protect|guard).*(?:against|from).*(?:prompt|injection)", re.IGNORECASE),
    # Role instruction to an LLM that the user is asking about
    re.compile(r"^(?:explain|describe|discuss|what is|define)\b.{0,30}\b(prompt|injection|jailbreak|dan)\b", re.IGNORECASE),
]


def detect_injection(text: str) -> tuple[bool, float, list[str]]:
    """
    Scan *text* for prompt injection patterns.

    Returns
    -------
    (flagged, score, reasons)
        flagged — True if the suspicion score exceeds ``FLAG_THRESHOLD``.
        score — the raw suspicion score (0.0 to 1.0+).
        reasons — human-readable list of which patterns matched.
    """
    if not text or not isinstance(text, str) or len(text) < 20:
        return False, 0.0, []

    reasons: list[str] = []
    score = 0.0

    for pattern, weight in _INJECTION_PATTERNS:
        if pattern.search(text):
            score += weight
            reasons.append(f"Matched: {pattern.pattern[:60]}")

    # Deduct for safe patterns
    for pattern in _SAFE_PATTERNS:
        if pattern.search(text):
            score = max(0.0, score - 0.4)

    flagged = score >= FLAG_THRESHOLD
    return flagged, score, reasons


def sanitize_for_log(text: str, max_len: int = 500) -> str:
    """Truncate and strip control chars for safe logging."""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "..."
    return cleaned


def validate_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Validate a list of chat messages for prompt injection.

    Returns the messages unchanged (the API layer uses the returned list for
    downstream logging/warnings). Suspicious messages are flagged via the
    ``_injection_warning`` key in the metadata.

    The caller should decide whether to proceed or return a warning.
    """
    for msg in messages:
        content = msg.get("content", "")
        if not isinstance(content, str) or not content:
            continue
        flagged, score, reasons = detect_injection(content)
        if flagged:
            # Surface the warning but don't strip — the model can handle
            # many flagged inputs safely; we just note the risk.
            msg["_injection_warning"] = {
                "score": round(score, 2),
                "reasons": reasons,
            }
    return messages
