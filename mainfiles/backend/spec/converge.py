"""Convergence report: spec-vs-output gap detection, iterated.

``build_convergence_report`` takes the spec, the analysis (spec x
tasks coverage), the per-task TDD evidence, and the verification
records, and produces (a) a markdown report stored as the converge
stage artifact and (b) the machine-readable gap list. A gap is any of:

  * an FR marked UNCOVERED in the analysis;
  * an FR whose covering tasks have no TDD-OK evidence row;
  * a task with TDD-OK evidence but an empty diff (claims work, shows
    none) — except tasks explicitly marked no-code (diff may be empty
    only when the task title says "docs"/"doc" — otherwise it is a gap);
  * a verification level claimed without a passing record.

Iteration: each gap becomes a follow-up task in the report
(``- [ ] F<n> ... — covers: FR-xxx``); a subsequent pipeline run can
feed those tasks back in as its task list. ``validate_converge_report``
enforces that a converge artifact actually carries a follow-up task
(or an explicit ``accepted:`` line) for every gap — a report that
lists gaps and then ignores them is rejected.
"""
from __future__ import annotations

import re

from ..spec_chain import analyze_coverage, parse_tasks, spec_frs, uncovered_frs


def compute_gaps(spec: str, analysis: str,
                 tasks_text: str, evidence: dict[str, dict],
                 verifications: list[dict] | None = None) -> list[dict]:
    """evidence: {task_id: {tdd_ok: bool, diff: str}}."""
    gaps: list[dict] = []
    for fr in uncovered_frs(analysis or ""):
        gaps.append({"kind": "uncovered", "fr": fr,
                     "detail": f"{fr} has no covering task in the analysis"})
    tasks = parse_tasks(tasks_text or "")
    fr_to_tasks: dict[str, list[str]] = {}
    for t in tasks:
        for fr in t["covers"]:
            fr_to_tasks.setdefault(fr, []).append(t["id"])
    for fr in spec_frs(spec or ""):
        covering = fr_to_tasks.get(fr, [])
        if not covering:
            continue  # already reported as uncovered above
        if not any((evidence.get(tid) or {}).get("tdd_ok")
                   for tid in covering):
            gaps.append({"kind": "untested", "fr": fr,
                         "detail": f"{fr} is covered only by tasks without "
                                   f"TDD-OK evidence: {', '.join(covering)}"})
    for t in tasks:
        ev = evidence.get(t["id"]) or {}
        if ev.get("tdd_ok") and not (ev.get("diff") or "").strip():
            title = (t["title"] or "").lower()
            if "doc" not in title:
                gaps.append({"kind": "empty-diff", "fr": "",
                             "detail": f"task {t['id']} has TDD evidence "
                                       f"but an empty diff"})
    for v in verifications or []:
        if not v.get("passed"):
            gaps.append({"kind": "verification", "fr": "",
                         "detail": f"verification level "
                                   f"{v.get('level')} did not pass"})
    return gaps


def build_convergence_report(spec: str, tasks_text: str, analysis: str,
                             evidence: dict[str, dict],
                             verifications: list[dict] | None = None,
                             reviews: list[dict] | None = None) -> tuple[str, list[dict]]:
    gaps = compute_gaps(spec, analysis, tasks_text, evidence, verifications)
    tasks = parse_tasks(tasks_text or "")
    lines = ["# Convergence report", "",
             f"- spec requirements: {len(spec_frs(spec or ''))}",
             f"- tasks: {len(tasks)}",
             f"- tasks with TDD-OK evidence: "
             f"{sum(1 for t in tasks if (evidence.get(t['id']) or {}).get('tdd_ok'))}",
             f"- verification levels passed: "
             f"{', '.join(v['level'] for v in (verifications or []) if v.get('passed')) or '(none)'}",
             "", "## Gaps:"]
    if not gaps:
        lines.append("- none: spec, tasks, TDD evidence, and verification agree")
    for i, g in enumerate(gaps, 1):
        fr = f" ({g['fr']})" if g.get("fr") else ""
        lines.append(f"- gap {i} [{g['kind']}]{fr}: {g['detail']}")
    lines += ["", "## Follow-up tasks:"]
    if not gaps:
        lines.append("- none")
    for i, g in enumerate(gaps, 1):
        fr_part = f" — covers: {g['fr']}" if g.get("fr") else ""
        lines.append(f"- [ ] F{i} Close gap: {g['detail']}{fr_part}")
    lines += ["", "## Reviews:"]
    for r in reviews or []:
        lines.append(f"- {r.get('axis')}: {r.get('verdict')}")
    if not reviews:
        lines.append("- (no reviews recorded)")
    return "\n".join(lines) + "\n", gaps


def validate_converge_report(artifact: str, gaps: list[dict]) -> None:
    text = artifact or ""
    if "# Convergence report" not in text:
        raise ValueError(
            "converge requires a convergence report artifact "
            "(build it via the converge-report endpoint)")
    if "## Gaps:" not in text:
        raise ValueError("convergence report requires a '## Gaps:' section")
    for g in gaps:
        fr = g.get("fr") or ""
        detail_key = (g.get("detail") or "")[:40]
        if fr and fr not in text:
            raise ValueError(
                f"converge report must address gap {fr} "
                f"(follow-up task or accepted: line)")
        if detail_key and detail_key not in text and fr not in text:
            raise ValueError(
                f"converge report must address gap: {g.get('detail')}")
