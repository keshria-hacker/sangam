---
name: editorial-diagrams
description: Make an editorial diagram from the 44-type catalogue — one accent colour, hairline strokes, a 4px grid — as a Mermaid starter or a self-contained HTML+SVG node/edge render.
category: design
invocation: both
---

# Editorial diagrams

## When to use

The user wants a diagram that reads like an editorial figure, not a
default graph dump: a flowchart, org chart, timeline, architecture
sketch, or any of the 44 catalogue types.

## Rules

1. Pick ONE type from the catalogue (`GET /api/diagrams/catalogue`).
   Do not invent a new type name.
2. ONE accent colour per diagram. Hairline (1px) strokes, no shadows.
3. Labels are short (under 60 characters) and plain — no jargon the
   reader cannot decode without the diagram.
4. Prefer the node/edge render (`POST /api/diagrams/export`, format
   `svg` or `html`) when the diagram is a set of boxes and arrows: the
   output is a standalone file with no external assets.
5. For catalogue templates, ship the Mermaid starter and say it is a
   starter the user edits — never claim it has been rendered or
   checked visually. Overlap and clipping are visual checks.
6. Brand profiles (`GET /api/diagrams/brands`) supply the accent and
   font; never hard-code a brand colour into a template.

## Output

A diagram the user can open, plus one sentence saying what it shows
and what, if anything, is still a starter.
