"""
api_routes/learn_routes.py — learning mode API (OpenMAIC classroom pattern).

Stateless lesson/feedback flow, gated end-to-end by FEATURE_LEARNING.
The frontend keeps the current lesson in memory and sends it back with
the learner's answer.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..learn import LearnError, start_lesson, tutor_feedback
from .common import router


def _require_learn() -> None:
    if not settings.FEATURE_LEARNING:
        raise HTTPException(status_code=404, detail="Learning mode is not enabled")


class LessonIn(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    model: str | None = None


class FeedbackIn(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    lesson: str = Field(min_length=1, max_length=20000)
    answer: str = Field(min_length=1, max_length=5000)
    model: str | None = None


async def _model_id(model: str | None, db: AsyncSession) -> str:
    from ..llm import default_model_id

    model_id = model or await default_model_id(db)
    if not model_id:
        raise HTTPException(status_code=400, detail="No model available.")
    return model_id


@router.post("/learn/lesson")
async def create_lesson(payload: LessonIn, db: AsyncSession = Depends(get_db)):
    """Teacher agent produces a structured lesson on the topic."""
    _require_learn()
    try:
        lesson = await start_lesson(payload.topic, await _model_id(payload.model, db), db)
    except LearnError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"topic": lesson.topic, "lesson": lesson.content}


@router.post("/learn/feedback")
async def answer_feedback(payload: FeedbackIn, db: AsyncSession = Depends(get_db)):
    """Tutor agent gives Socratic feedback on the learner's answer."""
    _require_learn()
    try:
        fb = await tutor_feedback(
            payload.topic, payload.lesson, payload.answer,
            await _model_id(payload.model, db), db,
        )
    except LearnError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"feedback": fb.feedback}
