"""
engineering_pipeline.py — Batch 5: enforced engineering workflow.

Stages advance ONLY in order:
  grill -> brainstorm -> design -> plan -> subagent -> review-spec
  -> review-quality -> finish

Enforcement is structural, not LLM judgement:
  * ``advance`` to a stage requires every earlier stage to be complete
    (out-of-order -> 422 in the route layer, ValueError here).
  * Each stage stores its artifact text.
  * review-spec requires the design stage's artifact id as its
    prerequisite (``prerequisite_artifact_id``); review-quality requires
    the plan or subagent stage's artifact id.
  * finish requires BOTH reviews to carry verdict "pass".

Wave-1 (deep-read refinement) additions, legacy behaviour preserved:
  * The "subagent" stage can now run REAL per-task agent runs when the
    pipeline has a spec-chain tasks artifact: one ``run_agent`` run per
    task (see pipeline_agents), joined into a diff ledger. Without
    chain tasks it keeps the v1 behaviour — a linked team run when a
    model is configured, otherwise a marked handoff brief, never
    fabricated output.
  * The strict spec-kit chain (constitution -> ... -> converge, real
    per-task runs with TDD ledger, two-stage review over a real
    BASE/HEAD diff package, finish gated on package-referencing
    verdicts) lives in spec_chain.py and is served by the chain routes
    in engineering_routes.py. The legacy finish gate is kept for
    backward compatibility and is superseded by chain finish for new
    pipelines; see BUILD_LOG2-pipeline.md for the split.

Tables live in this module and register on Base.metadata (Batch 2/4
precedent); models.py is untouched.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession

from .database import Base

STAGES = ["grill", "brainstorm", "design", "plan", "subagent",
          "review-spec", "review-quality", "finish"]

# stage -> prerequisite stage whose artifact id must be supplied
PREREQUISITE_STAGE = {
    "review-spec": "design",
    "review-quality": ("plan", "subagent"),
}


class EngineeringPipeline(Base):
    __tablename__ = "engineering_pipelines"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    goal = Column(Text, nullable=False, default="")
    current_stage = Column(String, nullable=False, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


class EngineeringStage(Base):
    __tablename__ = "engineering_stages"

    id = Column(String, primary_key=True)
    pipeline_id = Column(String, ForeignKey("engineering_pipelines.id"), nullable=False)
    stage = Column(String, nullable=False)
    artifact = Column(Text, nullable=False, default="")
    verdict = Column(String, nullable=True)
    source = Column(String, nullable=False, default="user")  # user|team|handoff
    position = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


def new_pipeline_id() -> str:
    return f"eng-{uuid.uuid4().hex[:12]}"


def next_stage(current: str) -> str | None:
    """Stage that may be advanced to next, given the current stage."""
    if not current:
        return STAGES[0]
    idx = STAGES.index(current) if current in STAGES else -1
    return STAGES[idx + 1] if 0 <= idx + 1 < len(STAGES) else None


async def list_stages(db: AsyncSession, pipeline_id: str) -> list[EngineeringStage]:
    rows = await db.execute(
        select(EngineeringStage).where(
            EngineeringStage.pipeline_id == pipeline_id
        ).order_by(EngineeringStage.position))
    return list(rows.scalars().all())


def pipeline_out(pipe: EngineeringPipeline, stages: list[EngineeringStage]) -> dict:
    return {
        "id": pipe.id, "title": pipe.title, "goal": pipe.goal,
        "current_stage": pipe.current_stage or None,
        "next_stage": next_stage(pipe.current_stage or ""),
        "complete": pipe.current_stage == "finish",
        "stages": [{"id": s.id, "stage": s.stage, "artifact": s.artifact,
                    "verdict": s.verdict, "source": s.source} for s in stages],
    }


async def advance_pipeline(db: AsyncSession, pipe: EngineeringPipeline,
                           stage: str, artifact: str,
                           verdict: str | None = None,
                           prerequisite_artifact_id: str | None = None,
                           source: str = "user") -> EngineeringStage:
    """Advance one stage. Raises ValueError (route maps to 422) on any
    ordering, prerequisite, or finish-gate violation."""
    expected = next_stage(pipe.current_stage or "")
    if expected is None:
        raise ValueError("Pipeline is already finished")
    if stage != expected:
        raise ValueError(
            f"Out of order: next stage is '{expected}', not '{stage}'")
    stages = await list_stages(db, pipe.id)
    by_stage = {s.stage: s for s in stages}

    if stage in ("review-spec", "review-quality"):
        allowed = PREREQUISITE_STAGE[stage]
        allowed = (allowed,) if isinstance(allowed, str) else allowed
        if not prerequisite_artifact_id:
            raise ValueError(
                f"{stage} requires prerequisite_artifact_id "
                f"(the {allowed[0]} stage artifact id)")
        prereq = next((s for s in stages if s.id == prerequisite_artifact_id), None)
        if prereq is None or prereq.stage not in allowed:
            raise ValueError(
                f"prerequisite_artifact_id must be the {allowed[0]} stage artifact")
        if verdict not in ("pass", "fail"):
            raise ValueError(f"{stage} requires verdict 'pass' or 'fail'")

    if stage == "finish":
        reviews = {s.stage: s for s in stages
                   if s.stage in ("review-spec", "review-quality")}
        if any(reviews.get(r) is None or reviews[r].verdict != "pass"
               for r in ("review-spec", "review-quality")):
            raise ValueError(
                "finish requires both reviews (review-spec and "
                "review-quality) to have verdict 'pass'")

    row = EngineeringStage(
        id=f"engs-{uuid.uuid4().hex[:12]}", pipeline_id=pipe.id,
        stage=stage, artifact=artifact or "", verdict=verdict,
        source=source, position=len(stages))
    db.add(row)
    pipe.current_stage = stage
    await db.commit()
    await db.refresh(row)
    return row


async def produce_subagent_output(goal: str, prior_text: str,
                                  db: AsyncSession,
                                  tasks: list[dict] | None = None,
                                  model_id: str | None = None) -> tuple[str, str]:
    """Subagent-stage output.

    With chain tasks (list of {task_id, brief, files}): one REAL agent
    run per task via pipeline_agents.run_task_agent (the code agent's
    own run function), joined into a per-task diff ledger; source is
    "agent". Without tasks, the v1 behaviour is preserved: a linked
    team run when a model is configured, otherwise a marked handoff
    brief. Returns (artifact, source); source is "agent", "team", or
    "handoff". Never fabricates agent output.
    """
    if tasks:
        if model_id is None:
            try:
                from . import llm
                model_id = await llm.default_model_id(db)
            except Exception:  # noqa: BLE001 — no model configured
                model_id = None
        if model_id:
            from .pipeline_agents import run_task_agent
            parts = []
            ran_any = False
            for t in tasks:
                result = await run_task_agent(
                    t.get("task_id", "?"), t.get("brief", ""),
                    model_id, db, files=t.get("files") or [])
                ran_any = True
                parts.append(
                    f"## Task {result.task_id}\n"
                    f"error: {result.error or '(none)'}\n"
                    f"diff:\n{result.diff or '(no file changes)'}\n"
                    f"answer: {result.answer or '(none)'}")
            if ran_any:
                return "\n\n".join(parts), "agent"
    try:
        from . import llm
        resolved = model_id or await llm.default_model_id(db)
    except Exception:  # noqa: BLE001 — no model configured
        resolved = None
    if resolved:
        try:
            from .teams.runner import run_team
            result = await run_team("research", goal, resolved, db)
            if result.synthesis:
                return result.synthesis, "team"
            if result.specialists:
                joined = "\n\n".join(
                    f"## {r.role}\n{r.output}" for r in result.specialists if r.output)
                if joined:
                    return joined, "team"
        except Exception:  # noqa: BLE001 — fall through to handoff brief
            pass
    brief = (
        "HANDOFF BRIEF — no agent run was executed for this stage "
        "(no model configured or the team run failed). A human or agent "
        "should pick this up and produce the implementation output.\n\n"
        f"Goal: {goal}\n\nPrior stages:\n{prior_text or '(none)'}\n"
    )
    return brief, "handoff"
