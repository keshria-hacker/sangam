---
id: smallest-change-review
name: Smallest Change Review
category: engineering
invocation: both
description: "Review a change by the smallest-change rule: reuse first, smallest fix that fully solves the task, every finding backed by a concrete failing case, and a footer stating what was not checked and the risks the user must know."
tags: [review, smallest-change, reuse-first, concrete-case]
triggers: ["review this change", "review the diff", "smallest change", "is this change minimal"]
version: 1.0.0
last_reviewed: 2026-10-26
---

# Smallest Change Review

Sangam-native review discipline (inspired by the ponytail "lazy senior
dev" pattern, written here in Sangam's own words — no upstream text
is copied). It pairs with `review-checklist` (severity tiers): this
skill decides WHAT counts as a finding; that skill decides how
severe it is.

## The smallest-change rule

For the task the change claims to solve, prefer in this order:

1. An existing helper that already does it.
2. The standard library / platform capability.
3. An already-installed dependency.
4. A one-liner.
5. The minimum new code that fully solves the task.

Never add a dependency for a few lines of code. Never cut
validation, error handling, security checks, or accessibility to
make a change smaller — a change that drops those is not smaller,
it is unfinished.

## Every finding needs a concrete case

A finding without a concrete failing case is not reported. For each
finding, state:

- What: the exact lines / behaviour.
- Case: an input or situation that produces the wrong result today.
- Fix: the smallest change that fixes that case.
- If skipped: what happens if the change ships without the fix.

Rank findings: correct first, then safe, then holds under load,
then tested, then fast, then lean. A shortcut with a known limit
gets a comment at the shortcut: `shortcut: <limit>, <when to upgrade>`.

## What the review must read

Read the code the change TOUCHES, not just the diff: callers,
callees, tests, and the README/docs lines that describe the
behaviour. A diff-only review misses the call site that breaks.

## The footer (always present)

Every review ends with two lists, even when empty:

- Not checked: what the review did not examine (e.g. "production
  load", "the migration path", "other callers outside this repo").
- Risks the user must know: what could still go wrong after this
  change ships.

A review without the footer is incomplete: silence about coverage
reads as a claim of full coverage, and this skill never claims
coverage it does not have.

## Verdict

End with one line: `pass`, `pass with suggestions`, or `blocked`
(when any must-fix finding is open), followed by the footer.
