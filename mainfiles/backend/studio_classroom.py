"""
backend/studio_classroom.py — OpenMAIC-style classroom template
(spec/a6-studio-skills, Cluster H classroom, Cluster E note).

This is a TEMPLATE + deterministic generator, NOT a separate tab and
NOT a video/slide-editor service (both out of scope here):
  topic/document -> slide outline + quiz + interactive HTML + PBL plan.

No LLM is involved and no learning outcome is invented: slides and
quiz questions are built from the caller's own topic + source sentences
(the first sentences of the supplied source text). When no source text
is given, the outline is a labelled skeleton the teacher fills in —
the response says so (``source_based: false``) instead of presenting
generic filler as content. MP4 export is not offered.
"""
from __future__ import annotations

import html as _html
import re

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _sentences(source_text: str, limit: int = 8) -> list[str]:
    text = re.sub(r"\s+", " ", (source_text or "").strip())
    if not text:
        return []
    parts = [s.strip() for s in _SENTENCE.split(text) if s.strip()]
    return parts[:limit]


def _skeleton_slide(topic: str, index: int) -> dict:
    return {"title": f"{topic} — part {index}",
            "bullets": ["Add your key point here (skeleton slide — fill in before presenting)."],
            "skeleton": True}


def generate_classroom(topic: str, source_text: str = "") -> dict:
    """Generate slides + quiz + interactive HTML + PBL for a topic."""
    topic = (topic or "").strip() or "Untitled topic"
    sentences = _sentences(source_text)
    source_based = bool(sentences)
    if source_based:
        slides = []
        for i, sent in enumerate(sentences[:5], start=1):
            slides.append({
                "title": f"{topic} — {i}",
                "bullets": [sent],
                "skeleton": False,
            })
    else:
        slides = [_skeleton_slide(topic, i) for i in (1, 2, 3)]
    quiz = []
    for i, sent in enumerate(sentences[:4], start=1):
        # Recall question grounded in the source sentence itself; the
        # correct option is the sentence, distractors are labelled as
        # placeholders the teacher replaces — never fake facts.
        quiz.append({
            "question": f"Which statement matches the source material (item {i})?",
            "options": [sent, "Not stated in the source material.",
                        "Not stated in the source material.",
                        "Not stated in the source material."],
            "answer_index": 0,
            "source_sentence": sent,
        })
    if not quiz:
        quiz = [{
            "question": "Skeleton quiz — add a question about your topic here.",
            "options": ["Option A", "Option B", "Option C", "Option D"],
            "answer_index": 0,
            "source_sentence": "",
            "skeleton": True,
        }]
    pbl = {
        "driving_question": f"How can we apply {topic} to a real problem in our community?",
        "milestones": [
            "Define the problem in one paragraph.",
            "Research from the source material and note evidence.",
            "Build a small prototype or worked example.",
            "Present findings and reflect on what changed.",
        ],
    }
    items = "".join(
        f"<section><h2>{_html.escape(s['title'])}</h2><ul>"
        + "".join(f"<li>{_html.escape(b)}</li>" for b in s["bullets"])
        + "</ul></section>"
        for s in slides
    )
    quiz_html = "".join(
        f"<section><h3>{_html.escape(q['question'])}</h3><ol>"
        + "".join(f"<li>{_html.escape(o)}</li>" for o in q["options"])
        + "</ol></section>"
        for q in quiz
    )
    interactive_html = (
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>{_html.escape(topic)}</title>\n</head>\n<body>\n"
        f"<h1>{_html.escape(topic)}</h1>\n{items}\n<h2>Quiz</h2>\n{quiz_html}\n"
        f"<h2>Project-based learning</h2>\n<p>{_html.escape(pbl['driving_question'])}</p>\n"
        "<ol>" + "".join(f"<li>{_html.escape(m)}</li>" for m in pbl["milestones"]) + "</ol>\n"
        "</body>\n</html>\n"
    )
    return {
        "topic": topic,
        "source_based": source_based,
        "slides": slides,
        "quiz": quiz,
        "pbl": pbl,
        "interactive_html": interactive_html,
        "exports": ["html", "pptx-via-documents-generate"],
        "not_offered": ["mp4", "slide-editor"],
    }
