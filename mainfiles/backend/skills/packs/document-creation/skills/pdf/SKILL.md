---
id: pdf
name: Pdf
category: productivity
invocation: both
description: Create PDF documents deterministically with a stdlib-only hand-rolled writer — title plus headed sections, no PDF library needed. Output starts with %PDF.
tags: [pdf, document, generation]
triggers: ["create a pdf", "make a pdf", "generate a pdf"]
---
# Pdf

Create a PDF deterministically — do not describe PDF bytes in chat.
Use the skill script:

```
python3 scripts/generate.py --title "Doc" --out out.pdf \
  --sections '[{"heading": "Intro", "body": "Text here"}]'
```

The script is a minimal hand-rolled PDF writer (stdlib only, Helvetica,
single page in v1). Verify: the file starts with `%PDF` and contains
the title text.

## Rules
- Plain text only; long bodies wrap at ~95 characters. Very long
  documents are truncated at the page bottom in v1 — split them.
