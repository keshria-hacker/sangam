"""Spec pipeline v2 state machine (pure, DB-free validation).

Stage order (full spec-kit order, including the two stages the old
chain lacked)::

    constitution -> spec -> clarify -> plan -> checklist -> tasks
    -> analyze -> implement -> verify -> converge

``validate_stage`` enforces, per stage, both ordering (via
``next_stage``) and the stage's structural gate. Context carries the
already-stored artifacts plus ledger state; the route layer builds it
from the DB rows. ``clarify`` writes clarifications back into the
stored spec (same rule as the old chain); the route applies that
write-back before storing the clarify artifact.
"""
from __future__ import annotations

import re

from ..spec_chain import (
    apply_clarifications,
    spec_markers,
    validate_analysis,
    validate_plan,
    validate_spec,
    validate_tasks,
)
from .checklist import validate_checklist
from .converge import validate_converge_report

STAGES = ["constitution", "spec", "clarify", "plan", "checklist",
          "tasks", "analyze", "implement", "verify", "converge"]


def next_stage(current: str | None) -> str | None:
    """Next stage, or None when the pipeline is complete (converge is
    terminal for v2 — there is no separate finish stage)."""
    if not current:
        return STAGES[0]
    if current not in STAGES:
        return None
    idx = STAGES.index(current)
    return STAGES[idx + 1] if idx + 1 < len(STAGES) else None


def validate_stage(stage: str, artifact: str, context: dict) -> None:
    """Raise ValueError on any ordering or structural violation.

    context keys (all optional unless the stage needs them): spec,
    plan, checklist, tasks, analysis, clarifications, evidence
    ({task_id: {tdd_ok, diff}}), verifications ([{level, passed}]),
    gaps ([{fr, detail, kind}]).
    """
    current = context.get("current_stage")
    expected = next_stage(current)
    if expected is None:
        raise ValueError("Spec pipeline is already finished")
    if stage != expected:
        raise ValueError(
            f"Out of order: next spec stage is '{expected}', not '{stage}'")
    if stage == "constitution":
        if not (artifact or "").strip() or not re.search(
                r"(?m)^\s*(?:#+\s+|-\s+|\d+\.\s+).*?[Pp]rinciple\b", artifact):
            raise ValueError(
                "constitution requires at least one Principle line")
    elif stage == "spec":
        validate_spec(artifact)
    elif stage == "clarify":
        clarifications = context.get("clarifications") or []
        if not clarifications:
            raise ValueError(
                "clarify requires clarifications [{question, answer}]")
        if context.get("spec") is None:
            raise ValueError("clarify requires a stored spec stage")
        # Validates cap (5) + non-empty answers; write-back happens
        # in the route layer.
        apply_clarifications(context["spec"], clarifications)
        if spec_markers(artifact or ""):
            raise ValueError(
                "clarify artifact must not itself carry unresolved markers")
    elif stage == "plan":
        if context.get("spec") is None:
            raise ValueError("plan requires a stored spec stage")
        validate_plan(artifact, context["spec"])
    elif stage == "checklist":
        if context.get("spec") is None:
            raise ValueError("checklist requires a stored spec stage")
        validate_checklist(artifact, context["spec"])
    elif stage == "tasks":
        validate_tasks(artifact)
    elif stage == "analyze":
        if context.get("spec") is None:
            raise ValueError("analyze requires a stored spec stage")
        validate_analysis(context["spec"], artifact)
    elif stage == "implement":
        tasks_text = context.get("tasks") or ""
        tasks = validate_tasks(tasks_text) if tasks_text else []
        if not tasks:
            raise ValueError("implement requires a stored tasks stage")
        evidence = context.get("evidence") or {}
        missing = [t["id"] for t in tasks
                   if not (evidence.get(t["id"]) or {}).get("tdd_ok")]
        if missing:
            raise ValueError(
                "implement halted: tasks without TDD-OK (RED+GREEN) "
                f"evidence: {', '.join(missing)}")
        if not (artifact or "").strip():
            raise ValueError("implement requires a summary artifact")
    elif stage == "verify":
        verifications = context.get("verifications") or []
        if not any(v.get("level") == "targeted" and v.get("passed")
                   for v in verifications):
            raise ValueError(
                "verify requires a passing 'targeted' GreenContract "
                "verification record (record one via /verify first)")
        if not (artifact or "").strip():
            raise ValueError("verify requires a summary artifact")
    elif stage == "converge":
        validate_converge_report(artifact, context.get("gaps") or [])
