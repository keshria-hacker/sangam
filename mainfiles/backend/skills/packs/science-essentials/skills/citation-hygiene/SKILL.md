---
id: citation-hygiene
name: Citation Hygiene
category: knowledge
invocation: both
description: Audit and fix citations — verify claims trace to sources, format references consistently, catch citation drift.
parameters:
  - name: text
    type: string
    description: The draft text with citations to audit
    required: true
tags: [research, citations, writing]
---

# Citation Hygiene

## Process
1. **Extract** — list every factual claim that needs a citation and the
   citation attached to it.
2. **Verify** — for each: does the cited source actually support the claim?
   Flag mismatches as [unsupported], [overstated], or [misattributed].
3. **Format** — normalize all references to one consistent style (author,
   year, title, venue, DOI where available).
4. **Drift check** — flag claims that cite reviews citing reviews (go to the
   primary source), and self-citation clusters.

## Rules
- A citation that doesn't support its claim is worse than no citation.
- Prefer primary sources over reviews; prefer recent replications over
  single old studies for contested claims.

Text to audit: {{text}}
