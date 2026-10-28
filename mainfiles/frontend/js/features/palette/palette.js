/**
 * Command palette (Ctrl/Cmd+P) — quick actions for everything in the app.
 *
 * open-webui-style quick launcher: fuzzy-filtered list of actions covering
 * chat, skills, teams, learn, analytics, settings, and export. Feature-gated
 * actions appear only when their backend flag is on.
 */

import { apiFetch } from '../../shared/http.js';
import { escapeHtml } from '../../shared/utils.js';
import { getActiveChatId } from '../../core/state.js';
console.log('[Module] palette.js loaded');

let flags = {};
let paletteEl = null;
let selectedIndex = 0;
let visibleActions = [];
let focusBeforePalette = null;

function app() {
  return window.sangamApp || {};
}

async function loadFlags() {
  try {
    const data = await (await apiFetch('/features')).json();
    flags = (data && data.features) || {};
  } catch {
    flags = {};
  }
}

function buildActions() {
  const a = app();
  const actions = [
    { id: 'new-chat', label: 'New chat', hint: 'Ctrl+K', run: () => a.startNewChat?.() },
    { id: 'skills', label: 'Open Library', run: () => a.openSkillsTab?.() },
    { id: 'settings', label: 'Open Settings', hint: 'Ctrl+,', run: () => a.openSettings?.() },
    { id: 'models', label: 'Switch model', hint: 'Ctrl+M', run: () => a.openModelDropdown?.() },
    {
      id: 'export', label: 'Export current chat as Markdown', run: () => exportChat(),
    },
    { id: 'theme', label: 'Toggle theme', hint: 'Ctrl+Shift+T', run: () => toggleTheme() },
    { id: 'websearch', label: 'Toggle web search', hint: 'Alt+W', run: () => toggleWebSearch() },
    { id: 'copy', label: 'Copy last response', hint: 'Ctrl+Shift+C', run: () => copyLast() },
    { id: 'regen', label: 'Regenerate last response', hint: 'Ctrl+Shift+R', run: () => a.regenerate?.() },
  ];
  // UI-simplify: every destination is palette-reachable. Chat is already
  // covered by "New chat"; these land on the destination itself, not a
  // section inside it. No existing action is removed.
  actions.push(
    { id: 'home', label: 'Open Home', run: () => import('../tabs/tabs.js').then((m) => m.showTool('home')) },
    { id: 'work', label: 'Open Work', run: () => import('../tabs/tabs.js').then((m) => m.showTool('work')) },
    { id: 'create', label: 'Open Create', run: () => import('../tabs/tabs.js').then((m) => m.showTool('create')) },
    { id: 'knowledge', label: 'Open Knowledge', run: () => import('../tabs/tabs.js').then((m) => m.showTool('knowledge')) },
  );
  actions.push({
    id: 'teams', label: 'Open Agent teams',
    run: () => import('../tabs/tabs.js').then((m) => m.showToolSub('agents', 'data-agentsub', 'teams')),
  });
  actions.push({
    id: 'compare', label: 'Compare models',
    run: () => import('../tabs/tabs.js').then((m) => m.showToolSub('agents', 'data-agentsub', 'compare')),
  });
  actions.push({
    id: 'runs', label: 'Open Activity feed',
    run: () => import('../tabs/tabs.js').then((m) => m.showToolSection('work', 'activity')),
  });
  if (flags.learning) {
    // Batch 1: this used to open the bare Settings landing page. Learn now
    // lives as the Study section inside Knowledge — go there for real.
    actions.push({
      id: 'learn', label: 'Open Learn mode',
      run: () => import('../tabs/tabs.js').then((m) => { m.showToolSection('knowledge', 'study'); }),
    });
  }
  if (flags.analytics) {
    // Batch 1: Usage now renders as its own section in Settings > Agents &
    // Safety instead of landing the user on the Settings front page.
    actions.push({
      id: 'usage', label: 'Open Usage analytics',
      run: () => import('../tabs/tabs.js').then((m) => { m.showToolSection('settings', 'usage'); }),
    });
  }
  return actions;
}

async function exportChat() {
  const chatId = getActiveChatId();
  if (!chatId) {
    app().showToast?.({ type: 'info', title: 'No active chat to export' });
    return;
  }
  try {
    const res = await apiFetch(`/chats/${encodeURIComponent(chatId)}/export?format=markdown`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'chat-export.md';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    app().showToast?.({ type: 'success', title: 'Chat exported' });
  } catch (err) {
    app().showToast?.({ type: 'error', title: 'Export failed', message: err?.message || String(err) });
  }
}

function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur === 'dark' ? 'light' : 'dark';
  import('../../shared/settings_store.js').then((m) => {
    m.setSetting('theme', next); // appearance re-applies via settings-changed
  });
}

async function toggleWebSearch() {
  // UI-simplify fix: the old code clicked #webSearchToggle, which does
  // not exist, so the action silently did nothing. Use the same
  // setToolEnabled('web_search', …) path as the app.js Alt+W handler,
  // which also persists the setting and fires sangam:tools-changed.
  const { isToolEnabled, setToolEnabled } = await import('../composer/popovers.js');
  const on = !isToolEnabled('web_search');
  setToolEnabled('web_search', on);
  app().showToast?.({ type: 'info', title: on ? 'Web search on' : 'Web search off' });
}

function copyLast() {
  const msgs = app().getMessages?.() || [];
  const last = msgs.slice().reverse().find((m) => m.role === 'assistant');
  if (last?.content) {
    navigator.clipboard.writeText(last.content).then(() => {
      app().showToast?.({ type: 'success', message: 'Last response copied.' });
    });
  }
}

function ensurePalette() {
  if (paletteEl) return paletteEl;
  paletteEl = document.createElement('div');
  paletteEl.id = 'paletteOverlay';
  paletteEl.className = 'modal-overlay hidden';
  paletteEl.innerHTML = `
    <div class="modal palette-modal" role="dialog" aria-modal="true" aria-label="Command palette">
      <div class="palette-input-wrap">
        <i class="fa-solid fa-terminal"></i>
        <input id="paletteInput" placeholder="Type a command…" autocomplete="off" aria-label="Command search">
      </div>
      <div class="palette-list" id="paletteList" role="listbox"></div>
      <div class="palette-hint"><kbd>↑↓</kbd> navigate · <kbd>↵</kbd> run · <kbd>esc</kbd> close</div>
    </div>`;
  document.body.appendChild(paletteEl);
  const input = paletteEl.querySelector('#paletteInput');
  input.addEventListener('input', () => renderList(input.value));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); moveSelection(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); moveSelection(-1); }
    else if (e.key === 'Enter') { e.preventDefault(); runSelected(); }
  });
  paletteEl.addEventListener('click', (e) => { if (e.target === paletteEl) closePalette(true); });
  // Focus trap: Tab/Shift+Tab cycle only within the palette while it is
  // open (input + currently rendered action buttons, queried live because
  // the list re-renders on filter/mousemove). Without this, Tab walked
  // out into the page behind the modal.
  paletteEl.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    const focusable = Array.from(paletteEl.querySelectorAll(
      'input:not([disabled]), button:not([disabled])')).filter((el) => el.offsetParent !== null || el === document.activeElement);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  });
  return paletteEl;
}

function matches(action, query) {
  return action.label.toLowerCase().includes(query.toLowerCase());
}

function renderList(query = '') {
  const list = paletteEl.querySelector('#paletteList');
  const q = query.trim();
  visibleActions = buildActions().filter((a) => !q || matches(a, q));
  selectedIndex = Math.min(selectedIndex, Math.max(0, visibleActions.length - 1));
  if (!visibleActions.length) {
    list.innerHTML = '<div class="palette-empty">No matching commands.</div>';
    return;
  }
  list.innerHTML = visibleActions.map((a, i) => `
    <button class="palette-item${i === selectedIndex ? ' selected' : ''}" type="button"
            data-idx="${i}" role="option" aria-selected="${i === selectedIndex}">
      <span>${escapeHtml(a.label)}</span>
      ${a.hint ? `<kbd>${escapeHtml(a.hint)}</kbd>` : ''}
    </button>`).join('');
  list.querySelectorAll('.palette-item').forEach((btn) => {
    btn.addEventListener('click', () => { selectedIndex = Number(btn.dataset.idx); runSelected(); });
    btn.addEventListener('mousemove', () => {
      if (selectedIndex !== Number(btn.dataset.idx)) {
        selectedIndex = Number(btn.dataset.idx);
        renderList(paletteEl.querySelector('#paletteInput').value);
      }
    });
  });
}

function moveSelection(delta) {
  if (!visibleActions.length) return;
  selectedIndex = (selectedIndex + delta + visibleActions.length) % visibleActions.length;
  renderList(paletteEl.querySelector('#paletteInput').value);
  paletteEl.querySelector('.palette-item.selected')?.scrollIntoView({ block: 'nearest' });
}

function runSelected() {
  const action = visibleActions[selectedIndex];
  closePalette();
  if (action) {
    try {
      action.run();
    } catch (err) {
      app().showToast?.({ type: 'error', title: 'Command failed', message: err?.message || String(err) });
    }
  }
}

export async function openPalette() {
  ensurePalette();
  await loadFlags();
  focusBeforePalette = document.activeElement;
  paletteEl.classList.remove('hidden');
  selectedIndex = 0;
  const input = paletteEl.querySelector('#paletteInput');
  input.value = '';
  renderList('');
  setTimeout(() => input.focus(), 0);
}

export function closePalette(restoreFocus = false) {
  paletteEl?.classList.add('hidden');
  // Return focus to where it was before the palette opened, but only for
  // dismissals (Escape/backdrop). Running an action keeps its own focus
  // target, so runSelected() closes without restoring.
  if (restoreFocus && focusBeforePalette && focusBeforePalette.isConnected) {
    focusBeforePalette.focus();
  }
  focusBeforePalette = null;
}

export function isPaletteOpen() {
  return !!paletteEl && !paletteEl.classList.contains('hidden');
}

export async function initPalette() {
  await loadFlags();
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'p') {
      e.preventDefault();
      isPaletteOpen() ? closePalette() : openPalette();
    } else if (e.key === 'Escape' && isPaletteOpen()) {
      closePalette(true);
    }
  });
  // Phase 8 B5: the topbar terminal button is removed (redundant with Ctrl+P).
  // The palette stays available via Ctrl+P / Cmd+P.
}
