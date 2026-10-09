# Design Polish — command palette + chat export

**Status:** implemented (2026-10-08) · branch `design-polish`
**Inspired by:** open-webui/open-webui (command palette, chat export),
nexu-io/open-design (UX clarity)

## What shipped

### Command palette (Ctrl/Cmd+P)
`features/palette/palette.js` — fuzzy-filtered quick launcher for everything
in the app:
- New chat, Skills browser, Settings, Switch model
- Export current chat as Markdown
- Toggle theme / web search, Copy last response, Regenerate
- Feature-gated: Agent teams, Learn mode, Usage analytics appear only when
  their backend flags are on

Keyboard: ↑↓ navigate, Enter run, Esc close. Topbar terminal button for
discoverability; welcome keyhints updated.

### Chat export (open-webui parity)
`GET /api/chats/{chat_id}/export?format=markdown` — renders the full chat
(title, model, timestamp, all messages in order) as a Markdown file
download. Authenticated, 404 on unknown chat, 400 on bad format.

## Design decisions
- Palette actions delegate to `window.sangamApp` (existing app API) and
  dynamic imports of feature modules — no duplicated logic.
- Export is server-rendered so it includes full history, not just the
  loaded viewport.

## Future (not in this pass)
- Export to JSON/HTML
- Palette: recent chats jump-to, model quick-switch inline
