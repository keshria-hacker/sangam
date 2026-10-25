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


# --- Code / protected-term protection -------------------------------------
# Slop patterns must NEVER rewrite code, identifiers, function names,
# error strings, or caller-protected names. Both modes below therefore
# work on prose only: fenced code blocks are skipped wholesale, inline
# `code` spans are masked with same-length spaces (so offsets and line
# numbers survive), and caller-supplied `protected` phrases are masked
# the same way. A product literally named "Crucial" is only safe if the
# caller passes it in `protected` — prose words are otherwise fair game,
# and that limit is stated here rather than hidden.

def _mask_spans(line: str, protected: list[str] | None) -> str:
    """Blank inline-code spans and protected phrases, preserving length."""
    masked = re.sub(r"`[^`\n]+`", lambda m: " " * len(m.group(0)), line)
    for phrase in protected or []:
        if not phrase:
            continue
        masked = re.sub(
            re.escape(phrase), lambda m: " " * len(m.group(0)), masked,
            flags=re.IGNORECASE,
        )
    return masked


def _split_fence_blocks(text: str) -> list[tuple[bool, str]]:
    """Split text into (is_code, block) runs. Fence lines belong to code."""
    lines = text.split("\n")
    blocks: list[tuple[bool, list[str]]] = []
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            is_code = True
        else:
            is_code = in_fence
        if blocks and blocks[-1][0] == is_code:
            blocks[-1][1].append(line)
        else:
            blocks.append((is_code, [line]))
    return [(is_code, "\n".join(ls)) for is_code, ls in blocks]


def _split_protected(part: str, protected: list[str] | None) -> list[tuple[bool, str]]:
    """Split a prose part into (is_protected, chunk) pieces."""
    if not protected:
        return [(False, part)]
    phrases = [p for p in protected if p]
    if not phrases:
        return [(False, part)]
    pattern = "(" + "|".join(re.escape(p) for p in phrases) + ")"
    pieces = re.split(pattern, part, flags=re.IGNORECASE)
    out: list[tuple[bool, str]] = []
    for piece in pieces:
        if not piece:
            continue
        out.append((any(piece.lower() == p.lower() for p in phrases), piece))
    return out


def detect_slop(text: str, protected: list[str] | None = None) -> list[dict]:
    """Name each slop pattern found, quoting its line. Never rewrites.

    Returns [{pattern, line (1-based), quote}]; quote is the full source
    line containing the match, trimmed. A pattern matching twice on one
    line is reported once per line (evidence, not a count).
    Code fences, inline code, and `protected` phrases are never flagged.
    """
    if not text:
        return []
    lines = text.splitlines() or [""]
    found: list[dict] = []
    seen: set[tuple[str, int]] = set()
    in_fence = False
    for line_no, line in enumerate(lines, start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        masked = _mask_spans(line, protected)
        for name, pattern, _ in _PATTERNS:
            if (name, line_no) in seen:
                continue
            if re.search(pattern, masked, flags=re.IGNORECASE):
                seen.add((name, line_no))
                found.append({"pattern": name, "line": line_no, "quote": line.strip()})
    # Leading-opener evidence, if present (and the text starts in prose).
    if not (lines and lines[0].strip().startswith("```")) and _LEADING_OPENERS.search(text.lstrip()):
        first = lines[0].strip() if lines else ""
        if ("leading-opener", 1) not in seen:
            found.append({"pattern": "leading-opener", "line": 1, "quote": first})
    found.sort(key=lambda d: (d["line"], d["pattern"]))
    return found


def remove_slop_with_changes(
    text: str, protected: list[str] | None = None
) -> tuple[str, list[dict]]:
    """Edit mode: minimum edit + a 'What changed' list.

    Returns (cleaned, changes) where each change is
    {pattern, before, after}. 'before' is the exact matched text,
    'after' is the replacement after case adjustment ("" = deleted).
    Code fences, inline code spans, and `protected` phrases are copied
    through byte-for-byte — only prose is ever edited.
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

    def _edit_prose_block(block: str) -> str:
        # Split by inline code spans; edit prose parts only.
        parts = re.split(r"(`[^`\n]+`)", block)
        edited_parts: list[str] = []
        for part in parts:
            if part.startswith("`") and part.endswith("`") and len(part) >= 2:
                edited_parts.append(part)
                continue
            chunks: list[str] = []
            for is_protected, chunk in _split_protected(part, protected):
                if is_protected:
                    chunks.append(chunk)
                    continue
                for name, pattern, replacement in _PATTERNS:
                    chunk = re.sub(pattern, _swap(name, replacement), chunk, flags=re.IGNORECASE)
                chunks.append(chunk)
            edited_parts.append("".join(chunks))
        return "".join(edited_parts)

    out_blocks: list[str] = []
    for is_code, block in _split_fence_blocks(text):
        out_blocks.append(block if is_code else _edit_prose_block(block))
    text = "\n".join(out_blocks)

    def _opener_cb(match: re.Match) -> str:
        changes.append({"pattern": "leading-opener", "before": match.group(0).strip(), "after": ""})
        return ""

    # Leading opener only when the text starts in prose, not in a fence.
    if not text.lstrip().startswith("```"):
        text, _n = _LEADING_OPENERS.subn(_opener_cb, text)
    if changes:
        # Tidy whitespace left behind by deletions, prose blocks only, so
        # code indentation is never collapsed.
        cleaned_blocks: list[str] = []
        for is_code, block in _split_fence_blocks(text):
            if is_code:
                cleaned_blocks.append(block)
            else:
                block = re.sub(r"[ \t]{2,}", " ", block)
                block = re.sub(r"\n{3,}", "\n\n", block)
                cleaned_blocks.append(_fix_sentence_starts(block.strip()))
        text = "\n".join(cleaned_blocks).strip()
        # Restoring the original trailing newline behaviour is unnecessary:
        # callers compare stripped prose; code blocks keep their newlines
        # because fence-block joins above preserve them.
    return text, changes


def remove_slop(text: str, protected: list[str] | None = None) -> tuple[str, int]:
    """Remove AI slop patterns. Returns (cleaned, change_count)."""
    cleaned, changes = remove_slop_with_changes(text, protected=protected)
    return cleaned, len(changes)
