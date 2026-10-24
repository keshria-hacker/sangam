"""
response_quality/slop.py — no-ai-slop style cleanup (petergyang/no-ai-slop).

Two modes share one pattern catalogue:
- detect: name each pattern found, quote the offending line, do NOT rewrite.
- edit: minimum effective edit (cut, don't add) + a "What changed" list.

Conservative by design — only patterns that are slop in virtually any
context are touched. The catalogue below is the full list of named
patterns (30+); detect/edit both report the pattern *name*, never a
score and never a guess about whether AI wrote the text.

Named patterns (name -> replacement; "" means delete):
  rich-tapestry -> "rich mix", delve-into -> "look at",
  delves-into -> "looks at", delving-into -> "looking at",
  tapestry -> "mix", landscape -> "field", realm -> "area",
  intricate -> "detailed", furthermore -> "also", moreover -> "also",
  additionally -> "also", crucial -> "important", vital -> "important",
  nestled -> "located", boasts -> "has", showcase -> "show",
  bustling -> "busy", meticulous -> "careful",
  ever-evolving -> "changing", foster -> "encourage",
  leverage (verb) -> "use", vibrant -> (deleted),
  unlock -> "enable", unleash(es) -> "use(s)",
  game-changer -> "major improvement", revolutionize* -> "transform",
  cutting-edge -> "new", testament-to -> "sign of",
  important-to-note -> (deleted), worth-noting -> (deleted),
  as-an-ai -> (deleted), todays-fast-paced-world -> (deleted),
  in-conclusion -> (deleted), leading-opener -> (deleted, start only).

Returns (cleaned_text, change_count) for remove_slop; see
remove_slop_with_changes / detect_slop for the richer shapes.
"""
from __future__ import annotations

import re

# (name, regex, replacement) — applied case-insensitively, in order.
# Longer phrases first so "rich tapestry" is one hit, not two.
_PATTERNS: list[tuple[str, str, str]] = [
    ("rich-tapestry", r"\brich\s+tapestry\b", "rich mix"),
    ("delving-into", r"\bdelving\s+into\b", "looking at"),
    ("delves-into", r"\bdelves\s+into\b", "looks at"),
    ("delve-into", r"\bdelve\s+into\b", "look at"),
    ("testament-to", r"\ba\s+testament\s+to\b", "sign of"),
    ("testament-to", r"\btestament\s+to\b", "sign of"),
    ("important-to-note", r"\bit['’]s\s+important\s+to\s+note\s+that\b", ""),
    ("worth-noting", r"\bit['’]s\s+worth\s+(noting|mentioning)\s+that\b", ""),
    ("as-an-ai", r"\bas\s+an\s+ai(\s+language\s+model)?,?", ""),
    ("todays-fast-paced-world",
     r"\bin\s+today['’]s\s+(fast-paced|rapidly\s+changing|digital|modern)\s+(world|age|era|landscape),?", ""),
    ("in-conclusion", r"\bin\s+conclusion,?", ""),
    ("tapestry", r"\btapestry\b", "mix"),
    ("landscape", r"\blandscape\b", "field"),
    ("realm", r"\brealm\b", "area"),
    ("intricate", r"\bintricate\b", "detailed"),
    ("furthermore", r"\bfurthermore\b", "also"),
    ("moreover", r"\bmoreover\b", "also"),
    ("additionally", r"\badditionally\b", "also"),
    ("crucial", r"\bcrucial\b", "important"),
    ("vital", r"\bvital\b", "important"),
    ("nestled", r"\bnestled\b", "located"),
    ("boasts", r"\bboasts\b", "has"),
    ("showcase", r"\bshowcases?\b", "show"),
    ("bustling", r"\bbustling\b", "busy"),
    ("meticulous", r"\bmeticulous\b", "careful"),
    ("ever-evolving", r"\bever-evolving\b", "changing"),
    ("foster", r"\bfoster\b", "encourage"),
    ("leverage", r"\bleverage\b", "use"),
    ("vibrant", r"\bvibrant\b", ""),
    ("unlock", r"\bunlock\b", "enable"),
    ("unleash", r"\bunleashes?\b", "use"),
    ("game-changer", r"\bgame-?changer\b", "major improvement"),
    ("revolutionize", r"\brevolutioniz\w*\b", "transform"),
    ("cutting-edge", r"\bcutting-?edge\b", "new"),
]

# Leading openers stripped only at the very start of the text.
_LEADING_OPENERS = re.compile(
    r"^(great question!|i['’]d be happy to help!?|certainly!|of course!|absolutely!|happy to help!?)\s+",
    re.IGNORECASE,
)

PATTERN_NAMES: list[str] = sorted({name for name, _, _ in _PATTERNS})


def _fix_sentence_starts(text: str) -> str:
    """Capitalize a lowercase word that now starts the text or a sentence."""

    def _cap(match: re.Match) -> str:
        return match.group(1) + match.group(2).upper()

    text = re.sub(r"^(\s*)([a-z])", _cap, text)
    text = re.sub(r"([.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    return text


def _adjust_case(matched: str, replacement: str) -> str:
    if not replacement:
        return replacement
    if matched[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def detect_slop(text: str) -> list[dict]:
    """Name each slop pattern found, quoting its line. Never rewrites.

    Returns [{pattern, line (1-based), quote}]; quote is the full source
    line containing the match, trimmed. A pattern matching twice on one
    line is reported once per line (evidence, not a count).
    """
    if not text:
        return []
    lines = text.splitlines() or [""]
    found: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for name, pattern, _ in _PATTERNS:
        for line_no, line in enumerate(lines, start=1):
            if (name, line_no) in seen:
                continue
            if re.search(pattern, line, flags=re.IGNORECASE):
                seen.add((name, line_no))
                found.append({"pattern": name, "line": line_no, "quote": line.strip()})
    # Leading-opener evidence, if present.
    if _LEADING_OPENERS.search(text.lstrip()):
        first = lines[0].strip() if lines else ""
        if ("leading-opener", 1) not in seen:
            found.append({"pattern": "leading-opener", "line": 1, "quote": first})
    found.sort(key=lambda d: (d["line"], d["pattern"]))
    return found


def remove_slop_with_changes(text: str) -> tuple[str, list[dict]]:
    """Edit mode: minimum edit + a 'What changed' list.

    Returns (cleaned, changes) where each change is
    {pattern, before, after}. 'before' is the exact matched text,
    'after' is the replacement after case adjustment ("" = deleted).
    """
    if not text or not text.strip():
        return text, []
    changes: list[dict] = []

    def _swap(name: str, replacement: str):
        def _cb(match: re.Match) -> str:
            after = _adjust_case(match.group(0), replacement)
            changes.append({"pattern": name, "before": match.group(0), "after": after})
            return after

        return _cb

    for name, pattern, replacement in _PATTERNS:
        text = re.sub(pattern, _swap(name, replacement), text, flags=re.IGNORECASE)

    def _opener_cb(match: re.Match) -> str:
        changes.append({"pattern": "leading-opener", "before": match.group(0).strip(), "after": ""})
        return ""

    text, n = _LEADING_OPENERS.subn(_opener_cb, text)
    if changes:
        # Tidy whitespace left behind by deletions.
        text = re.sub(r"[ \t]{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = _fix_sentence_starts(text.strip())
    return text, changes


def remove_slop(text: str) -> tuple[str, int]:
    """Remove AI slop patterns. Returns (cleaned, change_count)."""
    cleaned, changes = remove_slop_with_changes(text)
    return cleaned, len(changes)
