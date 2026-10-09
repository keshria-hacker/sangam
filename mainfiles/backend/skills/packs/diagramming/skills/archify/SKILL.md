---
id: archify
name: Architecture Diagrams
category: engineering
invocation: both
description: Turn an idea, plan, or codebase into a beautiful Mermaid diagram — system architecture, data flow, sequence, or ER. Diagrams render live in the chat.
parameters:
  - name: subject
    type: string
    description: The idea, plan, or codebase to diagram
    required: true
  - name: diagram_type
    type: string
    description: flowchart, sequence, class, er, or state — pick the one that fits, default flowchart
    required: false
    default: flowchart
tags: [diagrams, mermaid, architecture, visualization]
---

# Architecture Diagrams

Produce a Mermaid diagram for the subject. Sangam renders ```mermaid blocks
live, so always emit the diagram as a fenced mermaid code block.

## Process
1. **Understand** — if the subject is a codebase, identify the key
   components, data stores, and external systems first. If it's an idea,
   identify the actors and the flow of data/control.
2. **Choose the diagram type** — flowchart for architecture, sequenceDiagram
   for interactions over time, erDiagram for data models, classDiagram for
   code structure, stateDiagram for lifecycles. `{{diagram_type}}` is a hint;
   override it when another type fits better and say why.
3. **Keep it readable** — max ~12 nodes. Group related nodes with subgraphs.
   Label edges with verbs ("sends", "reads", "triggers").
4. **Validate** — Mermaid is picky: node ids must be alphanumeric (no spaces
   or dashes — use underscores), labels go in ["brackets"], and every id
   referenced on an edge must be defined.

## Output
- One fenced ```mermaid block with the diagram.
- Below it, 3–6 bullets explaining what the diagram shows and the key
  design decision it captures.

Subject: {{subject}}
