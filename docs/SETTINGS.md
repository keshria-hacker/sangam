# Sangam — Settings Control Center (perfect-flow program)

## Shape

Settings (`/settings`, `/settings/:section`) is a searchable,
sectioned control center with a left sub-nav (`.sp-cat[data-cat]`
buttons). Search matches names + descriptions. Every row carries a
label, description, default, current value, reset-to-default, and a
requires-restart marker where applicable. No setting that exists
anywhere in the codebase is orphaned: if it can be set, it is
discoverable here.

## The 17 sections

General, Appearance, Chat & Responses, Models & Providers, Tools,
Memory & Knowledge, Projects & Context, Agents & Automation, Skills &
Library, Connectors & MCP, Voice & Audio, Image & Video, Security,
Data & Privacy, Appearance of code, Advanced, About.

Legacy section ids redirect: `knowledge → memory`,
`research → tools`, `voice_output → voice`, `devices → security`
(`LEGACY_SETTING_SECTIONS` in `settings_schema.js`). The Devices
section (LAN pairing, QR, paired devices, certificate, threat model)
lives inside Security, not as its own category.

## Appearance tokens, live

Settings → Appearance edits the design tokens (color / type /
spacing / radius / motion / density) and they apply live — every
component consumes tokens, so there is no second theme system to
drift. (A stale `.rail-nav{display:none}` rule from the 2026-10-11
sidebar compaction hid the whole rail until this program removed it;
tokens did not cause that, a hardcoded override did.)

## `.env`-only options (read-only, not faked)

`MASTER_KEY` (secret, never shown) and backend `.env`-only options
(base URLs, `REDIS_URL`, `SANGAM_*` roots, etc.) are listed read-only
in Settings → Advanced with live equivalents linked. Wiring them for
real edits needs a backend settings-read path first; until then they
are visible but not editable in the UI, and the UI says so. Keys may
also be set via `.env`, but anything settable must be visible and
testable in the UI.

## Notable rows

- `LAN_ENABLED` ("Allow devices on my Wi-Fi") — Security, with the
  threat model ("What this protects" / "NOT protected") beside it.
- Telemetry — default OFF (user-approved default 6).
- No-slop cleanup + De-slop preview — Voice & Audio (Detect audits
  without rewriting; Edit rewrites flagged clichés only).
- Model Fit + Doctor — Models & Providers (hardware summary, ranked
  recommendations, live provider status).
- Data & Privacy — memory dashboard, export (memories-JSON only),
  per-memory delete.
