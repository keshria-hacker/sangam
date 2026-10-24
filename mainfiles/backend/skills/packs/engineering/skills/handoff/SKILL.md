---
id: handoff
name: Handoff
category: engineering
invocation: both
description: "Compress a session into a compact continuation document: goal, decisions, what is done, what is open, and the exact next step — so another session or agent can resume without re-asking everything."
tags: [handoff, continuity, documentation]
triggers: ["write a handoff", "handoff", "summarize for continuation"]
---
# Handoff

Write the document you wish you had received.

## Structure
1. Goal — what this work is trying to achieve, in one paragraph.
2. Decisions — each decision and why, not just what was chosen.
3. Done — what is complete, with evidence (test counts, commit refs).
4. Open — what remains, ordered by what blocks what.
5. Next step — the single concrete action to take first, with enough
   context to do it without re-reading the whole conversation.

## Rules
- Honest limits only: never claim a test passed, a file exists, or a
  review happened unless it did. Mark guesses as guesses.
- Keep it compact: a handoff longer than the work it describes has
  failed. Aim for one screen of text.
