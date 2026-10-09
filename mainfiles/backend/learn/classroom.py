"""
learn/classroom.py — multi-agent interactive classroom (OpenMAIC pattern).

A lesson is a Teacher agent producing a structured explanation plus a check
question; the Tutor agent then evaluates the learner's answer Socratically.
ECC's research-first principle: the teacher must ground explanations in
concrete specifics (examples, numbers, mechanisms) — no hand-waving.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from ..feature_flags import is_enabled

logger = logging.getLogger(__name__)

TEACHER_PROMPT = """You are a skilled teacher running a one-on-one lesson.
Research-first: ground everything in concrete specifics — real examples,
numbers, mechanisms, named concepts. Never hand-wave.

Produce the lesson in this exact structure:

## The big idea
One paragraph: what this is and why it matters.

## How it works
The mechanism, step by step. Use a concrete example throughout.

## Common misconception
One thing learners usually get wrong, and the correction.

## Check yourself
One question that tests real understanding (not recall). State the question,
then on a new line write "ANSWER:" followed by the correct answer and a
one-line explanation of why.

Keep the whole lesson under 350 words. Use headers exactly as above."""

TUTOR_PROMPT = """You are a Socratic tutor. The learner just answered your check
question. Given the lesson and the correct answer:

- If the answer is correct (or essentially correct): say so warmly in one
  line, then ask ONE follow-up question that goes one level deeper.
- If partially correct: name what's right, pinpoint the gap, and give a
  targeted hint — do not just give the answer.
- If wrong: don't reveal the answer immediately. Ask a guiding question that
  leads toward it.

Keep feedback under 150 words. End with a question whenever the learner
should continue."""


@dataclass
class Lesson:
    topic: str
    content: str  # markdown lesson including the check question


@dataclass
class Feedback:
    feedback: str  # markdown tutor response


async def _complete(model_id: str, messages: list[dict], db: Any, temperature: float) -> str:
    from ..llm import stream_completion

    parts: list[str] = []
    async for chunk in stream_completion(model_id, messages, db, temperature=temperature, max_tokens=1500):
        text = chunk if isinstance(chunk, str) else getattr(chunk, "text", None)
        if text:
            parts.append(text)
    return "".join(parts).strip()


async def start_lesson(topic: str, model_id: str, db: Any) -> Lesson:
    """Teacher agent produces a structured lesson on the topic."""
    from ..config import settings

    if not is_enabled("learning"):
        raise LearnError("Learning mode is not enabled (FEATURE_LEARNING=false).")
    topic = (topic or "").strip()
    if not topic:
        raise LearnError("Empty topic.")
    content = await _complete(
        model_id,
        [
            {"role": "system", "content": TEACHER_PROMPT},
            {"role": "user", "content": f"Teach me: {topic}"},
        ],
        db,
        temperature=0.6,
    )
    if not content:
        raise LearnError("The teacher produced an empty lesson.")
    return Lesson(topic=topic, content=content)


async def tutor_feedback(topic: str, lesson: str, answer: str, model_id: str, db: Any) -> Feedback:
    """Tutor agent evaluates the learner's answer Socratically."""
    from ..config import settings

    if not is_enabled("learning"):
        raise LearnError("Learning mode is not enabled (FEATURE_LEARNING=false).")
    if not (answer or "").strip():
        raise LearnError("Empty answer.")
    feedback = await _complete(
        model_id,
        [
            {"role": "system", "content": TUTOR_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Topic: {topic}\n\nLesson I taught:\n{lesson}\n\n"
                    f"Learner's answer: {answer}"
                ),
            },
        ],
        db,
        temperature=0.6,
    )
    if not feedback:
        raise LearnError("The tutor produced empty feedback.")
    return Feedback(feedback=feedback)


class LearnError(RuntimeError):
    """A learning-mode failure the user can act on."""
