# Analytics — opt-in local-first usage analytics

**Status:** implemented (2026-10-08) · branch `analytics`
**Inspired by:** Openpanel-dev/openpanel (privacy-friendly product analytics)

## Architecture

```
backend/analytics/
  events.py   record_event(db, user_id, type, props) — silent no-op unless
              FEATURE_ANALYTICS; optional_user_id(request, db) best-effort
              identity (never raises)
  stats.py    get_stats(db, user_id, days) — per-day counts, by-type
              breakdown, top models. Aggregates only; raw events never
              leave the backend.
  __init__.py register_analytics_extension() -> capability:analytics
models.py     AnalyticsEvent table (user FK cascade, JSON properties)
```

### Privacy design
- **Opt-in**: `FEATURE_ANALYTICS=false` by default; when off, nothing is
  recorded and `/api/analytics/stats` 404s.
- **Local only**: events stay in the server's SQLite DB — no third party,
  no telemetry exfiltration (unlike OpenPanel's cloud, this is the
  self-hosted subset).
- **No content**: only event types + tiny properties (model name, team id).
  Message content and prompts are never stored.

### Recorded events
`message_sent` (chat), `team_run`, `lesson_started`, `image_generated`,
`voice_tts`, `voice_stt`, `pack_enabled`. Each hook is wrapped so analytics
can never break the product flow.

### Frontend
`features/analytics/analytics.js` — Usage button (topbar, hidden unless the
`analytics` flag is on) opens a dashboard: total events, per-day CSS bar
chart, by-type and top-model breakdowns, 7/14/30-day ranges.

## Future (not in this pass)
- Retention pruning (e.g. auto-delete events older than N days)
- Export/delete-my-data (GDPR-style)
- Admin-wide aggregates (currently per-user only)
