"""
response_quality/adhd.py — ADHD-friendly formatting (ayghri/i-have-adhd).

What this module actually does (deterministic, post-hoc, and nothing
more — the Settings help text says exactly this):
- strips throat-clearing openers from the start of the text,
- collapses excessive blank lines,
- reflows paragraphs over 600 chars into ~400-char chunks,
- caps lists at 5 items, appending a "+N more" note (never silently
  dropping items without that note).

What it does NOT do: it never reorders content, never numbers steps,
never makes the answer first, never adds time estimates, and never
restates per-turn state. Those prompt-level behaviours live in
adhd_style_text() — a system-prompt style block, not a text transform.
Deep-memory wiring: that block IS now injected into the chat prompt
path (chat_stream_routes.py, after memory injection, before context
truncation) when the user's ``adhdFriendly`` setting is on, via
``adhd_style_enabled`` + ``apply_adhd_style_to_messages`` below.

Returns (formatted_text, change_count).
"""
from __future__ import annotations

import re

# Throat-clearing openers stripped from the very start of the response.
_OPENERS = re.compile(
    r"^(great question!|happy to help!?|i['’]d be happy to help!?|certainly!|of course!|"
    r"absolutely!|good question!|thanks for asking!?)\s+",
    re.IGNORECASE,
)

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_MAX_PARA = 600   # paragraphs longer than this get reflowed
_TARGET_CHUNK = 400  # reflowed chunks aim under this length


def _split_sentences(paragraph: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(paragraph.strip()) if s]


def _reflow(paragraph: str) -> tuple[str, bool]:
    """Split an over-long paragraph at sentence boundaries."""
    if len(paragraph) <= _MAX_PARA:
        return paragraph, False
    # Don't reflow code blocks or lists — only prose walls.
    stripped = paragraph.lstrip()
    if stripped.startswith(("```", "-", "*", "1.", "|")):
        return paragraph, False
    sentences = _split_sentences(paragraph)
    if len(sentences) < 2:
        return paragraph, False
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + 1 + len(sentence) > _TARGET_CHUNK:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    if len(chunks) < 2:
        return paragraph, False
    return "\n\n".join(chunks), True


_LIST_ITEM = re.compile(r"^(\s*)([-*]|\d+[.)])\s+\S")


def _cap_lists(text: str) -> tuple[str, int]:
    """Cap each run of consecutive list items at 5, appending '+N more'.

    Code fences are left alone. A capped list keeps its first 5 items and
    gains one trailing line like '+2 more' — the count is always stated,
    so items are never silently dropped.
    """
    lines = text.split("\n")
    out: list[str] = []
    changes = 0
    i = 0
    in_fence = False
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            i += 1
            continue
        if not in_fence and _LIST_ITEM.match(line):
            group = [line]
            j = i + 1
            while j < len(lines) and _LIST_ITEM.match(lines[j]):
                group.append(lines[j])
                j += 1
            if len(group) > 5:
                out.extend(group[:5])
                out.append(f"+{len(group) - 5} more")
                changes += 1
            else:
                out.extend(group)
            i = j
            continue
        out.append(line)
        i += 1
    return "\n".join(out), changes


def adhd_format(text: str) -> tuple[str, int]:
    """Apply ADHD-friendly formatting. Returns (formatted, change_count)."""
    if not text or not text.strip():
        return text, 0
    changes = 0

    new_text, n = _OPENERS.subn("", text.lstrip())
    if n:
        changes += n
        text = new_text.lstrip()

    # Collapse excessive blank lines.
    new_text, n = re.subn(r"\n{3,}", "\n\n", text)
    if n:
        changes += n
        text = new_text

    # Reflow walls of text.
    paragraphs = text.split("\n\n")
    reflowed: list[str] = []
    for para in paragraphs:
        new_para, did = _reflow(para)
        if did:
            changes += 1
        reflowed.append(new_para)
    text = "\n\n".join(reflowed).strip()

    # Cap long lists at 5 items (+N more note).
    text, n = _cap_lists(text)
    changes += n
    return text, changes


def adhd_style_enabled(settings_json: str | None) -> bool:
    """Is the prompt-level ADHD style on for this user?

    Reads the same ``adhdFriendly`` flag the post-hoc formatting
    toggle already uses (stored in UserPreference.settings_json).
    Invalid / missing JSON -> False: when off, nothing changes.
    """
    if not settings_json:
        return False
    try:
        import json as _json

        settings = _json.loads(settings_json)
    except (ValueError, TypeError):
        return False
    return bool(settings.get("adhdFriendly", False)) if isinstance(settings, dict) else False


def apply_adhd_style_to_messages(messages: list) -> list:
    """Prepend the ADHD style block as a system message (deep-memory wiring).

    Returns a NEW list; the input is never mutated. Callers insert
    this into the chat prompt path only when ``adhd_style_enabled``
    is True — when off, the prompt path is byte-for-byte unchanged.
    """
    return [{"role": "system", "content": adhd_style_text()}, *list(messages)]


def adhd_style_text() -> str:
    """Prompt-level ADHD style block (ayghri/i-have-adhd, 10 rules).

    This is TEXT for a system prompt, not a transform: it tells the model
    how to write. It is served at GET /api/quality/adhd-style and,
    when the user's ``adhdFriendly`` setting is on, injected into the
    chat system prompt by chat_stream_routes.py (deep-memory wiring).
    """
    return (
        "ADHD-friendly style — follow these rules for this reply:\n"
        "1. Lead with the next action: the first line is something doable now, not context or a plan.\n"
        "2. Number multi-step tasks: one bounded action per step, fewest steps that still work.\n"
        "3. End with one concrete next step, so work does not stall between turns.\n"
        "4. Suppress tangents: park second issues as their own question at the end.\n"
        "5. Restate state every turn (e.g. 'step 3 of 5') — nothing held only in the reader's memory.\n"
        "6. Give specific time estimates in minutes, never 'a bit'.\n"
        "7. Make wins visible: plainly state what now works.\n"
        "8. Matter-of-fact errors: cause + fix, no 'oops'.\n"
        "9. Cap lists at 5 items: longer lists split into 'do now' / 'later'.\n"
        "10. No preamble, no recap, no closers: no 'Great question!', no 'Hope this helps!'."
    )
