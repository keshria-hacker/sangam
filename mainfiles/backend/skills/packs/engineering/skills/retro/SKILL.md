---
id: retro
name: Retro
category: engineering
invocation: both
description: "Post-session retrospective: what worked, what broke, and one concrete environment or process improvement to carry forward. Evidence-based, no blame, one action only."
tags: [retro, retrospective, improvement]
triggers: ["run a retro", "retro", "retrospective"]
---
# Retro

Look back once, improve one thing, move on.

## Method
1. Timeline: what actually happened, in order, from evidence (commits,
   test runs, messages) — not from memory of how it felt.
2. Worked / broke: two short lists, each item tied to a concrete event.
3. Root cause for the top breakage only: ask "why" until you hit a
   process or environment cause, not a person.
4. One improvement: a single concrete change (a checklist, a script, a
   default) with an owner and a way to tell next time whether it helped.

## Rules
- No blame, no vague actions ("communicate better" is not an action).
- If the same breakage appeared in the last retro, that improvement
  failed — say so and replace it.
