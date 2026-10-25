"""
skills/creator.py — skill-creator eval loop (deep-read Wave 2,
anthropics skill-creator adapted to Sangam's code gates).

Loop: write -> test prompts -> run agent-with-skill -> evaluate ->
rewrite -> repeat, BEFORE publishing. This module is the API-level
function the parent wires to a Library action / routes; it defines no
routes itself.

* ``draft_skill(dir, ...)`` writes a SKILL.md in the authoring-contract
  format (closed frontmatter, 500-line cap enforced).
* ``evaluate_skill(skill_dir, test_prompts, agent_runner, rewriter)``
  runs one round: authoring checks + each test prompt through
  ``agent_runner(prompt, skill_dir) -> str``. A test case passes when
  every ``expected_substrings`` (case-insensitive) appears in the
  runner output. When a round fails and a ``rewriter(report)`` callable
  is supplied, it is called to revise the skill and the loop repeats
  (up to ``max_rounds``). With no rewriter, failures are REPORTED, not
  silently rewritten — the author rewrites, then re-runs.
* ``publish_skill(skill_dir, eval_report)`` refuses unless the latest
  eval round passed fully AND the authoring checks pass; then it
  installs via verify.install_skill. No eval pass, no publish.

No model call happens here: ``agent_runner`` is injected (the caller
wires the real agent-with-skill run; tests inject a stub). A loop run
without a runner cannot claim a pass — it reports ``runner_missing``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import yaml

from .verify import (
    ALLOWED_FRONTMATTER_KEYS,
    MAX_SKILL_MD_LINES,
    install_skill,
    run_skill_checks,
)

AgentRunner = Callable[[str, Path], str]
Rewriter = Callable[[dict], None]


def draft_skill(skill_dir: Path, name: str, description: str, body: str,
                category: str = "misc", invocation: str = "both",
                model_invocation: bool = True, tags: list[str] | None = None,
                triggers: list[str] | None = None) -> Path:
    """Write a contract-format SKILL.md into skill_dir (created if needed).

    Raises ValueError on unknown frontmatter (closed contract) or a
    SKILL.md over the 500-line cap.
    """
    frontmatter: dict = {
        "id": Path(skill_dir).name,
        "name": name,
        "description": description,
        "category": category,
        "invocation": invocation,
        "model_invocation": model_invocation,
    }
    if tags:
        frontmatter["tags"] = tags
    if triggers:
        frontmatter["triggers"] = triggers
    unknown = sorted(set(frontmatter) - ALLOWED_FRONTMATTER_KEYS)
    if unknown:
        raise ValueError(f"Unknown frontmatter keys: {unknown}")
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n" + body.strip() + "\n"
    if len(text.splitlines()) > MAX_SKILL_MD_LINES:
        raise ValueError(f"SKILL.md would be {len(text.splitlines())} lines "
                         f"(max {MAX_SKILL_MD_LINES}); move depth to references/")
    skill_dir = Path(skill_dir)
    skill_dir.mkdir(parents=True, exist_ok=True)
    md = skill_dir / "SKILL.md"
    md.write_text(text, encoding="utf-8")
    return md


def _evaluate_case(case: dict, output: str) -> dict:
    expected = [str(s) for s in (case.get("expected_substrings") or [])]
    lowered = (output or "").lower()
    missing = [s for s in expected if s.lower() not in lowered]
    return {"prompt": case.get("prompt", ""),
            "passed": not missing, "missing": missing,
            "output_excerpt": (output or "")[:300]}


def evaluate_skill(skill_dir: Path, test_prompts: list[dict],
                   agent_runner: AgentRunner | None = None,
                   rewriter: Rewriter | None = None,
                   max_rounds: int = 3) -> dict:
    """Run the write -> test -> evaluate -> rewrite loop.

    test_prompts: [{prompt, expected_substrings: [...]}]. At least one
    prompt is required; an empty list is a caller error, not a pass.
    """
    skill_dir = Path(skill_dir)
    if not test_prompts:
        raise ValueError("Skill-creator eval needs at least one test prompt")
    if max_rounds < 1:
        raise ValueError("max_rounds must be >= 1")
    rounds: list[dict] = []
    for round_no in range(1, max_rounds + 1):
        checks = run_skill_checks(skill_dir)
        if agent_runner is None:
            rounds.append({"round": round_no, "checks": checks,
                           "cases": [], "passed": False,
                           "note": "runner_missing: no agent runner supplied, "
                                   "so no eval pass can be claimed"})
            break
        cases = []
        for case in test_prompts:
            try:
                output = agent_runner(str(case.get("prompt", "")), skill_dir)
            except Exception as exc:  # noqa: BLE001 — a failing run is a failing case
                output = ""
                cases.append({**_evaluate_case(case, output),
                              "error": str(exc)})
                continue
            cases.append(_evaluate_case(case, output))
        passed = checks["failed"] == 0 and all(c["passed"] for c in cases)
        rounds.append({"round": round_no, "checks": checks, "cases": cases,
                       "passed": passed})
        if passed:
            break
        if rewriter is not None and round_no < max_rounds:
            rewriter(rounds[-1])
        else:
            break
    final = rounds[-1]
    return {"skill": skill_dir.name, "rounds": rounds,
            "passed": bool(final["passed"]),
            "rounds_run": len(rounds),
            "publishable": bool(final["passed"])}


def trigger_eval(skill_dir: Path, positive_prompts: list[str],
                 negative_prompts: list[str]) -> dict:
    """Trigger-accuracy eval (anthropics §13 gap: evals tested output
    quality, not trigger precision).

    Uses the registry's deterministic ``match_skills`` scorer against
    the skill file itself: the skill should fire on positive prompts
    (tasks it is for) and NOT fire on negative prompts (tasks it is
    not for). Returns {fired_on_positive, fired_on_negative, precision
    notes, passed} — passed means every positive fired and no negative
    fired. Scores are deterministic, not model judgements.
    """
    from ..code_agent import match_skills
    from .registry import SkillRegistry
    skill_dir = Path(skill_dir)
    registry = SkillRegistry(skills_root=skill_dir.parent)
    skill = next((s for s in registry.skills.values()
                  if s.source_dir is not None
                  and Path(s.source_dir).resolve() == skill_dir.resolve()),
                 None) or registry.get(skill_dir.name)
    if skill is None:
        raise ValueError(f"skill {skill_dir.name!r} does not parse in its parent dir")
    fired_pos, fired_neg = [], []
    for prompt in positive_prompts or []:
        if any(s.id == skill.id for s in match_skills(prompt, [skill])):
            fired_pos.append(prompt)
    for prompt in negative_prompts or []:
        if any(s.id == skill.id for s in match_skills(prompt, [skill])):
            fired_neg.append(prompt)
    passed = (len(fired_pos) == len(positive_prompts or [])
              and not fired_neg)
    return {"skill": skill_dir.name,
            "positive_total": len(positive_prompts or []),
            "positive_fired": len(fired_pos),
            "negative_total": len(negative_prompts or []),
            "negative_fired": len(fired_neg),
            "negative_fired_prompts": fired_neg,
            "passed": passed}


def evaluate_blind(skill_dir: Path, cases: list[dict],
                   runner_with: AgentRunner | None = None,
                   runner_without: AgentRunner | None = None) -> dict:
    """Blind A/B publish gate (taste-skill evals + superpowers §12).

    Each case runs against a fresh agent WITH the skill and a fresh
    agent WITHOUT it; a case counts for a side when every
    ``expected_substrings`` appears in that side's output. The gate
    PASSES only when with-skill beats without-skill strictly
    (``with_passed > without_passed``) — a skill that adds nothing
    must not publish. The judge here is the deterministic substring
    rubric, recorded per case with FAIL counts, not a blind human
    judge; the "blind" property is that neither side's output is
    labelled during scoring (both are scored by the same rubric).
    With no runners supplied, no pass can be claimed (runner_missing).
    """
    skill_dir = Path(skill_dir)
    if not cases:
        raise ValueError("blind eval needs at least one case")
    if runner_with is None or runner_without is None:
        return {"skill": skill_dir.name, "cases": [], "with_passed": 0,
                "without_passed": 0, "passed": False,
                "note": "runner_missing: both runners required, no pass claimed"}
    scored = []
    with_passed = without_passed = 0
    for case in cases:
        try:
            out_with = runner_with(str(case.get("prompt", "")), skill_dir)
        except Exception as exc:  # noqa: BLE001 — a failing run is a failing case
            out_with, with_err = "", str(exc)
        else:
            with_err = ""
        try:
            out_without = runner_without(str(case.get("prompt", "")), skill_dir)
        except Exception as exc:  # noqa: BLE001
            out_without, without_err = "", str(exc)
        else:
            without_err = ""
        row_with = _evaluate_case(case, out_with)
        row_without = _evaluate_case(case, out_without)
        with_passed += int(row_with["passed"])
        without_passed += int(row_without["passed"])
        scored.append({"prompt": case.get("prompt", ""),
                       "with_passed": row_with["passed"],
                       "without_passed": row_without["passed"],
                       "with_missing": row_with["missing"],
                       "without_missing": row_without["missing"],
                       "with_error": with_err, "without_error": without_err})
    return {"skill": skill_dir.name, "cases": scored,
            "with_passed": with_passed, "without_passed": without_passed,
            "total": len(cases),
            "passed": with_passed > without_passed,
            "fail_counts": {"with": len(cases) - with_passed,
                            "without": len(cases) - without_passed}}


def publish_skill(skill_dir: Path, eval_report: dict,
                  version: str = "1.0.0",
                  require_failing_baseline: bool = False,
                  baseline_report: dict | None = None) -> dict:
    """Publish a skill after its eval loop passes.

    Refuses (ValueError) when the report is not publishable or the
    authoring checks currently fail — re-checking at publish time, so a
    report from an older, edited skill cannot sneak through.

    Batch 10 (superpowers "watch it fail first"): with
    ``require_failing_baseline=True``, publish additionally refuses
    unless ``baseline_report`` shows the agent WITHOUT the skill failed
    at least one case (``baseline_passed < baseline_total``) — a skill
    must prove it fixes a real failure, not merely pass alongside a
    baseline that already passed.
    """
    skill_dir = Path(skill_dir)
    if require_failing_baseline:
        if baseline_report is None:
            raise ValueError("Cannot publish: failing-baseline gate requires "
                             "a baseline_report (agent-without-skill run)")
        total = baseline_report.get("total")
        passed_n = baseline_report.get("without_passed",
                                       baseline_report.get("passed"))
        if total is None or passed_n is None:
            raise ValueError("Cannot publish: baseline_report lacks total/passed counts")
        if int(passed_n) >= int(total):
            raise ValueError("Cannot publish: baseline (without skill) already "
                             "passes every case — the skill proves no improvement")
    if not eval_report.get("publishable"):
        raise ValueError("Cannot publish: the skill-creator eval loop has "
                         "not passed for this skill")
    checks = run_skill_checks(skill_dir)
    if checks["failed"] != 0:
        raise ValueError(f"Cannot publish: authoring checks fail: {checks}")
    result = install_skill(skill_dir, version=version)
    return {**result, "eval_rounds": eval_report.get("rounds_run", 0)}
