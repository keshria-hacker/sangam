---
id: code-review
name: Code Review
category: engineering
invocation: both
description: Review code on two axes in parallel — Standards (correctness, security, style, tests) and Spec (does it do what the spec asked, nothing more). Severity-graded findings; critical issues block.
tags: [code-review, review, quality]
triggers: ["review this code", "code review", "review my change"]
---
# Code Review

Two axes, graded findings, no rubber stamps.

## Axis 1 — Standards
Correctness (logic errors, edge cases), security (injection, secrets,
unsafe execution), readability, and test coverage of the change.

## Axis 2 — Spec
Does the change do exactly what the spec asked — no more, no less?
Flag scope creep and missing acceptance criteria separately from bugs.

## Severity
- Critical: security hole, data loss, or wrong behaviour — blocks merge.
- Major: likely bug or missing test — must be fixed or explicitly waived.
- Minor: style, naming, small simplifications — fix if cheap.

## Output
Findings grouped by severity with file/line references and a concrete
suggested fix for each. End with a verdict: approve, approve-with-nits,
or block (with the blocking findings listed first).
