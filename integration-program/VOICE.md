# Voice — Local-first TTS/STT

**Status:** implemented (2026-10-08) · branch `voice`
**Inspired by:** debpalash/VoiceStudio (fully-local ElevenLabs alternative)

## What VoiceStudio taught us

- VoiceStudio's own engine-selection doc recommends **kokoro-tts** for fast
  English TTS on CPU-only hardware (pip, ~30MB, 2× realtime) vs its own
  2.4GB diffusion backend — so Sangam defaults to the light engines and
  treats VoiceStudio as an optional remote engine.
- VoiceStudio ships an **OpenAI-compatible audio layer**
  (`POST /v1/audio/speech`, `POST /v1/audio/transcriptions`,
  `GET /v1/audio/voices`), which is the interop point: any OpenAI-compatible
  audio server (OpenAI, a running VoiceStudio backend, speaches) works as a
  Sangam voice engine with zero bespoke code.

## Architecture

```
┌─ frontend ──────────────────────────────┐
│ mic button → MediaRecorder → /voice/stt │── dictation into composer
│ Speak button → /voice/tts → <audio>     │── per-message playback
│ auto-speak toggle, voice select         │── settings (flag-gated)
│ speechSynthesis fallback                │── when no backend engine
└─────────────────────────────────────────┘
┌─ backend/voice ─────────────────────────┐
│ service.py   synthesize/transcribe/     │
│              list_voices/voice_status   │
│ engines.py   kokoro | faster-whisper |  │
│              openai-compat  (all lazy,  │
│              all optional)              │
└─────────────────────────────────────────┘
```

### Engines (`backend/voice/engines.py`)
| Engine | Direction | Install | Notes |
|---|---|---|---|
| kokoro | TTS | `pip install kokoro` (+ `espeak-ng` system pkg) | local neural, `VOICE_KOKORO_VOICE` selects voice |
| faster-whisper | STT | `pip install faster-whisper` | local, `VOICE_WHISPER_MODEL` (default `tiny`) |
| openai | TTS+STT | `VOICE_OPENAI_BASE_URL` (+ key) | OpenAI, VoiceStudio server, speaches… |

`VOICE_TTS_ENGINE` / `VOICE_STT_ENGINE` = `auto` (default) picks the first
available; `none` disables a direction. Missing packages degrade to
"engine unavailable" — the app never fails to boot.

### API (`backend/api_routes/voice_routes.py`)
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/voice/status` | engine availability report |
| GET | `/api/voice/voices` | TTS voices from the active engine |
| POST | `/api/voice/tts` | `{text, voice?}` → `audio/wav` bytes |
| POST | `/api/voice/stt` | multipart audio → `{text}` |

All routes 404 unless `FEATURE_VOICE=true`, and 503 with an actionable
message when the flag is on but no engine is installed.

### Chat integration
- TTS input is cleaned for speech (markdown/code/links stripped) and capped
  at `VOICE_MAX_TTS_CHARS` (default 2000).
- Frontend `maybeAutoSpeak()` hook fires on completed assistant messages
  when the user enables "read aloud" in Settings.

### Extension registry
Registered as `capability:voice` v1.0.0 on startup.

## Enabling it
```bash
FEATURE_VOICE=true
# local engines (optional, pick what you need):
pip install kokoro faster-whisper
# ...or point at a server instead:
VOICE_OPENAI_BASE_URL=http://localhost:8001   # e.g. VoiceStudio backend
```

## Future (not in this pass)
- Streaming TTS (chunked audio via the MEDIA_START/DELTA/END SSE events —
  the pipeline already supports it)
- Voice cloning / custom voice upload (VoiceStudio does this well; would be
  the `openai` engine against a VoiceStudio server)
- Attaching spoken replies as media on the message so they persist
- Per-chat voice profiles
