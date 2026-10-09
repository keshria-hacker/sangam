# Image Generation — Fooocus-inspired, engine-pluggable

**Status:** implemented (2026-10-08) · branch `image-gen`
**Inspired by:** lllyasviel/Fooocus ("focus on prompting and generating")

## What Fooocus taught us (and what we did about it)

- **No REST API.** Fooocus is a Gradio UI-first app; generation is a chained
  UI flow (`get_task` → `generate_clicked` → gallery) with ~40 controls —
  not reliably drivable headless. So instead of a brittle screen-scrape,
  Sangam integrates at the two honest seams:
  1. A `fooocus` engine slot using `gradio_client` against a local Fooocus
     `--listen` server, clearly marked **experimental** (reachability is
     verified; generation maps version-sensitive endpoints and fails with a
     diagnostic when they don't match).
  2. Fooocus's real portable idea — **prompt enhancement + style presets** —
     ported as pure, tested Python (`image_gen/styles.py`).
- **The reliable local path** is an OpenAI-compatible `/v1/images/generations`
  server (same pattern as the voice theme's `/v1/audio/*` interop).

## Architecture

```
┌─ frontend ───────────────────────────────────┐
│ image button → dialog (prompt/style/size)    │── POST /image/generate
│ generated image → composer chip → media_ids  │── persists on the message
│ assistant can also call the generate_image   │── tool in the agent loop
│ tool; images render via existing msg-media   │
└──────────────────────────────────────────────┘
┌─ backend/image_gen ──────────────────────────┐
│ styles.py   8 presets + enhance_prompt()     │
│ engines.py  openai (tested) | fooocus (exp.) │
│ service.py  generate_images() → saves via    │
│             media pipeline → MediaAttachment │
└──────────────────────────────────────────────┘
```

### Engines
| Engine | How | Status |
|---|---|---|
| openai | `POST {IMAGE_OPENAI_BASE_URL}/v1/images/generations` | working, tested (mocks) |
| fooocus | `gradio_client` → `FOOOCUS_URL` (default :7865) | experimental, diagnostic on mismatch |

`IMAGE_GEN_ENGINE=auto` (default) picks the first available; `none` disables.

### API (`backend/api_routes/image_routes.py`)
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/image/status` | engine availability + style presets |
| POST | `/api/image/generate` | `{prompt, style?, size?, n?}` → `{images: [MediaAttachment]}` |

404 unless `FEATURE_IMAGE_GEN=true`; 503 with an actionable message when no
engine is configured.

### Chat integration
- `generate_image` tool (built-in, flag-gated): the model calls it when the
  user asks for visuals; returns image URL + markdown to embed.
- Manual flow: composer 🎨 button → dialog → generated image attaches as a
  chip; its `media_id` rides on the message's `media_ids` (frontend now sends
  them; backend already persisted `media_json`).
- Images render through the existing `msg-media` path — no new renderer.

### Extension registry
`capability:image_gen` v1.0.0, plus `tool:generate_image` via the normal
tool projection.

## Enabling it
```bash
FEATURE_IMAGE_GEN=true
# Option A — OpenAI or any OpenAI-compatible image server:
IMAGE_OPENAI_API_KEY=sk-...
# Option B — local Fooocus (experimental driver):
#   1. run Fooocus with --listen
#   2. IMAGE_GEN_ENGINE=fooocus
```

## Future (not in this pass)
- Stabilize the Fooocus driver against a pinned Fooocus version (needs a
  live GPU instance to verify the Gradio endpoint mapping)
- Inpainting / img2img (Fooocus's strength) via reference-image upload
- Streaming partial previews during generation
- Per-chat style defaults
