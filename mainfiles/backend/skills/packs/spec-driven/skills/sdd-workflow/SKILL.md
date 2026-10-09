---
id: sdd-workflow
name: Spec-Driven Development
category: engineering
invocation: both
description: Build software spec-first — write a constitution, specify the feature, plan the implementation, break it into tasks, then implement with verification. Prevents building the wrong thing.
parameters:
  - name: feature_idea
    type: string
    description: The feature or change to build, in the user's own words
    required: true
  - name: phase
    type: string
    description: Which phase to run — constitution, specify, plan, tasks, implement, or all
    required: false
    default: all
tags: [sdd, spec-kit, planning, workflow]
---

# Spec-Driven Development

Build the feature in five gated phases. **Do not skip phases.** Each phase
produces a short document; the next phase may not start until the user
confirms the current one (a one-line "ok" suffices).

## Phase 1 — Constitution
Establish the non-negotiable principles for this work: correctness bars,
testing requirements, performance budgets, security constraints. Keep it to
5–9 bullet principles. Template: `references/constitution-template.md`.

## Phase 2 — Specify
Write what the feature does from the user's perspective — user stories,
acceptance criteria, out-of-scope list. No implementation details, no file
names, no code. If a requirement is ambiguous, ask rather than assume.
Template: `references/spec-template.md`.

## Phase 3 — Plan
Design the implementation against the spec: architecture decisions,
data model changes, API surface, test plan, rollout/rollback. Flag risks
and unknowns explicitly. Template: `references/plan-template.md`.

## Phase 4 — Tasks
Break the plan into small, independently verifiable tasks (each completable
in one focused session). Order by dependency. Each task states its done
criterion. Template: `references/tasks-template.md`.

## Phase 5 — Implement
Work through the tasks in order. After each task: run the relevant tests,
report pass/fail, and stop on failure. Never mark a task done on an
untested change.

## Rules
- Spec first, code last. A phase's document is the next phase's contract.
- When the user says "just build it", still produce at least a 5-line spec
  and task list before touching code.
- Prefer editing existing code over new abstractions; prefer boring solutions.

Feature to build: {{feature_idea}}
Starting phase: {{phase}}
