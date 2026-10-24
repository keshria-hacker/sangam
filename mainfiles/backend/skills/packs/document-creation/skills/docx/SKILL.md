---
id: docx
name: Docx
category: productivity
invocation: both
description: Create Word (.docx) documents deterministically with a stdlib-only script — title plus headed sections, no Office install or new dependency needed. Output is a valid ZIP with Word content types.
tags: [docx, document, word, generation]
triggers: ["create a docx", "make a word document", "generate a docx"]
---
# Docx

Create a .docx file deterministically — do not hand-write Office XML in
chat. Use the skill script:

```
python3 scripts/generate.py --title "My Doc" --out out.docx \
  --sections '[{"heading": "Intro", "body": "Text here"}]'
```

The script builds the file with zipfile + templated XML (stdlib only).
Verify the result: it opens as a ZIP and contains `word/document.xml`
with the title text inside.

## Rules
- Sections are heading/body pairs; keep headings short and bodies plain
  text (no markup — it is escaped, not rendered).
- The output path is written by the script and printed on stdout.
