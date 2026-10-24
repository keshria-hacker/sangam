---
id: tdd
name: TDD
category: engineering
invocation: both
description: "Test-driven development, one vertical slice at a time: RED (failing test first), GREEN (smallest change that passes), REFACTOR. Delete code written before its test."
tags: [tdd, testing, red-green-refactor]
triggers: ["test-driven", "tdd", "write tests first"]
---
# TDD

RED — GREEN — REFACTOR, one slice at a time.

## Rules
1. RED: write a failing test for one small behaviour first. Watch it fail
   for the right reason; a test that passes before the change proves
   nothing and must be rewritten.
2. GREEN: write the smallest code that makes the test pass. No extra
   features, no speculative generality (YAGNI).
3. REFACTOR: clean up only while tests stay green. Duplication removed
   here, not during GREEN.
4. One slice at a time: finish a behaviour end-to-end before starting
   the next. A half-tested feature is not progress.
5. Code written before its test is deleted and rewritten test-first —
   no exceptions, no "but it works".

## What makes a good test
- Named for the behaviour, not the method: "rejects out-of-order stages".
- One behaviour per test; independent of other tests; fast and
  deterministic (no network, no wall-clock dependence).
