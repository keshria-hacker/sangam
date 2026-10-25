"""backend/spec/ — A5 spec pipeline (perfect-flow Cluster G).

The enforced state machine lives in :mod:`state_machine`; it REUSES
the validators in :mod:`backend.spec_chain` (spec/plan/tasks/analysis)
instead of rewriting them, and adds the stages the old chain lacked:
``checklist`` (between plan and tasks), ``verify`` (GreenContract,
between implement and converge), and real TDD evidence (RED/GREEN)
plus a stored convergence report. The old chain
(constitution->spec->clarify->plan->tasks->implement->analyze->converge)
is left untouched for backward compatibility — this package is the
v2 pipeline with the full order:

  constitution -> spec -> clarify -> plan -> checklist -> tasks
  -> analyze -> implement -> verify -> converge
"""
from .checklist import parse_checklist, render_checklist, validate_checklist
from .converge import build_convergence_report, validate_converge_report
from .review import render_pr_review
from .state_machine import STAGES, next_stage, validate_stage
from .store import ArtifactStore
from .tdd import is_failure_output, is_pass_output, validate_tdd_evidence

__all__ = [
    "STAGES", "next_stage", "validate_stage",
    "parse_checklist", "render_checklist", "validate_checklist",
    "is_failure_output", "is_pass_output", "validate_tdd_evidence",
    "build_convergence_report", "validate_converge_report",
    "render_pr_review", "ArtifactStore",
]
