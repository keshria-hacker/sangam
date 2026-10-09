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
    { id: 'skills', label: 'Open Skills browser', run: () => a.openSkillsTab?.() },
    { id: 'settings', label: 'Open Settings', hint: 'Ctrl+,', run: () => a.openSettings?.() },
    { id: 'models', label: 'Switch model', hint: 'Ctrl+M', run: () => a.openModelDropdown?.() },
    {
      id: 'export', label: 'Export current chat as Markdown', run: () => exportChat(),
    },
    { id: 'theme', label: 'Toggle theme', hint: 'Ctrl+Shift+T', run: () => toggleTheme() },
    { id: 'websearch', label: 'Toggle web search', hint: 'Ctrl+Shift+W', run: () => toggleWebSearch() },
    { id: 'copy', label: 'Copy last response', hint: 'Ctrl+Shift+C', run: () => copyLast() },
    { id: 'regen', label: 'Regenerate last response', hint: 'Ctrl+Shift+R', run: () => a.regenerate?.() },
  ];
  if (flags.multi_agent) {
    actions.push({
      id: 'teams', label: 'Open Agent teams',
      run: () => import('../teams/teams.js').then((m) => m.openTeamsModal()),
    });
  }
  if (flags.learning) {
    actions.push({
      id: 'learn', label: 'Open Learn mode',
      run: () => import('../learn/learn.js').then((m) => m.openLearnModal()),
    });
  }
  if (flags.analytics) {
    actions.push({
      id: 'usage', label: 'Open Usage analytics',
      run: () => import('../analytics/analytics.js').then((m) => m.openAnalyticsModal()),
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
  import('../../core/state.js').then((m) => {
    m.setSettings({ ...m.getSettings(), theme: next });
    app().applySettings?.();
  });
}

function toggleWebSearch() {
  document.getElementById('webSearchToggle')?.click();
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
  paletteEl.addEventListener('click', (e) => { if (e.target === paletteEl) closePalette(); });
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
  paletteEl.classList.remove('hidden');
  selectedIndex = 0;
  const input = paletteEl.querySelector('#paletteInput');
  input.value = '';
  renderList('');
  setTimeout(() => input.focus(), 0);
}

export function closePalette() {
  paletteEl?.classList.add('hidden');
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
      closePalette();
    }
  });
  // Also add a topbar button for discoverability.
  const btn = document.getElementById('paletteBtn');
  if (btn) {
    btn.classList.remove('hidden');
    btn.addEventListener('click', openPalette);
  }
}
