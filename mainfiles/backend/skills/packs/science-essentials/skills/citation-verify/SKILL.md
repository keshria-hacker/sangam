---
id: citation-verify
name: Citation Verify
category: knowledge
invocation: both
model_invocation: true
description: Verify citations in a draft deterministically — every in-text citation must resolve to a reference-list entry, every reference must be cited, duplicates and malformed DOIs are flagged. Use when checking references, citations, or a bibliography in a draft.
tags: [research, citations, verification]
triggers: ["verify citations", "check references", "check the bibliography"]
---

# Citation Verify

Check a draft's citations deterministically — do not hand-verify
reference lists in chat. Use the skill script:

```
python3 scripts/verify_citations.py --text draft.txt
```

The script is self-contained (stdlib only) and deterministic: the same
draft always produces the same report. It reads the draft from a file
(or stdin) and prints one line per finding plus a summary.

## What it checks
- Every in-text citation `[n]` or `(Author, Year)` resolves to an entry
  in the References section; unresolved citations are flagged.
- Every References entry is cited at least once; uncited entries are flagged.
- Duplicate reference entries and malformed DOIs (`10.` prefix required)
  are flagged.
- Claims marked `[needs citation]` are counted, not treated as verified.

## Rules
- A citation that doesn't support its claim is worse than no citation —
  this script checks resolvability, not support; support still needs a
  human (or the literature-review skill) to read the source.
- See references/checklist.md for the full verification checklist
  (lazy reference — read only when a draft needs the full procedure).
