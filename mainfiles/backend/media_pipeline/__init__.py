"""media_pipeline — one unified media pipeline (Batch 11).

Unifies what image_gen/, image_ops.py, voice/ and media_jobs_routes.py
already do behind a single staged job model (OpenMontage's pattern,
minus its video output: stages with ``produces``/``checkpoint_required``
/``max_revisions``/``budget_cap``), plus the pure helpers for audio,
diagrams, design critique, node graphs, overlays and storyboards.

Hard exclusions, enforced here and in routes/tests — never add them:
voice cloning / speaker-identity from reference audio, any ``video``
job kind, FaceSwap / face-identity conditioning, custom-node code
execution (the node graph below executes only through handlers the
caller supplies, i.e. Sangam's existing engines).
"""
from .stages import (
    STAGE_ACTIONS,
    content_hash,
    validate_pipeline,
)

__all__ = ["STAGE_ACTIONS", "content_hash", "validate_pipeline"]
