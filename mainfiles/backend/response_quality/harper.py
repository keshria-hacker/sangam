"""response_quality/harper.py — Harper-class offline lint (suggestions only).

Deterministic, offline, no model, no network. This module wraps the
existing Harper-style rules in backend/writing_lint.py (repeated words,
confusion candidates, double spaces, missing space after punctuation,
unbalanced quotes/parens, repeated punctuation, unknown words) and adds
the protection the response rules require:

* Fenced code blocks (``` ... ```) are blanked line-for-line before
  linting, so a code fence never contributes issues and line numbers
  still match the original text.
* Inline code spans (`...`) are blanked with same-length spaces, so
  identifiers, function names, and error strings inside backticks are
  never flagged or rewritten.
* Lines that look like code (``import x``, ``def f():``, ``x = f(y)``,
  lines containing ``=>``/``::``/``();``) are blanked the same way.

This module NEVER rewrites text and NEVER autocorrects: it returns
suggestions [{rule, line, offset, quote, suggestion}] for a human (or
the UI) to accept or dismiss. Product names, function names, and error
strings survive untouched because they live in code spans/lines, or —
for capitalized prose words — are skipped by writing_lint's own
proper-noun rule.

Use lint_harper() / harper_suggestions(); both are the same function.
"""
from __future__ import annotations

import re

_CODE_LINE = re.compile(
    r"^\s*(import\s|from\s+\S+\s+import\s|def\s+\w+\s*\(|class\s+\w+|"
    r"return\s+\S|const\s+\w+\s*=|let\s+\w+\s*=|var\s+\w+\s*=|"
    r"if\s+.*:\s*$|for\s+.*:\s*$|while\s+.*:\s*$)"
)
_CODE_CHARS = re.compile(r"=>|::|\(\);|;\s*$")


def _blank_inline_code(line: str) -> str:
    """Replace `code` spans with same-length spaces (offsets preserved)."""
    def _blank(match: re.Match) -> str:
        return " " * len(match.group(0))

    return re.sub(r"`[^`\n]+`", _blank, line)


def _prose_only_text(text: str) -> str:
    """Return text with code regions blanked, line count preserved."""
    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        if in_fence:
            out.append("")
            continue
        if _CODE_LINE.match(line) or _CODE_CHARS.search(line):
            out.append("")
            continue
        out.append(_blank_inline_code(line))
    return "\n".join(out)


def lint_harper(text: str) -> list[dict]:
    """Offline lint suggestions. Never modifies text, never autocorrects.

    Returns [{rule, line, offset, quote, suggestion?}] with line numbers
    into the ORIGINAL text. Code fences, inline code, and code-looking
    lines produce no issues by construction (they are blanked first).
    """
    if not text or not text.strip():
        return []
    from ..writing_lint import lint_text

    cleaned = _prose_only_text(text)
    issues = lint_text(cleaned)
    # Drop issues whose quote is only whitespace (blanked code regions).
    return [i for i in issues if (i.get("quote") or "").strip()]


def harper_suggestions(text: str) -> list[dict]:
    """Alias for lint_harper()."""
    return lint_harper(text)


__all__ = ["lint_harper", "harper_suggestions"]
