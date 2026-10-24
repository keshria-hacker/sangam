---
id: implement
name: Implement
category: engineering
invocation: both
description: Build from an approved spec and ticket graph, ticket by ticket, in dependency order. Verify each ticket before moving on, and never mark work done on an untested change.
tags: [implement, build, execution]
triggers: ["implement the spec", "implement", "build this"]
---
# Implement

Work the ticket graph in order. No shortcuts.

## Loop per ticket
1. Read the ticket and its done criterion. Restate it in one line.
2. Make the smallest change that satisfies it.
3. Run the relevant check (test, type check, or manual verification) and
   report pass/fail honestly. On failure, fix the cause — do not move on.
4. Only then mark the ticket done and take the next unblocked ticket.

## Rules
- Prefer editing existing code over new abstractions; prefer boring
  solutions over clever ones.
- If a ticket's done criterion turns out to be wrong, say so and update
  the ticket — do not quietly redefine "done".
- Stop and report when blocked (missing credential, ambiguous spec)
  instead of guessing.
