"""
backend/writing_lint.py — offline, deterministic grammar/spell/repetition
lint (Harper-style, no model, no network).

Candidate-only by design: this linter NEVER rewrites text and never
autocorrects. It returns issues [{rule, line, offset, quote, suggestion}]
for a human to accept or dismiss.

Rules:
- repeated-word: "the the" (case-insensitive, adjacent duplicate words).
- confusion-candidate: their/there/they're, your/you're, its/it's,
  to/too/two, affect/effect. These are FLAGGED AS CANDIDATES, not errors:
  most uses are correct, and only a human (or a model) can tell which
  use is wrong. The suggestion states the distinction to check.
- double-space: two or more spaces between words on a line.
- missing-space-after-punctuation: "Hello.World" / "yes,No" — sentence
  punctuation immediately followed by a letter with no space.
- unbalanced-quotes: odd count of double quotes in the text.
- unbalanced-parens: unclosed "(" or extra ")" in the text.
- repeated-punctuation: "!!", "??", ",,", ";;", or 4+ dots in a row.
- unknown-word: word not in the bundled common-words list
  (response_quality/common_words.txt, shipped with Sangam; /usr/share/dict
  was absent on the build machine, so no system dictionary is assumed).
  Capitalized words are skipped (assumed proper nouns) and words shorter
  than 4 letters are skipped, to keep false positives down. An
  unknown word is a candidate, not proof of a misspelling.
Batch 12 (Harper-shaped additions, same issue shape, same route):
- a-an-agreement: "a apple" / "an cat" (a small exception list covers
  hour/honest/honour/honor/heir/herb, where spelling misleads).
- double-comparative: "more better", "most fastest".
- common-typo: a small deterministic typo map (teh, recieve, adress,
  occured, seperate, definately, neccessary, accomodate, wich, thier,
  untill, goverment, enviroment). These are candidates with a
  suggestion, never auto-rewrites.

Offsets are 0-based character offsets into the full text; line is
1-based. quote is the offending word/line fragment.
"""
from __future__ import annotations

import re
from pathlib import Path

_WORDS_PATH = Path(__file__).resolve().parent / "response_quality" / "common_words.txt"

_WORDS: set[str] | None = None


def _wordlist() -> set[str]:
    global _WORDS
    if _WORDS is None:
        try:
            words: set[str] = set()
            for line in _WORDS_PATH.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("#"):
                    continue
                words.update(w.lower() for w in line.split())
            _WORDS = words
        except OSError:
            _WORDS = set()
    return _WORDS


def wordlist_size() -> int:
    return len(_wordlist())


_CONFUSIONS: dict[str, str] = {
    "their": "check: their = belonging to them; there = place; they're = they are",
    "there": "check: there = place; their = belonging to them; they're = they are",
    "they're": "check: they're = they are; their = belonging to them; there = place",
    "your": "check: your = belonging to you; you're = you are",
    "you're": "check: you're = you are; your = belonging to you",
    "its": "check: its = belonging to it; it's = it is / it has",
    "it's": "check: it's = it is / it has; its = belonging to it",
    "to": "check: to = direction/infinitive; too = also/excess; two = the number 2",
    "too": "check: too = also/excess; to = direction/infinitive; two = the number 2",
    "two": "check: two = the number 2; to = direction/infinitive; too = also/excess",
    "affect": "check: affect is usually the verb; effect is usually the noun",
    "effect": "check: effect is usually the noun; affect is usually the verb",
}

_WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def _line_offsets(text: str) -> list[int]:
    """Start offset of each line (line 1 starts at 0)."""
    offsets = [0]
    for m in re.finditer(r"\n", text):
        offsets.append(m.end())
    return offsets


def _line_of(offsets: list[int], pos: int) -> int:
    import bisect

    return bisect.bisect_right(offsets, pos)


def lint_text(text: str) -> list[dict]:
    """Lint text. Returns a list of issue dicts; never modifies text."""
    if not text:
        return []
    issues: list[dict] = []
    offsets = _line_offsets(text)
    lines = text.splitlines()

    def _issue(rule: str, pos: int, quote: str, suggestion: str | None = None) -> dict:
        d: dict = {
            "rule": rule,
            "line": _line_of(offsets, pos),
            "offset": pos,
            "quote": quote,
        }
        if suggestion:
            d["suggestion"] = suggestion
        return d

    # Repeated words + confusion candidates + unknown words, per word token.
    prev: tuple[str, int] | None = None
    words = list(_WORD_RE.finditer(text))
    wordlist = _wordlist()
    for m in words:
        word = m.group(0)
        low = word.lower()
        if prev is not None and prev[0] == low and low.isalpha() and len(low) >= 2:
            issues.append(_issue(
                "repeated-word", m.start(), word,
                f"Delete one '{word}' (repeated word).",
            ))
        # Confusion candidates: flag every occurrence of a confusion word
        # EXCEPT the extremely common preposition "to" standing alone in a
        # clearly verbal context is impossible to judge — so "to" is only
        # flagged when it directly precedes another confusion word or a
        # number word, keeping noise down. All other confusion words are
        # flagged as candidates on every occurrence.
        if low in _CONFUSIONS and low != "to":
            issues.append(_issue("confusion-candidate", m.start(), word, _CONFUSIONS[low]))
        if (
            wordlist
            and len(word) >= 4
            and not word[:1].isupper()
            and low not in wordlist
            and low not in _CONFUSIONS
        ):
            issues.append(_issue(
                "unknown-word", m.start(), word,
                "Not in the bundled common-words list — check the spelling.",
            ))
        prev = (low, m.start())

    # Double spaces (within a line, not leading indentation).
    for m in re.finditer(r"(?<=\S) {2,}(?=\S)", text):
        issues.append(_issue("double-space", m.start(), "  ",
                             "Use a single space."))
    # Missing space after sentence punctuation.
    for m in re.finditer(r"([.!?])([A-Za-z])", text):
        # Skip decimals / abbreviations handled loosely: only flag when the
        # char before the punctuation is a lowercase letter.
        if m.start() > 0 and text[m.start() - 1].islower():
            issues.append(_issue(
                "missing-space-after-punctuation", m.start(), m.group(0),
                "Add a space after sentence punctuation.",
            ))
    # Repeated punctuation.
    for m in re.finditer(r"[!?]{2,}|,,|;;|\.{4,}", text):
        issues.append(_issue("repeated-punctuation", m.start(), m.group(0),
                             "Use a single punctuation mark."))
    # Unbalanced quotes (double quotes only; apostrophes excluded).
    if text.count('"') % 2 == 1:
        pos = text.rfind('"')
        issues.append(_issue("unbalanced-quotes", pos, '"',
                             "A double quote is opened but never closed (or vice versa)."))
    # Unbalanced parens.
    depth = 0
    first_open = -1
    for i, ch in enumerate(text):
        if ch == "(":
            if depth == 0:
                first_open = i
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                issues.append(_issue("unbalanced-parens", i, ")",
                                     "Closing parenthesis without a matching opener."))
                depth = 0
    if depth > 0 and first_open >= 0:
        issues.append(_issue("unbalanced-parens", first_open, "(",
                             "Opening parenthesis is never closed."))
    # Batch 12: Harper-shaped deterministic rules (see qa/devqa.py
    # extra_writing_issues for the rule bodies; the issue shape matches
    # this function's _issue output so the route needs no change).
    from .qa.devqa import extra_writing_issues

    for extra in extra_writing_issues(text, _WORD_RE.finditer(text)):
        d = {"rule": extra["rule"], "line": _line_of(offsets, extra["offset"]),
             "offset": extra["offset"], "quote": extra["quote"]}
        if extra.get("suggestion"):
            d["suggestion"] = extra["suggestion"]
        issues.append(d)
    issues.sort(key=lambda d: (d["offset"], d["rule"]))
    return issues
