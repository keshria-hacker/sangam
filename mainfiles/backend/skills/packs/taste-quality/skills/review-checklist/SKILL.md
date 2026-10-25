---
id: review-checklist
name: Review Checklist
category: engineering
invocation: both
description: "Severity-tiered code review: report every finding as blocker, suggestion, or nit on one shared scale, so reviews from different reviewers are comparable and blockers can never hide in prose."
tags: [review, checklist, severity, code-review]
triggers: ["review this", "check this change", "review the diff"]
version: 1.0.0
last_reviewed: 2026-10-26
---

# Review Checklist

Severity-tiered review on one shared scale (see
`backend/teams/review_schema.py`, which parses this format).

## The scale

- 🔴 blocker — must fix before merge. A run cannot finish with an
  open blocker unacknowledged. Cite the exact lines.
- 🟡 suggestion — should fix; may ship with a recorded reason.
- 💭 nit — polish only; never blocks, never inflates a report.

Write findings as tiered lines, one per line:

- 🔴 blocker: <what> — <problem> — <fix>
- 🟡 suggestion: <what> — <problem> — <fix>
- 💭 nit: <what>

## Rules

- Concrete case or no finding: never guess a pitfall from the task
  text; every finding cites real lines.
- Untiered prose is not a finding and must not be counted.
- End with a verdict: `blocked` when any blocker is open, otherwise
  `pass`, plus what was not checked.
- A suggestion shipped without a recorded reason is a process miss,
  not a code miss — say so.
