"""
response_quality/slop.py — no-ai-slop style cleanup (petergyang/no-ai-slop).

Removes high-confidence AI slop: purple-prose verbs/nouns get plainer
replacements, filler hedges get deleted. Conservative by design — only
patterns that are slop in virtually any context are touched.

Returns (cleaned_text, change_count).
"""
from __future__ import annotations

import re

# (pattern, replacement) — applied case-insensitively, in order.
# A replacement of "" deletes the match; the next word is capitalized when
# the deletion starts a sentence.
_SWAPS: list[tuple[str, str]] = [
    (r"\bdelving\s+into\b", "looking at"),
    (r"\bdelves\s+into\b", "looks at"),
    (r"\bdelve\s+into\b", "look at"),
    (r"\btapestry\b", "mix"),
    (r"\bvibrant\b", ""),
    (r"\btestament\s+to\b", "sign of"),
    (r"\bunlock\b", "enable"),
    (r"\bunleashes?\b", "uses"),
    (r"\bgame-?changer\b", "major improvement"),
    (r"\brevolutioniz\w*\b", "transform"),
    (r"\bcutting-?edge\b", "new"),
]

# Filler hedges deleted outright (sentence-start capitalization fixed after).
_DELETIONS: list[str] = [
    r"\bit['’]s\s+important\s+to\s+note\s+that\b",
    r"\bit['’]s\s+worth\s+(noting|mentioning)\s+that\b",
    r"\bas\s+an\s+ai(\s+language\s+model)?,?",
    r"\bin\s+today['’]s\s+(fast-paced|rapidly\s+changing|digital|modern)\s+(world|age|era|landscape),?",
    r"\bin\s+conclusion,?",
]

# Leading openers stripped only at the very start of the text.
_LEADING_OPENERS = re.compile(
    r"^(great question!|i['’]d be happy to help!?|certainly!|of course!|absolutely!|happy to help!?)\s+",
    re.IGNORECASE,
)


def _fix_sentence_starts(text: str) -> str:
    """Capitalize a lowercase word that now starts the text or a sentence."""

    def _cap(match: re.Match) -> str:
        return match.group(1) + match.group(2).upper()

    text = re.sub(r"^(\s*)([a-z])", _cap, text)
    text = re.sub(r"([.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    return text


def remove_slop(text: str) -> tuple[str, int]:
    """Remove AI slop patterns. Returns (cleaned, change_count)."""
    if not text or not text.strip():
        return text, 0
    changes = 0

    def _swap(match: re.Match, replacement: str) -> str:
        nonlocal changes
        changes += 1
        word = match.group(0)
        # Preserve leading capitalization ("Delve into" -> "Look at").
        if word[:1].isupper():
            replacement = replacement[:1].upper() + replacement[1:] if replacement else replacement
        return replacement

    for pattern, replacement in _SWAPS:
        text = re.sub(pattern, lambda m: _swap(m, replacement), text, flags=re.IGNORECASE)
    for pattern in _DELETIONS:
        new_text, n = re.subn(pattern, "", text, flags=re.IGNORECASE)
        if n:
            changes += n
            text = new_text
    new_text, n = _LEADING_OPENERS.subn("", text)
    if n:
        changes += n
        text = new_text

    if changes:
        # Tidy whitespace left behind by deletions.
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = _fix_sentence_starts(text.strip())
    return text, changes
