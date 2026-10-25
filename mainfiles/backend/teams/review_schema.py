"""teams/review_schema.py — shared severity-tier review contract (Batch 10).

agency-agents' portable contract: every reviewer (human, persona, or
pipeline stage) reports findings on one severity scale so findings are
comparable across reviewers instead of each inventing its own words:

* blocker (🔴) — must fix before merge; the run cannot finish with an
  open blocker unacknowledged.
* suggestion (🟡) — should fix; may ship with a recorded reason.
* nit (💭) — polish; never blocks.

:func:`parse_review_checklist` extracts tiered findings from review
text (emoji or ``blocker:``/``suggestion:``/``nit:`` prefixes).
:func:`review_report` summarises counts and the blocking verdict.
Sangam's existing reviewer persona already writes Must/Should/Nice;
this module is the machine-readable side of that same contract, and
both vocabularies map here (must->blocker, should->suggestion,
nice->nit) so old reviews still parse.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

SEVERITIES = ("blocker", "suggestion", "nit")

_EMOJI = {"🔴": "blocker", "🟡": "suggestion", "💭": "nit"}
_WORD = {"blocker": "blocker", "must": "blocker",
         "suggestion": "suggestion", "should": "suggestion",
         "nit": "nit", "nice": "nit"}


@dataclass
class ReviewFinding:
    severity: str
    text: str

    def to_dict(self) -> dict:
        return {"severity": self.severity, "text": self.text}


def parse_review_checklist(text: str) -> list[ReviewFinding]:
    """Extract severity-tiered findings from review text.

    A line counts when it starts (after list markers) with an emoji
    tier or a ``<word>:`` tier prefix. Untiered lines are ignored —
    they are prose, not findings, and must not inflate counts.
    """
    findings: list[ReviewFinding] = []
    for raw in (text or "").splitlines():
        line = raw.strip().lstrip("-*•[] ").strip()
        if not line:
            continue
        severity = None
        rest = line
        for emoji, sev in _EMOJI.items():
            if line.startswith(emoji):
                severity, rest = sev, line[len(emoji):].strip(" :")
                break
        if severity is None:
            match = re.match(r"(?i)(blocker|must|suggestion|should|nit|nice)\s*:\s*(.+)", line)
            if match:
                severity = _WORD[match.group(1).lower()]
                rest = match.group(2).strip()
        if severity and rest:
            findings.append(ReviewFinding(severity=severity, text=rest))
    return findings


def review_report(findings: list[ReviewFinding]) -> dict:
    """Summarise findings; blockers decide the verdict."""
    counts = {sev: 0 for sev in SEVERITIES}
    for finding in findings or []:
        if finding.severity in counts:
            counts[finding.severity] += 1
    blockers = counts["blocker"]
    return {"counts": counts,
            "total": sum(counts.values()),
            "verdict": ("blocked" if blockers else "pass"),
            "detail": (f"{blockers} blocker(s) must be fixed before merge"
                       if blockers else "No blockers; suggestions and nits "
                       "may ship with a recorded reason."),
            "findings": [f.to_dict() for f in (findings or [])]}
