# DESIGN.md — Sangam Design Systems

**Date:** 2026-10-09
**Status:** Living document

## Design Tokens

### Colors
- `--bg`: Main background (dark: #121315, light: #ffffff)
- `--surface`: Card/panel background
- `--bg-elevated`: Hover/focus states
- `--text`: Primary text
- `--text-secondary`: Secondary text
- `--text-tertiary`: Muted text
- `--border`: Borders
- `--border-soft`: Subtle borders
- `--accent`: Primary accent (blue)
- `--danger`: Error states (uses `--danger-rgb` for alpha)
- `--focus-ring`: Focus outline (2px, consistent)

### Typography
- Font scale: 9px to 24px (whole numbers only)
- `--font-mono`: Monospace for code
- System font stack for UI

### Spacing & Radii
- Radii: 6px (sm), 8px (md), 12px (lg), 999px (pill)
- Consistent 8px grid

## Components

### Buttons
- `.btn-primary`: Primary action (theme-aware text)
- `.btn-secondary`: Secondary action
- `.btn-sm`: Small variant
- `.icon-btn`: Icon-only button (must have `aria-label`)

### Cards
- `.hub-card`: Standard card with hover
- `.hub-card-head`: Card header with icon + title

### Forms
- `.switch`: Toggle switch (checkbox + track + thumb)
- `.provider-key-input`: API key input with show/hide
- `.popover-check`: Checkbox in popover

### Modals
- `.modal`: Standard modal system
- Focus trap required (see `js/shared/focus_trap.js`)
- `aria-modal="true"`, Escape to close

### Navigation
- `.rail-item`: Sidebar nav item (icon + label)
- `.rail-off`: Disabled state (shows "Turn on")
- `data-nav`: Navigation identifier

### Tabs
- `role="tablist"`, `role="tab"`, `aria-selected`
- Arrow keys: navigate, Home/End: jump, Enter/Space: activate
- Roving tabindex pattern

## Accessibility
- All icon buttons have `aria-label`
- `:focus-visible` shows 2px outline
- Skip-to-content link at top
- Contrast: WCAG AA (4.5:1 minimum) in both themes
- Modals trap focus, restore on close

## Studios

### Image Studio
- Entry: Create Hub → "Image studio" template
- Features: Style presets, prompt enhancement, gallery
- Backend: `/api/image/*` (FEATURE_IMAGE_GEN)

### Voice Studio
- Entry: Create Hub → "Voice studio" template
- Features: TTS, STT, mic dictation
- Backend: `/api/voice/*` (FEATURE_VOICE)

## Layout
- Intent-grouped rail: Home, Chat, Agents, Knowledge, Create, Code, Learn, Library, Insights, Settings
- Main chat is pinned (never closes)
- Tool tabs for side-by-side work
- Right Inspector panel (Ctrl+Shift+I)
- Activity Tray for background jobs
