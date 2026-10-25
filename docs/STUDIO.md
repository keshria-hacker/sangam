# Sangam — Studio (perfect-flow program)

Studio (`/studio`) covers documents, design, diagrams, image, voice,
and classroom. It does NOT cover video production (user-confirmed
skip) or voice cloning (user-confirmed skip).

## Documents

Generate docx / pdf / pptx / xlsx, and parse them back — document
proof is a round-trip, not a "file created" toast. Generation goes
through the session-backed endpoint (Playwright-covered: docx bytes
start with the `PK` zip signature).

## Design & diagrams

- Diagram catalogue: exactly 44 types, with SVG/HTML export. PNG
  export returns 422: there is no raster renderer in this build, and
  the failure is reported, not faked with an SVG renamed to .png.
- Diagram IR: diagrams are built from an intermediate representation
  (note-graph + diagram IR), linted ("Run lint" is a first-class
  action), then exported.
- Image ops: Vary / Upscale / Inpaint / Outpaint / Describe controls
  (Playwright-covered). No real image bytes were generated in the
  coordinator's environment (engines absent); the catalogue reports
  engine status honestly instead of synthesising output.

## Voice

TTS / STT / dub / dictation only. Voice cloning is skipped (see
`DECISIONS.md`). The classroom generator produces slides grounded in
source, a quiz, interactive HTML, and PBL — no MP4.

## Classroom templates

Slides grounded in the source material (not generic filler), quiz
generation, interactive HTML export, project-based learning
scaffolds. Lesson-player TTS is not wired (carried limit).

## Artifacts

Studio output lands in the ArtifactStore (defined and tested in
Phase 0; media/files routes were not yet migrated at that time —
see `FIX_LOG.md`). Artifacts are listed in the Runs centre and in
Library, with pruning for stale artifacts ("Delete stale artifacts"
is a real control with a day-count input, Playwright-visible).
