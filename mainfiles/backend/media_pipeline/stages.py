"""Staged media pipeline definitions (OpenMontage salvage, non-video).

A pipeline is a small JSON stage list attached to a MediaJob::

    {"stages": [{"name": "script", "action": "voice_script",
                 "checkpoint_required": true, "max_revisions": 3,
                 "budget_cap_usd": 5.0, "produces": ["audio"],
                 "input": {"text": "..."}}],
     "budget_cap_usd": 5.0}

Stages run in list order. A stage with ``checkpoint_required`` pauses
the job in ``awaiting_approval`` after it finishes; approve resumes
from the next stage. ``max_revisions`` caps approve/resume cycles per
stage (a resume after a checkpoint counts as a revision). Budget caps
are enforced only on *known* cost: a stage cost is recorded only when
an engine reports one, never invented — an unknown cost never trips
the cap, and the cost record says so.
"""
from __future__ import annotations

import hashlib
import json

STAGE_ACTIONS = {
    # Existing Sangam engines, reached through the job executor.
    "image", "tts", "voice_script", "transcribe",
    # Pure/validated stages implemented in this package.
    "diagram_validate", "design_critique", "subtitle", "overlay",
    "storyboard", "audiobook_plan",
}

MAX_STAGES = 12


def content_hash(payload: object) -> str:
    """Deterministic content hash for job dedup (VoiceStudio's
    ``find_cached_job`` pattern): same canonical input -> same hash."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def validate_pipeline(pipeline: object) -> list[dict]:
    """Return a list of fixable diagnostics (empty = valid)."""
    errs: list[dict] = []

    def err(code: str, message: str, fix: str) -> dict:
        return {"code": code, "message": message, "supportedFixes": fix}

    if not isinstance(pipeline, dict):
        return [err("not-an-object", "pipeline must be an object",
                    "Pass {\"stages\": [...]}.")]
    stages = pipeline.get("stages")
    if not isinstance(stages, list) or not stages:
        return [err("no-stages", "pipeline.stages must be a non-empty list",
                    "Add at least one stage with a name and an action.")]
    if len(stages) > MAX_STAGES:
        errs.append(err("too-many-stages",
                        f"at most {MAX_STAGES} stages per pipeline",
                        f"Split the pipeline into two jobs of <= {MAX_STAGES} stages."))
    cap = pipeline.get("budget_cap_usd")
    if cap is not None and (not isinstance(cap, (int, float)) or cap < 0):
        errs.append(err("bad-budget", "budget_cap_usd must be >= 0",
                        "Set budget_cap_usd to a non-negative number or omit it."))
    seen: set[str] = set()
    for i, stage in enumerate(stages):
        path = f"stages[{i}]"
        if not isinstance(stage, dict):
            errs.append(err("bad-stage", f"{path} must be an object",
                            "Replace it with {name, action}."))
            continue
        name = stage.get("name")
        if not name or not isinstance(name, str):
            errs.append(err("missing-name", f"{path}.name is required",
                            "Give the stage a short name."))
        elif name in seen:
            errs.append(err("duplicate-stage", f"duplicate stage name: {name!r}",
                            f"Rename the second {name!r} stage."))
        seen.add(name) if isinstance(name, str) else None
        action = stage.get("action")
        if action not in STAGE_ACTIONS:
            errs.append(err("bad-action",
                            f"{path}.action must be one of {sorted(STAGE_ACTIONS)}",
                            "Use an existing engine action, or a pure stage "
                            "(diagram_validate, design_critique, subtitle, "
                            "overlay, storyboard, audiobook_plan)."))
        rev = stage.get("max_revisions", 3)
        if not isinstance(rev, int) or rev < 0 or rev > 10:
            errs.append(err("bad-revisions",
                            f"{path}.max_revisions must be an int in 0..10",
                            "Set max_revisions to e.g. 3."))
        scap = stage.get("budget_cap_usd")
        if scap is not None and (not isinstance(scap, (int, float)) or scap < 0):
            errs.append(err("bad-budget",
                            f"{path}.budget_cap_usd must be >= 0",
                            "Set it to a non-negative number or omit it."))
        if stage.get("checkpoint_required") not in (True, False, None):
            errs.append(err("bad-checkpoint",
                            f"{path}.checkpoint_required must be true/false",
                            "Set checkpoint_required to true or omit it."))
        if stage.get("produces") is not None and not isinstance(stage["produces"], list):
            errs.append(err("bad-produces", f"{path}.produces must be a list",
                            "List artifact names, e.g. [\"audio\"]."))
    return errs


class CostRecord:
    """Cost ledger: only engine-reported amounts are recorded.

    ``known`` is False until at least one stage reports a cost, so a
    budget check never aborts on invented numbers.
    """

    def __init__(self) -> None:
        self.total_usd: float = 0.0
        self.known: bool = False
        self.by_stage: dict[str, float] = {}

    def add(self, stage: str, amount_usd: float | None) -> None:
        if amount_usd is None:
            return
        self.known = True
        self.total_usd += float(amount_usd)
        self.by_stage[stage] = self.by_stage.get(stage, 0.0) + float(amount_usd)

    def exceeds(self, cap: float | None) -> bool:
        return self.known and cap is not None and self.total_usd > cap

    def as_dict(self) -> dict:
        return {"total_usd": round(self.total_usd, 6) if self.known else None,
                "known": self.known, "by_stage": self.by_stage}
