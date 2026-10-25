"""
response_quality/humanizer.py — natural-rewriting style mode.

Honest boundary, stated in the code, the UI, and the docs: this is a
READABILITY rewrite — slop removal, filler deletion, and splitting
over-long sentences — that makes text plainer and more natural to
read. It is NOT an AI-detection evasion tool: it makes no claim about
any detector (Turnitin, GPTZero, or any other), it does not strip
authorship signals, invisible characters, or watermarks, and it must
never be described as bypassing detection. The upstream
Turnitout-Humanizer repo's stated purpose (defeating detectors) is
explicitly NOT ported; only the generic, legitimate half — plainer
phrasing — is implemented here, under Sangam's own wording.

Mechanics (deterministic, no model, no network):
1. slop edit (remove_slop_with_changes) — minimum edit + change list.
2. filler deletion — a small list of throat-clearing phrases removed
   only where they add no information.
3. long-sentence split — sentences over 45 words are split at the
   first ", and" / ";" / ", but" boundary; if no boundary exists the
   sentence is left alone (never rewritten by guessing).

Returns (rewritten, changes) where changes extend the slop change
list with {pattern, before, after} entries for steps 2 and 3.
"""
from __future__ import annotations

import re

from .slop import remove_slop_with_changes

_FILLERS: list[tuple[str, str]] = [
    ("filler-phrase", r"\bin this (blog post|article|piece),?\s*", ""),
    ("filler-phrase", r"\bit goes without saying that\s+", ""),
    ("filler-phrase", r"\bneedless to say,?\s+", ""),
    ("filler-phrase", r"\bas we all know,?\s+", ""),
    ("filler-phrase", r"\bwhen it comes to\s+", "For "),
]

_SPLIT_AT = re.compile(r"[,;]\s+(and|but|so|yet)\s+")
_MAX_SENTENCE_WORDS = 45

HONEST_NOTE = (
    "Natural rewrite for readability: slop removed, filler cut, "
    "over-long sentences split. This does not evade AI detectors, "
    "does not conceal authorship, and makes no claim about any "
    "detector's result."
)


def _split_long_sentences(text: str) -> tuple[str, list[dict]]:
    """Split >45-word sentences at a conjunction boundary, once each."""
    changes: list[dict] = []
    parts = re.split(r"(?<=[.!?])\s+", text)
    out: list[str] = []
    for sent in parts:
        words = sent.split()
        if len(words) > _MAX_SENTENCE_WORDS:
            m = _SPLIT_AT.search(sent)
            if m:
                first = sent[:m.start()].strip()
                rest = sent[m.end():].strip()
                rest = rest[:1].upper() + rest[1:] if rest else rest
                if not first.endswith((".", "!", "?")):
                    first += "."
                changes.append({"pattern": "long-sentence-split",
                                "before": sent, "after": f"{first} {rest}"})
                out.append(f"{first} {rest}")
                continue
        out.append(sent)
    return " ".join(out), changes


def natural_rewrite(text: str) -> tuple[str, list[dict]]:
    """Rewrite for natural, readable phrasing. Returns (text, changes)."""
    if not text or not text.strip():
        return text, []
    cleaned, changes = remove_slop_with_changes(text)

    def _filler_cb(name: str, replacement: str):
        def _cb(match: re.Match) -> str:
            changes.append({"pattern": name, "before": match.group(0),
                            "after": replacement})
            return replacement
        return _cb

    for name, pattern, replacement in _FILLERS:
        cleaned = re.sub(pattern, _filler_cb(name, replacement), cleaned,
                         flags=re.IGNORECASE)
    cleaned, split_changes = _split_long_sentences(cleaned)
    changes.extend(split_changes)
    if changes:
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, changes
