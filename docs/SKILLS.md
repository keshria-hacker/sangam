# Sangam — Skills & Library (perfect-flow program)

## The SKILL.md contract

A skill is a directory with a `SKILL.md` front-matter contract
(name, version, description, inputs, outputs, permissions) plus its
implementation. The registry enforces the contract: a skill that
does not declare what it does cannot be installed. Invocation uses
progressive disclosure (the skill's summary loads first; detail loads
only when invoked), so the composer is never flooded with skill text.

## Marketplace (labelled honestly)

- Install with version pinning, SHA-256 verification, and a lockfile.
- Dry-run preview before install: what will be added, what it can
  touch, what it costs.
- Supply-chain scan on install (declared dependencies vs. fetched
  content).
- Per-skill evals: "Run checks on one skill and see results" is a
  first-class Library action (Playwright-covered).
- Stack-aware recommendations: the skill system suggests skills for
  the detected stack; the curated import path and the authoring
  contract are explicit, not magic.
- **Registry source is a labelled stub.** The marketplace lists
  skills from a stub registry in this build; it is labelled as such
  in the UI and is not presented as a live upstream index.

## The three approved first packs

Engineering, Science, Creative/Design (user-approved default 3).
All three install with hash verification. The Science pack is a
5-skill curated slice — explicitly labelled, not a claim to the full
177-skill science corpus.

## Engineering pipeline (Code → Engineering)

The enforced engineering workflow (spec → clarify → plan → tasks →
implement → verify → converge, with package-gated review) lives as a
Code → Engineering segment. It was orphaned by the IA swap (its old
Work container was deleted) and re-mounted by the coordinator; the
router maps `work:engineering → code/engineering` for old links.

## Skill packs vs. tabs

Skills never become destinations or tabs. A pack is installed into
the Library and invoked from the composer, the palette, or an agent
plan — never as a new sidebar entry. (This is why "import all 177
science skills or 100+ templates as tabs" is out of scope.)
