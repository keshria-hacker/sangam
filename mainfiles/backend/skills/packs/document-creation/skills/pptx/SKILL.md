---
id: pptx
name: Pptx
category: productivity
invocation: both
description: Create PowerPoint (.pptx) decks deterministically with a stdlib-only script — a title slide with headed bullet lines, no new dependency needed.
tags: [pptx, presentation, slides, generation]
triggers: ["create a pptx", "make slides", "generate a pptx"]
---
# Pptx

Create a .pptx file deterministically — do not hand-write presentation
XML in chat. Use the skill script:

```
python3 scripts/generate.py --title "Deck" --out out.pptx \
  --sections '[{"heading": "Point", "body": "Detail"}]'
```

The script builds the file with zipfile + templated XML (stdlib only).
Verify: it opens as a ZIP and `ppt/slides/slide1.xml` contains the
title text.

## Rules
- One slide in v1: title plus one line per section ("Heading: body").
  Split longer decks into multiple files or sections until multi-slide
  support lands.
