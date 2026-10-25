# Sangam — Information Architecture (perfect-flow program, tabs-on-top correction 2026-10-25)

## Destinations (exactly 8, as tabs on top)

Chat, Projects, Studio, Code, Research, Agents, Library, Settings.
Each is a real page with a URL; Chat is pinned first in the tab bar
and is the only chat surface — never closed, duplicated, or nested
inside another destination. Every other destination opens as a
switchable, closable tab in the bar at the top of the app: opening a
destination that already has a tab focuses it instead of duplicating
it, and closing the active tab falls back to the most recently used
remaining tab (else Chat), so closing can never blank the screen.
Each tab remembers the param/section/URL it was last left at, so
switching back restores where the user was. Sub-navigation inside a
destination is a segmented control at the top of that destination's
content, never a second sidebar. There is NO sidebar and NO sidebar
destination button: the old sidebar's bottom items live in compact
form at the right of the tab bar (New chat, usage meter, avatar
menu, palette hint as plain text, not a button). Chat history is
reached through the command palette, not a sidebar list.

> **Reversal note (2026-10-25):** the perfect-flow spec said "no
> destination opens another destination as a tab", which contradicted
> the user's standing vision (Chat pinned as the only chat, everything
> else as separate tool tabs). That line was followed without flagging
> the contradiction, and the visible tab bar was replaced by sidebar
> destination buttons. The user corrected this on 2026-10-25: tabs on
> top, sidebar buttons removed. This document, the shell section of
> `ARCHITECTURE.md`, and `FIX_LOG.md` now describe the corrected
> navigation. See `tests/e2e/tabs.spec.ts` for the behavioural proof.

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

- **Tabs on top, no title bar.** The tab bar (`#tabBar`) is the only
  header-like element besides a slim contextual breadcrumb
  (`#destBreadcrumb`) inside the content, shown only at depth > 1
  (detail pages, settings sections). The old `#toolViewTitle` element
  is gone, and the old sidebar rail (`.rail-item`, `#sidebar`) is
  gone with the sidebar itself.
- **Tab clicks pushState.** A tab click navigates AND updates the
  address bar (fix 2026-10-25: `showTool()` used to fall through to
  `routeFromLocation` with `push:false` for current ids, rendering
  without changing the URL). Browser back/forward moves between tabs,
  and a deep link opens (or focuses) the right tab on load.
- **Tab overflow scrolls, never wraps.** With many tabs open the bar
  scrolls horizontally; the page itself never gains horizontal scroll.
- **No mobile drawer.** There is no hamburger menu and no off-canvas
  sidebar on small screens: the tab bar is the only navigation on
  mobile too, and nothing can linger over content after a tap.
- **Legacy destinations redirect, never 404.** `home → /chat`,
  `work → /agents`, `create → /studio`, `knowledge → /research`, plus
  sub-id mappings (see `features/shell/router.js`
  `LEGACY_ID_REDIRECTS` / `LEGACY_PATH_REDIRECTS`). Unknown routes
  render a 404 page with a working "Back to Chat" action.
- **Empty states have exactly one guided next action.** The Runs
  centre lost its second competing CTA in this program; every
  destination was audited to the same rule.
- **Tab bar right side (compact, always):** New chat, palette hint as
  plain text (Ctrl/Cmd+K — the keybinding is bound by the palette
  module, not a button), usage meter, avatar menu. The usage meter
  shows "Usage unavailable" before auth by design — never an invented
  number.

## Router

`mainfiles/frontend/js/features/shell/router.js` is the pure source of
truth (destinations, URL shapes, legacy redirects, breadcrumb text);
`features/tabs/tabs.js` consumes it and implements the tab bar (tab
state, most-recently-used fallback, per-tab param/section memory) while
preserving the old tab API (`showTool`, `showToolSection`,
`showToolSub`, `openToolTab`, `switchTab`, `closeTab`), so old palette
actions, slash commands, and specs keep resolving. The old rail module
(`core/nav.js`) was deleted with the sidebar. `features/shell/
destinations.js` renders each destination; `features/shell/router.js`
+ `tabs.js` are covered by `tests/e2e/shell.spec.ts` (destinations as
tabs, no sidebar/title bar, redirects/404/breadcrumb, palette reach,
two-click reachability + empty states, first-run) and by
`tests/e2e/tabs.spec.ts` (behavioural tab proof: palette open, switch
changes URL, close falls back to MRU, back/forward, deep link, mobile).

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
