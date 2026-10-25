"""
api_routes/quality_routes.py — writing-quality API (Batch 7).

POST /quality/preview — before/after diff (existing shape preserved:
original/cleaned/diff/stats). New `mode` field, default "edit" so
existing callers do not break:
  mode=detect -> detections [{pattern, line, quote}], text UNCHANGED
                 (cleaned == original, diff == ""), no rewrite.
  mode=edit   -> minimum edit + "what_changed" [{pattern, before, after}]
                 alongside the existing fields.
POST /quality/lint — offline deterministic lint (writing_lint.py);
  returns {issues} and never rewrites.
GET /quality/adhd-style — the prompt-level ADHD style block. Honest
  status (deep-memory wiring): wired=true — chat_stream_routes.py
  injects this block into the chat system prompt when the user's
  ``adhdFriendly`` setting is on, and leaves the prompt unchanged
  when it is off. The post-hoc adhdFriendly formatting toggle is
  separate and also works.
"""
import difflib

from fastapi import Depends
from pydantic import BaseModel

from ..auth import get_current_user
from ..response_quality import (
    adhd_style_text,
    apply_quality,
    detect_slop,
    detect_structure,
    natural_rewrite,
    pre_send_check,
    readability_report,
    run_eval,
)
from ..response_quality.adhd import restate_state
from ..response_quality.humanizer import HONEST_NOTE
from ..response_quality.slop import remove_slop_with_changes
from ..writing_lint import lint_text
from .common import router


class QualityIn(BaseModel):
    text: str
    no_slop: bool = True
    adhd_friendly: bool = False
    mode: str = "edit"  # "edit" (default, legacy) or "detect"
    structure: bool = False  # Batch 13: include structural detections + eval


class CheckIn(BaseModel):
    text: str


class HumanizeIn(BaseModel):
    text: str


class ReportIn(BaseModel):
    text: str
    step: int | None = None
    total: int | None = None
    next_action: str | None = None


def _ponytail_findings(text: str) -> tuple[list[dict], dict]:
    """Ponytail report shape for a quality check: ranked findings
    (must-fix first), each with a concrete case + fix + what happens
    if skipped, plus a footer of what was NOT checked and risks.

    Severity mapping (stated, not invented): deterministic lint
    errors (repeated word, double comparative, typo, unbalanced
    punctuation/quotes) are must-fix; structural slop and word slop
    are suggestions (style, not correctness); unknown-word and
    confusion candidates are nits (candidates a human must judge)."""
    findings: list[dict] = []
    for issue in lint_text(text):
        rule = issue["rule"]
        if rule in ("repeated-word", "double-comparative", "common-typo",
                    "unbalanced-quotes", "unbalanced-parens",
                    "repeated-punctuation"):
            severity, skipped = "must-fix", "The error ships to the reader."
        elif rule in ("unknown-word", "confusion-candidate"):
            severity, skipped = "nit", "Nothing breaks; a real error may hide here."
        else:
            severity, skipped = "suggestion", "Readers may stumble; meaning is intact."
        findings.append({"severity": severity, "kind": "lint", "rule": rule,
                         "line": issue["line"], "quote": issue["quote"],
                         "fix": issue.get("suggestion", "Review this line."),
                         "if_skipped": skipped})
    for hit in detect_slop(text):
        findings.append({"severity": "suggestion", "kind": "slop",
                         "rule": hit["pattern"], "line": hit["line"],
                         "quote": hit["quote"],
                         "fix": "Replace with plainer wording (see /quality/preview edit mode).",
                         "if_skipped": "The cliché stays; meaning is intact."})
    for hit in detect_structure(text):
        findings.append({"severity": "suggestion", "kind": "structure",
                         "rule": hit["pattern"], "line": hit["line"],
                         "quote": hit["quote"], "fix": hit["fix"],
                         "if_skipped": "The structural tic stays; meaning is intact."})
    rank = {"must-fix": 0, "suggestion": 1, "nit": 2}
    findings.sort(key=lambda f: (rank[f["severity"]], f["line"], f["rule"]))
    footer = {
        "not_checked": [
            "Factual accuracy — no lint rule can verify a claim.",
            "Tone and voice fit for the intended reader.",
            "Whether a flagged confusion-candidate word is actually wrong.",
        ],
        "risks": [
            "Auto-applying every suggestion can flatten the writer's voice; "
            "review suggestions before accepting them.",
            "Structural detections are heuristics (e.g. a quoted 'experts say' "
            "is a citation, not weasel attribution).",
        ],
    }
    return findings, footer


class LintIn(BaseModel):
    text: str


@router.post("/quality/preview")
async def preview_quality(payload: QualityIn, user=Depends(get_current_user)):
    """Show before/after diff of quality processing (or detect-only)."""
    mode = (payload.mode or "edit").lower()
    if mode == "detect":
        detections = detect_slop(payload.text) if payload.no_slop else []
        return {
            "original": payload.text,
            "cleaned": payload.text,
            "diff": "",
            "stats": {"slop_removed": 0, "adhd_changes": 0, "detections": len(detections)},
            "mode": "detect",
            "detections": detections,
        }
    cleaned, stats = apply_quality(
        payload.text,
        no_slop=payload.no_slop,
        adhd_friendly=payload.adhd_friendly,
    )
    diff = list(difflib.unified_diff(
        payload.text.splitlines(keepends=True),
        cleaned.splitlines(keepends=True),
        fromfile="original", tofile="cleaned",
    ))
    what_changed: list[dict] = []
    if payload.no_slop:
        _slop_cleaned, what_changed = remove_slop_with_changes(payload.text)
    out = {
        "original": payload.text,
        "cleaned": cleaned,
        "diff": "".join(diff),
        "stats": stats,
        "mode": "edit",
        "what_changed": what_changed,
    }
    if payload.structure:
        out["structure"] = detect_structure(payload.text)
        out["eval"] = run_eval(payload.text, cleaned, what_changed)
    return out


@router.post("/quality/check")
async def check_quality(payload: CheckIn, user=Depends(get_current_user)):
    """Ponytail-shaped quality check: ranked findings (must-fix
    first, each with a concrete case + fix + if-skipped) plus a
    footer of what was not checked and known risks. Detect-only:
    the text is never rewritten here."""
    findings, footer = _ponytail_findings(payload.text)
    return {"text": payload.text, "findings": findings,
            "counts": {sev: sum(1 for f in findings if f["severity"] == sev)
                       for sev in ("must-fix", "suggestion", "nit")},
            "footer": footer}


@router.post("/quality/humanize")
async def humanize_quality(payload: HumanizeIn, user=Depends(get_current_user)):
    """Natural rewrite for readability (NOT detector evasion — see
    response_quality/humanizer.py). Returns the rewritten text, the
    change list, and the honest boundary note. The original message
    is never replaced automatically; the caller shows both."""
    rewritten, changes = natural_rewrite(payload.text)
    return {"original": payload.text, "rewritten": rewritten,
            "changes": changes, "note": HONEST_NOTE}


@router.post("/quality/report")
async def report_quality(payload: ReportIn, user=Depends(get_current_user)):
    """Per-message quality report for Chat/Inspector: readability
    figures, slop hits, structural hits, lint count, ADHD pre-send
    check, and optional per-turn state restatement. Plain language
    throughout; figures are labelled estimates where they are."""
    findings, _footer = _ponytail_findings(payload.text)
    report: dict = {
        "readability": readability_report(payload.text),
        "slop": detect_slop(payload.text),
        "structure": detect_structure(payload.text),
        "lint_issue_count": sum(1 for f in findings if f["kind"] == "lint"),
        "adhd_pre_send_check": pre_send_check(payload.text),
        "summary": (
            f"{len(detect_slop(payload.text))} slop hit(s), "
            f"{len(detect_structure(payload.text))} structural hit(s), "
            f"{sum(1 for f in findings if f['kind'] == 'lint')} lint issue(s). "
            "Open /quality/check for the ranked findings with fixes."),
    }
    if payload.step is not None and payload.total is not None:
        report["state_restatement"] = restate_state(
            payload.step, payload.total, payload.next_action or "")
    return report


@router.post("/quality/lint")
async def lint_quality(payload: LintIn, user=Depends(get_current_user)):
    """Offline grammar/spell/repetition lint. Candidate issues only."""
    return {"issues": lint_text(payload.text)}


@router.get("/quality/adhd-style")
async def get_adhd_style(user=Depends(get_current_user)):
    """Prompt-level ADHD style block + honest wiring status."""
    return {
        "style": adhd_style_text(),
        "wired_into_chat": True,
        "wired_behind_setting": "adhdFriendly",
        "note": (
            "Wired into chat: chat_stream_routes.py prepends this style "
            "block to the chat system prompt when the user's adhdFriendly "
            "setting is on; when off, the prompt path is unchanged. The "
            "post-hoc adhdFriendly toggle (opener-strip + reflow + list "
            "cap) is separate and also works."
        ),
    }
