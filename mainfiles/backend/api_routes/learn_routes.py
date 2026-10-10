"""
api_routes/learn_routes.py — learning mode API (OpenMAIC classroom pattern).

Stateless lesson/feedback flow, gated end-to-end by FEATURE_LEARNING.
The frontend keeps the current lesson in memory and sends it back with
the learner's answer.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..feature_flags import is_enabled
from ..database import get_db
from ..learn import LearnError, start_lesson, tutor_feedback
from .common import router


def _require_learn() -> None:
    if not is_enabled("learning"):
        raise HTTPException(status_code=404, detail="Learning mode is not enabled")


class LessonIn(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    model: str | None = None


class FeedbackIn(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    lesson: str = Field(min_length=1, max_length=20000)
    answer: str = Field(min_length=1, max_length=5000)
    model: str | None = None


class OutlineIn(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    model: str | None = None


class QuizIn(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    lesson: str = Field(min_length=1, max_length=20000)
    num_questions: int = Field(default=5, ge=1, le=10)
    model: str | None = None


class GradeIn(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    questions: list[dict] = Field(min_length=1)
    answers: list[str] = Field(min_length=1)
    model: str | None = None


async def _model_id(model: str | None, db: AsyncSession) -> str:
    from ..llm import default_model_id

    model_id = model or await default_model_id(db)
    if not model_id:
        raise HTTPException(status_code=400, detail="No model available.")
    return model_id


@router.post("/learn/lesson")
async def create_lesson(
    payload: LessonIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Teacher agent produces a structured lesson on the topic."""
    _require_learn()
    try:
        lesson = await start_lesson(payload.topic, await _model_id(payload.model, db), db)
    except LearnError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    from ..analytics import events as _ae, optional_user_id, record_event as _record

    await _record(db, await optional_user_id(request, db), _ae.LESSON_STARTED, {})
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


@router.post("/learn/outline")
async def create_outline(payload: OutlineIn, db: AsyncSession = Depends(get_db)):
    """Generate an editable lesson outline from a topic."""
    _require_learn()
    from ..llm import stream_completion

    model_id = await _model_id(payload.model, db)
    prompt = f"""Create a structured lesson outline for the topic: {payload.topic}

Return a JSON array of sections, each with:
- "title": section title
- "points": array of 2-4 key points to cover
- "duration_min": estimated minutes

Example:
[{{"title": "Introduction", "points": ["What it is", "Why it matters"], "duration_min": 5}}]

Return ONLY the JSON array, no other text."""
    try:
        parts = []
        async for chunk in stream_completion(
            model_id,
            [{"role": "user", "content": prompt}],
            db,
            max_tokens=2000,
            temperature=0.7,
        ):
            text = chunk if isinstance(chunk, str) else getattr(chunk, "text", None)
            if text:
                parts.append(text)
        import json as _json
        import re
        raw = "".join(parts)
        # Extract JSON array from response
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            outline = _json.loads(match.group(0))
        else:
            outline = _json.loads(raw)
        return {"topic": payload.topic, "outline": outline}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Outline generation failed: {exc}")


@router.post("/learn/quiz")
async def create_quiz(payload: QuizIn, db: AsyncSession = Depends(get_db)):
    """Generate a quiz from a lesson."""
    _require_learn()
    from ..llm import stream_completion

    model_id = await _model_id(payload.model, db)
    prompt = f"""Based on this lesson about "{payload.topic}", create {payload.num_questions} quiz questions.

Lesson:
{payload.lesson[:8000]}

Return a JSON array, each with:
- "question": the question text
- "options": array of 4 options (for multiple choice)
- "answer": the correct option (exact text from options)
- "explanation": brief explanation of why it's correct

Return ONLY the JSON array, no other text."""
    try:
        parts = []
        async for chunk in stream_completion(
            model_id,
            [{"role": "user", "content": prompt}],
            db,
            max_tokens=2000,
            temperature=0.7,
        ):
            text = chunk if isinstance(chunk, str) else getattr(chunk, "text", None)
            if text:
                parts.append(text)
        import json as _json
        import re
        raw = "".join(parts)
        match = re.search(r'\[.*\]', raw, re.DOTALL)
        if match:
            questions = _json.loads(match.group(0))
        else:
            questions = _json.loads(raw)
        return {"topic": payload.topic, "questions": questions}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Quiz generation failed: {exc}")


@router.post("/learn/grade")
async def grade_quiz(payload: GradeIn, db: AsyncSession = Depends(get_db)):
    """Grade quiz answers. Returns score and per-question feedback."""
    _require_learn()
    if len(payload.questions) != len(payload.answers):
        raise HTTPException(status_code=400, detail="Questions and answers count mismatch")

    results = []
    correct = 0
    for q, ans in zip(payload.questions, payload.answers):
        expected = (q.get("answer") or "").strip().lower()
        given = (ans or "").strip().lower()
        is_correct = given == expected or (given and given in expected) or (expected and expected in given)
        if is_correct:
            correct += 1
        results.append({
            "question": q.get("question"),
            "your_answer": ans,
            "correct_answer": q.get("answer"),
            "explanation": q.get("explanation"),
            "correct": is_correct,
        })

    total = len(payload.questions)
    return {
        "score": correct,
        "total": total,
        "percentage": round(correct / total * 100, 1) if total else 0,
        "results": results,
    }
