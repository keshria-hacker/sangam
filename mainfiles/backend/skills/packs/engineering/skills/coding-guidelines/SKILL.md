---
id: coding-guidelines
name: Coding Guidelines
category: engineering
invocation: both
description: "Behavioural guardrails for code work: think before coding, simplest change first, surgical edits only, and a verifiable success check before reporting done. Injected by default for code-agent runs."
tags: [coding, guidelines, simplicity, verification]
triggers: ["write code", "implement this", "fix the code", "change the code"]
allowed_tools: [read_file, list_files, write_file, edit_file, run_bash, code_map]
version: 1.0.0
last_reviewed: 2026-10-26
---

# Coding Guidelines

Sangam-native behavioural guardrails for code work, written from the
failure modes of hurried agent coding. This skill biases toward caution
over speed on purpose: a slow correct change beats a fast wrong one.

## Think before coding

- State your assumptions and the tradeoffs in one short paragraph
  before touching a file. If an assumption could change the design,
  surface it instead of guessing.
- If the request is unclear in a way that changes the outcome, ask
  one crisp question and wait — do not pick silently.

## Simplest change first

- Minimum code that satisfies the request. No speculative abstraction,
  no extra configurability, no feature the request did not ask for.
- Match the existing style of the surrounding code; do not reformat
  unrelated lines.

## Surgical edits only

- Touch only what the request requires. Every changed file and line
  must trace back to the task; anything else is flagged in the run
  report, not smuggled in.
- Clean up only your own orphans (files you created and no longer
  need). Never delete code you did not create unless asked.

## Goal-driven execution

- Turn every task into verifiable success criteria first: what test,
  command, or check proves it works?
- Loop until the criteria pass or you are blocked — then report the
  block exactly, with the evidence, instead of claiming progress.
- After edits, run the project's own test command (the verify gate)
  and report its real result, pass or fail.
