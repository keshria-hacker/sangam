---
id: to-spec
name: To Spec
category: engineering
invocation: both
description: "Turn a conversation (or a grill decision list) into a short, testable specification: user stories, acceptance criteria, out-of-scope list, and open questions. No implementation details."
tags: [spec, specification, requirements]
triggers: ["write a spec", "to spec", "turn this into a spec"]
---
# To Spec

Write the spec the implementation will be judged against.

## Structure
1. Goal — one paragraph, user-visible outcome.
2. User stories — "As a …, I want …, so that …".
3. Acceptance criteria — numbered, each checkable by a test or by hand.
4. Out of scope — things explicitly NOT being built.
5. Open questions — anything still ambiguous, with a named owner if known.

## Rules
- No file names, no function names, no library choices. If a detail is
  implementation, it belongs in the plan, not the spec.
- Every acceptance criterion must be verifiable. "Works well" is not a
  criterion; "returns 422 on out-of-order input" is.
- When the conversation contradicts itself, flag it instead of silently
  picking a side.
