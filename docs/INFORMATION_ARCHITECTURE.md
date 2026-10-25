# Sangam — Information Architecture (perfect-flow program)

## Destinations (exactly 8, in sidebar order)

Chat, Projects, Studio, Code, Research, Agents, Library, Settings.
Each is a real page with a URL; Chat is pinned and is the only chat
surface — never closed, duplicated, or nested inside another
destination. Sub-navigation inside a destination is a segmented
control at the top of that destination's content, never a second
sidebar and never a tab that opens another destination.

| Destination | URL | Contents (flattened from the old IA) |
|---|---|---|
| Chat | `/chat` | The only composer; Auto mode default |
| Projects | `/projects`, `/projects/:id` | Workspaces: instructions, sources, tasks, scoped chats |
| Studio | `/studio`, `/studio/:artifact` | Documents, design, diagrams, image, voice, classroom |
| Code | `/code`, `/code/:repo` | Code agent, Spec & QA, code graph, Engineering pipeline |
| Research | `/research`, `/research/:notebook` | Explore, notebooks, study (knowledge graph lives here) |
| Agents | `/agents`, `/agents/:id` | Hub, task board, run history, workflows, security |
| Library | `/library` | Skills, MCP, extensions, templates (segments) |
| Settings | `/settings`, `/settings/:section` | Searchable control center, 17 sections |

## Rules that replaced the old shell

- **No tab strip, no title bar.** The old `#tabStrip` / `#toolViewTitle`
  / `#tabAdd` elements are gone. The only header-like element is a
  slim contextual breadcrumb (`#destBreadcrumb`) inside the content,
  shown only at depth > 1 (detail pages, settings sections).
- **No top bar repeating the destination name.** (The pre-existing
  mobile hamburger bar is excepted: on small screens it opens the
  drawer; it is not a title bar.)
- **Legacy destinations redirect, never 404.** `home → /chat`,
  `work → /agents`, `create → /studio`, `knowledge → /research`, plus
  sub-id mappings (see `features/shell/router.js`
  `LEGACY_ID_REDIRECTS` / `LEGACY_PATH_REDIRECTS`). Unknown routes
  render a 404 page with a working "Back to Chat" action.
- **Rail clicks pushState.** A rail click navigates AND updates the
  address bar (fix 2026-10-25: `showTool()` used to fall through to
  `routeFromLocation` with `push:false` for current ids, rendering
  without changing the URL).
- **Mobile drawer closes on navigation.** Below 900px the sidebar is
  off-canvas; tapping a rail destination closes it, so the destination
  is actually visible (same rule chat-history clicks already had).
- **Empty states have exactly one guided next action.** The Runs
  centre lost its second competing CTA in this program; every
  destination was audited to the same rule.
- **Sidebar footer (bottom, always):** avatar, usage meter, palette
  hint (Ctrl/Cmd+K), help. The usage meter shows "Usage unavailable"
  before auth by design — never an invented number.

## Router

`mainfiles/frontend/js/features/shell/router.js` is the pure source of
truth (destinations, URL shapes, legacy redirects, breadcrumb text);
`features/tabs/tabs.js` consumes it and preserves the old tab API
(`showTool`, `showToolSection`, `showToolSub`, `openToolTab`,
`switchTab`) as navigation calls, so old palette actions, slash
commands, and specs keep resolving. `features/shell/destinations.js`
renders each destination; `features/shell/router.js` + `tabs.js` are
covered by `tests/e2e/shell.spec.ts` (5 tests: destinations, no
strip/title bar, redirects/404/breadcrumb, palette reach, two-click
reachability + empty states, first-run).

## Command palette (Ctrl/Cmd+K, Ctrl+P alias)

Indexes destinations, all 17 settings sections, installed skills,
saved prompts, models, and conversations. Running a prompt from the
palette pre-fills the composer — it never auto-sends. Create actions
land on the right segment (e.g. "New artifact" →
`/studio?section=create`). The palette initialises before the
provider/model probe, so Ctrl+K works while models are still loading;
it reads the model list lazily at open time.

## First-run (3 steps max, skippable)

1. Cloud key → live test → green check → suggested model
   pre-selected, or Ollama → detect → model list → first model
   pre-selected.
2. Look-around → a clearly labelled SAMPLE panel, never a fake reply.
3. Guided prompt "What do you want to get done today?" → Auto answers.
   (Chat cannot answer before a provider is ready; the look-around
   path says so honestly instead of faking a response.)

## Settings control center

See `SETTINGS.md`. Every setting that exists anywhere in the codebase
is discoverable there: 17 sections, searchable by name + description,
every row with label, description, default, current value, reset, and
a requires-restart marker where applicable. `.env`-only options (base
URLs, `REDIS_URL`, `SANGAM_*` roots, `MASTER_KEY`) are listed
read-only in Settings → Advanced with live equivalents linked — wiring
them for real needs a backend settings-read path first (recorded,
not faked).
