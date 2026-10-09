---
id: literature-review
name: Literature Review
category: knowledge
invocation: both
description: Structured literature review — map what is known, find the gaps, and synthesize findings with traceable claims.
parameters:
  - name: topic
    type: string
    description: The research question or topic to review
    required: true
  - name: depth
    type: string
    description: quick (key papers) or deep (systematic mapping)
    required: false
    default: quick
tags: [research, science, literature]
---

# Literature Review

## Process
1. **Scope** — restate the research question and define inclusion criteria
   (date range, fields, study types). State what is out of scope.
2. **Map the landscape** — group known work into 3–6 themes or schools of
   thought. For each: key claim, key evidence, leading authors/venues.
3. **Find the gaps** — what is contested, what is unstudied, where methods
   disagree. Rank gaps by importance × tractability.
4. **Synthesize** — a 5-line takeaway: what we know, what we don't, and the
   most promising next experiment or analysis.

## Rules
- Every factual claim gets a source or is marked [needs citation].
- Distinguish established results from single-study findings from speculation.
- End with 3 concrete follow-up questions, not a vague "more research needed".

Topic: {{topic}} (depth: {{depth}})
