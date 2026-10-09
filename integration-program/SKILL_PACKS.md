# Skill Packs — curated skill bundles

**Status:** implemented (2026-10-08) · branch `skill-packs`
**Inspired by:** github/spec-kit, tt-a1i/archify, K-Dense-AI/scientific-agent-skills, earendil-works/pi

## What the reference repos taught us

- **spec-kit** — Spec-Driven Development: constitution → specify → plan →
  tasks → implement. Pure workflow + markdown templates; fully portable.
- **archify** — an agent *skill* (SKILL.md) that turns ideas/codebases into
  interactive diagrams. Sangam renders Mermaid natively, so the skill plugs
  straight in.
- **scientific-agent-skills** — 177 validated skills; too many to bundle.
  The portable pattern is a *curated starter set* with the upstream library
  as the deep well.
- **pi** — agent toolkit; its portable idea is loop discipline (autonomy
  ladder, verify-don't-trust), which Sangam lacked as an explicit skill.

## Architecture

```
backend/skills/packs/<pack>/
  pack.yaml                  manifest: name, version, description, source
  skills/<skill>/SKILL.md    Claude-style frontmatter (registry already
  skills/<skill>/references/   supports it since Foundation F2)

packs.py      PackManager: list/get/enable/disable, state in
              config/skills/.pack_state.json (gitignored)
registry.py   SkillRegistry(extra_roots=[...]) — enabled packs load
              without file copying; user skills win id collisions
api_skills.py GET /skills/packs, POST /skills/packs/{name}/enable|disable
```

### Bundled packs
| Pack | Skills | Source |
|---|---|---|
| spec-driven | sdd-workflow (+ 4 templates) | github/spec-kit |
| diagramming | archify | tt-a1i/archify |
| science-essentials | literature-review, data-analysis, citation-hygiene | K-Dense-AI/scientific-agent-skills |
| agent-loop | tool-discipline | earendil-works/pi |

Packs are **disabled by default** — the user opts in via the Skills modal
(new pack strip with Enable/Disable) or the API. Enabling reloads the skill
registry so pack skills immediately become invokable.

### Extension registry
Each pack projects as `skill-pack:<name>` (kind: SKILL).

## Writing your own pack
1. Create `backend/skills/packs/<name>/pack.yaml` (see spec-driven).
2. Add `skills/<skill>/SKILL.md` files (Claude-style frontmatter).
3. It appears in `GET /skills/packs` automatically — no code changes.

## Future (not in this pass)
- Remote pack installation (fetch a pack from a git URL)
- Pack versioning / updates
- Per-pack skill enable/disable (currently pack-level only)
- Deeper scientific packs (the 177-skill library as opt-in remote packs)
