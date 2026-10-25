"""
response_quality/eval.py — no-ai-slop eval.md checklist, as code.

After every edit, no-ai-slop's eval.md asks the editor to self-check
the result instead of trusting the edit. This module runs that
checklist deterministically over (original, cleaned, changes):

- numbers_preserved: every number in the original still appears in
  the cleaned text (an edit must never smooth "37%" into "much better").
- no_new_sentences: the edit adds no sentences (edit = cut/replace,
  never invent).
- length_change_bounded: word count moves by at most 10% either way
  (replacements like "game-changer" -> "major improvement" lengthen
  slightly; a large swing means the edit rewrote, not trimmed).
- what_changed_matches: changes are listed exactly when text changed.
- no_leading_opener_left: no throat-clearing opener survives at the
  start of the cleaned text.
- no_slop_words_left: none of slop.py's catalogue words survive
  (checked against the same pattern list, so the two cannot drift).

Each check is {check, passed, note}. ``run_eval`` never rewrites.
"""
from __future__ import annotations

import re

from .slop import _PATTERNS

_LEADING_OPENERS = re.compile(
    r"^(great question!|i['’]d be happy to help!?|certainly!|of course!|"
    r"absolutely!|happy to help!?)\s+",
    re.IGNORECASE,
)


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?%?", text or ""))


def _sentences(text: str) -> int:
    return len([s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s.strip()])


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text or ""))


def run_eval(original: str, cleaned: str, changes: list[dict]) -> dict:
    """Run the eval checklist. Returns {checks, passed, total, ok}."""
    original = original or ""
    cleaned = cleaned or ""
    checks: list[dict] = []

    def _check(name: str, passed: bool, note: str) -> None:
        checks.append({"check": name, "passed": bool(passed), "note": note})

    missing_numbers = sorted(_numbers(original) - _numbers(cleaned))
    _check("numbers_preserved", not missing_numbers,
           "All numbers survive the edit." if not missing_numbers
           else f"Numbers lost in edit: {', '.join(missing_numbers)}.")
    _check("no_new_sentences", _sentences(cleaned) <= _sentences(original),
           "Edit adds no sentences." if _sentences(cleaned) <= _sentences(original)
           else "Edit added sentences — an edit should cut, not invent.")
    ow, cw = _words(original), _words(cleaned)
    swing = (abs(cw - ow) / ow) if ow else (0 if cw == 0 else 1)
    _check("length_change_bounded", swing <= 0.10,
           f"Word count {ow} -> {cw} (within 10%)." if swing <= 0.10
           else f"Word count {ow} -> {cw}: edit rewrote more than it trimmed.")
    changed = cleaned != original
    _check("what_changed_matches", bool(changes) == changed,
           "Change list matches whether text changed."
           if bool(changes) == changed else
           "Change list does not match the edit (listed changes but no diff, or diff with no list).")
    _check("no_leading_opener_left", not _LEADING_OPENERS.search(cleaned.lstrip()),
           "No throat-clearing opener survives at the start.")
    leftovers = sorted({name for name, pat, _ in _PATTERNS
                        if re.search(pat, cleaned, re.IGNORECASE)})
    _check("no_slop_words_left", not leftovers,
           "No catalogue slop words survive." if not leftovers
           else f"Slop words still present: {', '.join(leftovers)}.")
    passed = sum(1 for c in checks if c["passed"])
    return {"checks": checks, "passed": passed, "total": len(checks),
            "ok": passed == len(checks)}
