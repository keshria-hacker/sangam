---
id: to-tickets
name: To Tickets
category: engineering
invocation: both
description: Break an approved plan into small, independently verifiable tickets with blocking edges, each completable in one focused session with a stated done criterion.
tags: [tickets, planning, tasks, decomposition]
triggers: ["break into tickets", "to tickets", "make tickets"]
---
# To Tickets

Turn a plan into a ticket graph, not a wish list.

## Rules
- One ticket = one vertical slice, completable in a single focused session.
- Each ticket states: goal, files touched, done criterion (test or check),
  and the tickets that block it (blocking edges, no cycles).
- Order tickets by dependency, not by enthusiasm. The first ticket must be
  runnable without the others.
- A ticket with no done criterion is not a ticket — rewrite it until it
  has one.
- Keep the graph small: if it exceeds about 12 tickets, the scope is too
  big and should be split first.
