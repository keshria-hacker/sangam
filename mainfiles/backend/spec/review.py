"""PR-style review artifact: diff + review verdicts, as markdown.

The review stage's output is a single document a human can read like
a pull-request review: changed files parsed from the unified diff,
per-axis verdicts (spec / quality) with their review-package id, and
an overall verdict (PASS only when every axis passes). This is the
output of the review stage — not a side-channel chat message.
"""
from __future__ import annotations

import re

_DIFF_FILE_RE = re.compile(r"^--- a/(.+)$", re.MULTILINE)


def diff_files(diff: str) -> list[str]:
    return sorted(set(_DIFF_FILE_RE.findall(diff or "")))


def render_pr_review(pipeline_title: str, diff: str,
                     reviews: list[dict]) -> str:
    """reviews: [{axis, verdict, review_package_id, artifact}]."""
    files = diff_files(diff)
    lines = [f"# PR review: {pipeline_title}", "",
             "## Changed files"]
    lines += [f"- {f}" for f in files] if files else ["- _(no files in diff)_"]
    lines += ["", "## Verdicts"]
    overall = "PASS"
    for r in reviews:
        verdict = (r.get("verdict") or "").lower()
        if verdict != "pass":
            overall = "FAIL"
        lines += [f"### {r.get('axis', '?')} — {verdict.upper()}",
                  f"- review package: {r.get('review_package_id', '')}",
                  (r.get("artifact") or "").strip() or "_(no review notes)_", ""]
    if not reviews:
        overall = "PENDING"
    lines += [f"## Overall: {overall}", "",
              "## Diff", "```diff", (diff or "").strip() or "_(empty)_",
              "```", ""]
    return "\n".join(lines)
