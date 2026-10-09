"""
response_quality/adhd.py — ADHD-friendly formatting (ayghri/i-have-adhd).

"Stop burying the answer": strip throat-clearing openers and break walls
of text into scannable chunks. Deterministic and conservative — it never
reorders content, only trims the top and reflows long paragraphs.

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
    return text, changes
