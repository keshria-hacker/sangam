---
id: grill
name: Grill
category: engineering
invocation: both
description: Relentlessly interview the user until every branch of the design tree is resolved, before any code is written. Asks one question at a time, plays the design back, and ends with a confirmed decision list.
tags: [grill, interview, design, requirements]
triggers: ["grill me", "grill", "interview me about"]
---
# Grill

Do not write code until the design is fully resolved.

## Method
1. Ask ONE question at a time. Wait for the answer before asking the next.
2. Cover, in order: goal and non-goals, users, inputs/outputs, edge cases,
   constraints (time, cost, security), and what "done" looks like.
3. Whenever the user answers vaguely, offer two or three concrete options
   and ask them to pick or correct you.
4. After each answer, restate the decision in one line and keep a running
   decision list.
5. Stop only when no open branch remains, or the user says "enough".

## Output
A decision list: each decision, the alternatives considered, and anything
explicitly left open. The next stage (brainstorm/spec) may not start until
the user confirms this list.
