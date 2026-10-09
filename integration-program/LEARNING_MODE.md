# Learning Mode — interactive classroom

**Status:** implemented (2026-10-08) · branch `learning-mode`
**Inspired by:** THU-MAIC/OpenMAIC (multi-agent interactive classroom),
affaan-m/ECC (research-first development)

## Architecture

```
backend/learn/
  classroom.py   Teacher agent: structured, research-first lessons
                 (big idea → mechanism → misconception → check question)
                 Tutor agent: Socratic feedback on the learner's answer
  __init__.py    register_learn_extension() -> capability:learning
```

### Flow
1. `POST /api/learn/lesson` {topic} — teacher produces a <350-word structured
   lesson ending with a check question (with hidden answer).
2. Learner answers in the UI.
3. `POST /api/learn/feedback` {topic, lesson, answer} — tutor responds
   Socratically: confirms correct answers and goes deeper, hints at gaps,
   never just reveals.

Gated end-to-end by `FEATURE_LEARNING` (added to config + `/api/features`).

### ECC influence
Research-first: the teacher prompt requires concrete specifics — real
examples, numbers, mechanisms, named concepts — and bans hand-waving.

### Frontend
`features/learn/learn.js` — Learn button (topbar, hidden unless the
`learning` flag is on) opens a modal: topic → lesson → answer → tutor
feedback, repeatable for follow-ups.

## Future (not in this pass)
- Multi-turn curriculum with progress tracking
- Quiz generation and spaced repetition
- Classroom roles (peer learners, per OpenMAIC)
