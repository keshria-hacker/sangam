"""
response_quality/structure.py — detect-only structural slop patterns
(petergyang/no-ai-slop, structural half).

Sangam's word/phrase catalogue (slop.py) catches "delve" and
"tapestry" but none of the structural patterns no-ai-slop names:
binary contrasts, colon reveals, faux-insight setups, importance
puffery, weasel attribution, recap/kicker endings, formatting slop,
em-dash clusters, robotic rhythm. This module adds those as
DETECT-ONLY candidates: each hit names the pattern, quotes the line,
and suggests a few-word fix. It never rewrites — rewriting voice is
the edit mode's job, and structural "fixes" are judgment calls a
human (or the edit mode with the text in front of them) must make.

A hit is {pattern, line (1-based), quote, fix}. A pattern matching
twice on one line is reported once per line, like detect_slop.
"""
from __future__ import annotations

import re

# (pattern name, regex, few-word fix). Applied per line unless noted.
_LINE_PATTERNS: list[tuple[str, str, str]] = [
    ("binary-contrast",
     r"\bnot\s+[^,.;:]{1,60}?\s*,\s*it['’]s\s+",
     "Say what it is directly; drop the 'not X, it's Y' frame."),
    ("binary-contrast",
     r"\bnot\s+[^,.;:]{1,60}?\s+but\s+",
     "Say what it is directly; drop the 'not X but Y' frame."),
    ("colon-reveal",
     r"\b(here['’]s the (thing|truth|catch|secret)|the truth is|the reality is|"
     r"the bottom line is)\s*:",
     "State the point without the drum-roll setup."),
    ("faux-insight",
     r"\b(what if i told you|here['’]s what nobody tells you|"
     r"the real question is|what nobody understands is)\b",
     "State the insight; drop the setup."),
    ("importance-puffery",
     r"\b(more important than ever|cannot be overstated|of paramount importance|"
     r"it is (absolutely )?essential to understand|in today['’]s (fast-paced )?world)\b",
     "Cut the puffery; let the fact carry the weight."),
    ("weasel-attribution",
     r"\b(experts say|studies show|many believe|it is widely believed|"
     r"sources say|researchers agree|people say)\b",
     "Name the source or drop the claim."),
    ("formatting-slop-emoji-heading",
     r"^\s*#{1,6}\s+[\U0001F300-\U0001FAFF\u2600-\u27BF]",
     "Headings do not need emoji decoration."),
    ("formatting-slop-bold-heading",
     r"^\s*#{1,6}\s+\*\*[^*]+\*\*\s*$",
     "A heading is already bold; drop the asterisks."),
]

_ENDING_PATTERNS: list[tuple[str, str, str]] = [
    ("recap-ending",
     r"^\s*(in summary|to sum up|in conclusion|to conclude|ultimately,?|"
     r"all in all|at the end of the day)\b",
     "End on the point, not a recap of it."),
    ("kicker-ending",
     r"^\s*(and )?(that|this) changes everything\.?\s*$",
     "End on a concrete fact, not a dramatic kicker."),
    ("kicker-ending",
     r"^\s*the future (is|starts) (here|now)\.?\s*$",
     "End on a concrete fact, not a dramatic kicker."),
]

_EM_DASH = "\u2014"


def _lines(text: str) -> list[str]:
    return (text or "").splitlines() or [""]


def detect_structure(text: str) -> list[dict]:
    """Detect structural slop patterns. Detect-only: never rewrites."""
    if not text or not text.strip():
        return []
    lines = _lines(text)
    found: list[dict] = []
    seen: set[tuple[str, int]] = set()

    def _add(name: str, line_no: int, quote: str, fix: str) -> None:
        key = (name, line_no)
        if key in seen:
            return
        seen.add(key)
        found.append({"pattern": name, "line": line_no,
                      "quote": quote.strip(), "fix": fix})

    for name, pattern, fix in _LINE_PATTERNS:
        rx = re.compile(pattern, re.IGNORECASE)
        for i, line in enumerate(lines, start=1):
            if rx.search(line):
                _add(name, i, line, fix)
    # Em-dash clusters: 3+ em dashes on one line.
    for i, line in enumerate(lines, start=1):
        if line.count(_EM_DASH) >= 3:
            _add("em-dash-cluster", i, line,
                 "Use commas or periods; save em dashes for rare emphasis.")
    # Robotic rhythm: 3+ consecutive sentences starting with the same word.
    for para in text.split("\n\n"):
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", para.strip()) if s.strip()]
        starts = [re.match(r"[A-Za-z]+", s).group(0).lower() if re.match(r"[A-Za-z]+", s) else ""
                  for s in sentences]
        run = 1
        for j in range(1, len(starts)):
            if starts[j] and starts[j] == starts[j - 1]:
                run += 1
                if run >= 3:
                    line_no = text[:text.find(para)].count("\n") + 1 if para in text else 1
                    _add("robotic-rhythm", line_no, sentences[j],
                         "Vary sentence openings; do not start every sentence the same way.")
                    break
            else:
                run = 1
    # Endings apply to the last non-empty paragraph / line.
    non_empty = [l for l in lines if l.strip()]
    if non_empty:
        last_para_lines = text.rstrip().split("\n\n")[-1].splitlines()
        last_line = last_para_lines[-1] if last_para_lines else non_empty[-1]
        last_no = len(lines) - (len(lines) - len(non_empty))  # approx: last non-empty line
        # Compute the true line number of the last non-empty line.
        last_no = max(i for i, l in enumerate(lines, start=1) if l.strip())
        for name, pattern, fix in _ENDING_PATTERNS:
            if re.search(pattern, last_line, re.IGNORECASE):
                _add(name, last_no, last_line, fix)
    found.sort(key=lambda d: (d["line"], d["pattern"]))
    return found


# ------------------------------------------------------------- readability
def readability_report(text: str) -> dict:
    """Rough, honestly-labelled readability figures — estimates from
    word/sentence counts only, never a claimed grade or score.

    Returns words, sentences, avg_sentence_words, long_sentences
    (>25 words), avg_paragraph_words, and a plain-language note."""
    if not text or not text.strip():
        return {"words": 0, "sentences": 0, "avg_sentence_words": 0.0,
                "long_sentences": 0, "avg_paragraph_words": 0.0,
                "note": "Empty text: nothing to measure."}
    words = re.findall(r"[A-Za-z0-9']+", text)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    paras = [p for p in text.split("\n\n") if p.strip()]
    sent_word_counts = [len(re.findall(r"[A-Za-z0-9']+", s)) for s in sentences]
    avg_sent = (sum(sent_word_counts) / len(sent_word_counts)) if sent_word_counts else 0.0
    long_sents = sum(1 for c in sent_word_counts if c > 25)
    avg_para = (len(words) / len(paras)) if paras else 0.0
    if avg_sent <= 15 and long_sents == 0:
        note = "Short sentences throughout — easy to scan."
    elif avg_sent <= 20:
        note = "Mostly short sentences; a few long ones to check."
    else:
        note = "Long sentences dominate — consider splitting the longest ones."
    return {"words": len(words), "sentences": len(sentences),
            "avg_sentence_words": round(avg_sent, 1),
            "long_sentences": long_sents,
            "avg_paragraph_words": round(avg_para, 1),
            "note": note}
