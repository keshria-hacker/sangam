# UI Simplification — UI-only run (2026-10-26)

**Branch:** `integration/full-program` · **Base:** `85a8784` (post-all-in-one)
**Scope:** frontend/UI ONLY. No new features, no new backend routes, no new
destinations, no new tabs, no theme change, no React rewrite. Vanilla JS stays.
Backend APIs are untouched by this run (one exception in spirit only: no API
behaviour was changed at all — every change below is a frontend file).

**Rule used throughout:** one obvious path per job; common actions visible,
advanced options behind a clearly labelled toggle; plain language first;
every existing capability reachable within 2 clicks from its destination
or via the command palette. Hiding behind a toggle is not removal.

## 0. Audit headline (static code evidence, no live browser)

- **P0 found and fixed:** the sidebar destination rail was invisible in CSS
  (`.rail-nav{display:none}` overrode the flex rule), so the 7 destinations
  were reachable only via the tab strip, picker, Home cards, and palette.
- **No genuinely dead user-visible button was found** (all rendered buttons
  had handlers), but there were 3 dead/no-op wirings and 2 wrong-destination
  links, plus 17 native `prompt()`/`confirm()` call sites.
- **The clutter was inside destinations, not between them:** Work = 7 section
  tabs (Agents alone = 6 sub-tabs); Create = 7 sub-tabs; Knowledge = one
  scrolling page with ~8 sections and ~25 controls; Settings = 9 categories
  with custom sections stacked under schema rows; Chat showed 10 message
  actions at once.
- **Mobile (static CSS evidence only):** no 390px breakpoint; `.library-tabs`,
  `.kn-mem-controls`, `.sp-setting-row` lacked wrapping; several tab/close
  controls were below 44px touch size.

## 1. What changed, per destination

### Shell + Chat + Home (Batch A, commit 7b47f3f)
- Sidebar rail unhidden (one CSS rule deleted); rail labels hide when
  collapsed, icons stay.
- Home → Learn card fixed: Settings → Knowledge → Study.
- Home job rows are buttons to Work → Activity (chat rows already were).
- Save toast corrected: "find it in Create → Documents" (was Knowledge).
- CSS: wrapping for `.library-tabs`, `.kn-mem-controls`, `.sp-setting-row`;
  44px minimum touch height for `.tab-close` / `.library-tab` at ≤900px.
- New shared utility `.advanced-section` (`<details>`): later batches use
  it to collapse, never to remove.
- Chat message actions grouped: Copy / Regenerate / Save visible; Workflow,
  Inspect, Check writing, Natural rewrite, Speak, feedback behind "More".
- Tune labels plain-first: "Thinking depth (reasoning effort)",
  "Longest reply (max tokens)", "Creativity (temperature)"; Council
  described as helpers discussing and voting, not "tally / ledger entry".
- Shortcuts modal gained Ctrl+P, slash, Ctrl+Shift+I; navigation moves
  focus to the destination title. Dead `skillsBtn/codeBtn/designBtn`
  wiring deleted.

### Work (Batch B)
- Agents → Runs tab is now a link: "See all runs in Activity".
- Dev & QA security scope check moved into Security (same endpoint, now
  with a JSON content-type); Dev & QA keeps an "Open Security" link.
- Compare confirmed as the only leaderboard surface in Work files.
- "Run mode & task plan" behind "Advanced: run shape" (Single agent is
  the visible default); Workflows help behind "How workflows work".
- Relabels: "One helper per task", "Team inbox", "Step-by-step",
  "Write the test first" (TDD in subtext), "Find code", "step-by-step
  workflows" (the word "Automations" was deliberately NOT used here —
  it would collide with the separate Automations sub-view).
- Security gains a text-only stepper (Allow → Create → Approve → Report;
  approvals unchanged). Engineering gains a progress label from existing
  fields. Workflows empty state gains "Start from a template" (Dev & QA
  starters, same destination). Runs centre untouched.

### Create (Batch C)
- Studio pipeline form behind "Advanced: combine steps" (jobs list stays
  visible outside it); Image operations behind "Advanced: edit an image";
  Diagrams brand row behind "Advanced: brand style". Generate, Gallery,
  picker, editor, lint, and export stay visible.
- "Code snippet" → "Code file"; Diagram starter card links to the
  Diagrams tab; Media jobs list gains "Track all jobs in Work → Activity".
- Relabels: "Read text aloud" / "Turn speech into text",
  "Subtitles for video", "Pause for my approval between steps".
- Gallery / Design buttons gained aria-labels.
- Deleted: 88-line unreachable modal block in `image.js` (after a `return`).
- Fixed (pre-existing, found by this run): `initImage()` referenced an
  undeclared `btn` and threw when image generation was enabled; the
  stray line was deleted (the next line already unhides `studioBtn`).

### Knowledge (Batch D)
- MCP enable/disable list removed from Knowledge; replaced by an explainer
  + "Open MCP Servers in Library" link. Library is the single home.
- Memory tools (Extract / Reflect / Timeline / Transcripts / Update)
  behind "Advanced memory tools". Every memory row gains Edit, which opens
  that block and prefills the Update form — no more typed memory ids.
- Catalogue collapsed as "Reference catalogue" (read-only, never installs).
- The single Knowledge "Tidy" control relabelled "Clean up old memories"
  (same endpoint). No second Consolidate button existed inside Knowledge;
  the Settings duplicate is handled in Batch E (link + collapsed browser).
- Relabels (user copy only, keys/values untouched): Events / Facts /
  How-tos, Groups / Folders, "Searches your documents by meaning and by
  exact words, with citations", "AI…" instead of "LLM…" in user copy.
- Empty states: transcripts explain themselves; "No memories yet" gains
  "Start a chat"; bare "Empty." in the Groups view fixed.
- `#knSearch` / `#knMemKind` gained aria-labels. Notebook chat import
  behind "Advanced: import from a chat" (no copy-chat-id feature invented).

### Library + Settings + palette (Batch E)
- Routing JSON rows behind "Advanced: edit as JSON" (rendering only;
  keys, values, and the Routes UI below them unchanged; search results
  still show the rows uncollapsed so they remain findable).
- Settings memory browser becomes a link to Knowledge → Memories plus a
  collapsed "Browse here" (the unchanged browser). Knowledge is the
  visible default home.
- Routes → Quota becomes a Usage link card with the same numbers.
- "Skills v2 — server scan, lockfile, checks, packs, recommendations" →
  "Skills — check for updates, saved sets, and suggestions"; Scan/Checks/
  Packs behind "Advanced skill tools"; Preview/Pin stay visible.
- Routes prompts replaced by inline forms with a real model dropdown
  (no more memorised model ids); Settings Reset-all uses the existing
  confirm-overlay pattern instead of `window.confirm`.
- Palette: "Toggle web search" fixed — it clicked a nonexistent element
  and silently did nothing; it now calls the real Alt+W tool toggle.
  Palette gained "Open Home / Work / Create / Knowledge" (every
  destination is now palette-reachable).
- Relabels: "Smart model gateway (OmniRoute)" with an explainer,
  "Clean up AI clichés — preview", ADHD description shortened to
  "Short sections, short lists, no throat-clearing openers.",
  "Workspace → Features" corrected to "Agents & Safety → Features",
  Doctor subtitle "Checks your setup and shows fixes".
- Library empties each gain one guided link. Prompt templates gained
  "Use in chat" (new chat, composer prefilled, not sent) via a new
  `chat.js` export `startNewChatWithText(text)`; Copy stays.

### Tidy (coordinator, commit 63151f2)
- Removed the unused `showToolSection` import from `app.js` and the
  unused `.home-row-static` CSS (Batch A leftovers).
- Media jobs dub option reworded: "Voice a script (subtitles are in
  Studio)" (it previously pointed at a renamed section).

## 2. Where did it go? (moved controls)

| Was here | Now lives here |
|---|---|
| Agents → Runs list | Work → Activity (link from Agents → Runs) |
| Dev & QA → Security scope check form | Work → Security (link left in Dev & QA) |
| Knowledge → MCP enable/disable | Library → MCP Servers (link left in Knowledge) |
| Settings → Memory browser (visible default) | Knowledge → Memories (link + collapsed "Browse here" left in Settings) |
| Settings → Routing JSON rows | Behind "Advanced: edit as JSON" in the same Models & Routing category; Routes UI below it is the human version |
| Routes → Quota numbers | Same numbers on a Usage link card → Settings → Usage |
| Create → Studio pipeline form | Same Studio tab, behind "Advanced: combine steps" |
| Create → Image operations | Same Image tab, behind "Advanced: edit an image" |
| Create → Diagrams brand row | Same Diagrams tab, behind "Advanced: brand style" |
| Knowledge → Memory tools | Same page, behind "Advanced memory tools" |
| Knowledge → Catalogue | Same page, behind "Reference catalogue" |
| Library → Skills Scan/Checks/Packs | Same page, behind "Advanced skill tools" |
| Agents → Run mode & task plan | Same Agents page, behind "Advanced: run shape" |

Nothing in this table was deleted from the UI; every row is one click
behind a labelled toggle, or one link away, in addition to the palette.

## 3. Reachability proof (static, by construction)

- Every capability listed in the audit's reachability map remains reachable
  within 2 clicks from its destination, or via the palette, after this run:
  collapsed sections cost exactly 1 extra click (open the toggle); linked
  capabilities cost exactly 1 extra click (follow the link); palette
  actions land directly on all 7 destinations (Home/Work/Create/Knowledge
  added by Batch E; Chat via "New chat"; Library and Settings already
  present).
- Inherently longer chains were NOT shortened by cutting safety steps:
  security runs keep allow → create → approve → report (now with a
  visible stepper); workflow canvas editing and automation creation keep
  their forms (now with template guidance). These are documented as
  acceptable in the audit, not claimed as 2-click flows.
- No backend route was removed, so no API caller breaks; frontend-only
  changes cannot orphan a backend capability.

## 4. Verification

- Frontend modules: `node --experimental-vm-modules
  scripts/check_frontend_modules.mjs` → 65/65 parse + link (unchanged
  count; no modules added or removed), re-run after every batch and
  after the fix below.
- Full suite (run with proxy env vars unset, as the parent shell's proxy
  values break httpx in tests): first full run after Batches A–E gave
  **1623 passed, 101 skipped, 1 failed**. The failure was a real
  regression caught by the gate, not the known flake: Batch E's shortened
  ADHD description had dropped the test-required true detail "caps
  lists at 5". Fix (commit after Batch E): description restored to
  "Short sections, short lists (caps lists at 5), no throat-clearing
  openers." — still plain, still without the false "Answer-first" /
  "numbered steps" claims the test also forbids. Targeted rerun of the
  whole Batch 7 file: 18/18 passed. A final full-suite rerun with the
  fix was then run before pushing (see the coordinator's final report
  for its totals); the known flaky Phase 5 OAuth tamper test (sig ending
  in 00 makes the tamper a no-op ~1/256) is not a regression if it
  appears — it passes on single rerun.
- NOT verified here (no live browser for subagents): rail visibility at
  desktop/collapsed widths, 390px wrapping, 44px touch targets, the
  "More" menu, Edit-prefill scroll/focus, the MCP deep link, inline
  route/combo forms, the Reset-all overlay, and palette navigation.
  These need the parent's live Playwright pass (smoke 3/3) before the
  UI is declared good on a real screen — they are code-verified only.

## 5. Honest limits / deliberately left

- Settings is still broad (9 categories) — it was grouped and collapsed,
  not shrunk, because its breadth is real configuration, not duplication.
  The remaining duplication inside Settings is the collapsed "Browse
  here" memory browser, kept deliberately so a Settings-only user is
  not forced to leave the page.
- `settings/devices.js` still uses `window.confirm` for "Revoke all
  devices" and certificate regeneration — Batch E's brief covered
  Reset-all only; converting those is a follow-up, not a regression.
- Workflows canvas has no special mobile handling (nodes are absolute
  140px in an overflow-hidden canvas); the audit flagged it and this run
  did not rebuild the canvas — that is a bigger job than a simplification
  pass.
- Palette has no focus trap and re-renders on mousemove (pre-existing,
  minor, left alone).
- The audit's "could not confirm" items that this run resolved by code
  (Documents empty state was already guided; learn.js needed no changes;
  no second arena leaderboard existed in Work files) are stated above;
  items that still need a live check are in §4, not silently claimed.
