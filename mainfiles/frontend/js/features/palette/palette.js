/**
 * Command palette (Ctrl/Cmd+K, Ctrl+P alias) — A1 perfect-flow shell (§3.3).
 *
 * The discoverability layer: it reaches every destination, every
 * settings section, every installed skill, and every saved prompt, plus
 * new chat/project/artifact, switch model, toggle Auto, install a
 * skill, open a settings section, run a saved prompt, and search
 * conversations. The searchable index itself is the pure module in
 * shell/palette_index.js (unit-tested from Node); this file only
 * builds it from live data and runs the chosen action.
 *
 * "Run a saved prompt" prefills the composer with the prompt body and
 * focuses it — it never auto-sends, so the user edits first (the same
 * contract as the slash-command starters).
 */

import { apiFetch } from '../../shared/http.js';
import { escapeHtml } from '../../shared/utils.js';
import { getActiveChatId, getChats, getModels } from '../../core/state.js';
import { DESTINATIONS } from '../shell/router.js';
import { buildPaletteIndex, searchPaletteIndex } from '../shell/palette_index.js';
import { SETTING_CATEGORIES } from '../../shared/settings_schema.js';
import { PROMPT_TEMPLATES } from '../library/library.js';

console.log('[Module] palette.js loaded');

let paletteEl = null;
let selectedIndex = 0;
let visibleActions = [];

function app() {
  return window.sangamApp || {};
}

async function loadSkills() {
  try {
    const data = await (await apiFetch('/extensions')).json();
    const exts = data.extensions || [];
    return exts.filter((e) => e.kind === 'skill').map((e) => ({ name: e.name }));
  } catch {
    return [];
  }
}

async function buildIndex() {
  const skills = await loadSkills();
  const models = (getModels() || []).map((m) => ({ id: m.id, label: m.name || m.id }));
  const chats = (getChats() || []).map((c) => ({ id: c.id, title: c.title }));
  return buildPaletteIndex({
    destinations: DESTINATIONS,
    settingsSections: SETTING_CATEGORIES,
    skills,
    prompts: PROMPT_TEMPLATES,
    models,
    chats,
  });
}

async function runAction(action) {
  const a = app();
  switch (action.type) {
    case 'navigate': {
      const { navigate } = await import('../tabs/tabs.js');
      navigate(action.dest, { section: action.section || null });
      return;
    }
    case 'settings': {
      const { navigate } = await import('../tabs/tabs.js');
      navigate('settings', { section: action.section });
      return;
    }
    case 'new-chat':
      a.startNewChat?.();
      {
        const { navigate } = await import('../tabs/tabs.js');
        navigate('chat');
      }
      return;
    case 'new-project': {
      const { navigate } = await import('../tabs/tabs.js');
      navigate('projects');
      setTimeout(() => document.getElementById('pjName')?.focus(), 300);
      return;
    }
    case 'new-artifact': {
      const { navigate } = await import('../tabs/tabs.js');
      navigate('studio', { section: 'create' });
      return;
    }
    case 'switch-model': {
      const model = (getModels() || []).find((m) => m.id === action.modelId);
      if (model) a.selectModel?.(model);
      else a.openModelDropdown?.();
      return;
    }
    case 'toggle-auto': {
      const store = await import('../../shared/settings_store.js');
      const pop = await import('../composer/popovers.js');
      const cur = store.getSetting('composerMode');
      const next = cur === 'auto' ? 'answer' : 'auto';
      pop.setMode(next);
      store.setSetting('composerMode', next);
      a.showToast?.({ type: 'info', title: next === 'auto' ? 'Auto mode on' : 'Auto mode off (Answer only)' });
      return;
    }
    case 'install-skill': {
      const { navigate } = await import('../tabs/tabs.js');
      navigate('library', { section: 'skills' });
      return;
    }
    case 'run-prompt': {
      const { navigate } = await import('../tabs/tabs.js');
      navigate('chat');
      const ta = document.getElementById('messageInput');
      if (ta) {
        ta.value = action.body || '';
        ta.focus();
      }
      return;
    }
    case 'open-chat': {
      const { navigate } = await import('../tabs/tabs.js');
      navigate('chat');
      const { openChat } = await import('../sidebar/sidebar.js');
      await openChat(action.chatId);
      return;
    }
    case 'command':
      if (action.command === 'theme') toggleTheme();
      else if (action.command === 'websearch') await toggleWebSearch();
      else if (action.command === 'export') await exportChat();
      else if (action.command === 'copy') copyLast();
      else if (action.command === 'regen') a.regenerate?.();
      return;
    default:
      return;
  }
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
        <input id="paletteInput" placeholder="Go to, run, switch, search…" autocomplete="off" aria-label="Command search">
      </div>
      <div class="palette-list" id="paletteList" role="listbox"></div>
      <div class="palette-hint"><kbd>↑↓</kbd> navigate · <kbd>↵</kbd> run · <kbd>esc</kbd> close · <kbd>Ctrl/Cmd+K</kbd> open</div>
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

let fullIndex = [];

function renderList(query = '') {
  const list = paletteEl.querySelector('#paletteList');
  const q = query.trim();
  visibleActions = searchPaletteIndex(fullIndex, q);
  selectedIndex = Math.min(selectedIndex, Math.max(0, visibleActions.length - 1));
  if (!visibleActions.length) {
    list.innerHTML = '<div class="palette-empty">No matching commands.</div>';
    return;
  }
  list.innerHTML = visibleActions.map((a, i) => `
    <button class="palette-item${i === selectedIndex ? ' selected' : ''}" type="button"
            data-idx="${i}" role="option" aria-selected="${i === selectedIndex}">
      <span>${escapeHtml(a.label)}</span>
      <span class="palette-group">${escapeHtml(a.group)}</span>
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
    runAction(action.action).catch((err) => {
      app().showToast?.({ type: 'error', title: 'Command failed', message: err?.message || String(err) });
    });
  }
}

export async function openPalette() {
  ensurePalette();
  fullIndex = await buildIndex();
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
  document.addEventListener('keydown', (e) => {
    // Ctrl/Cmd+K is the palette (spec §3.3); Ctrl+P stays as an alias.
    // app.js no longer binds Ctrl+K to New chat, so there is no double action.
    if ((e.ctrlKey || e.metaKey) && (e.key.toLowerCase() === 'k' || e.key.toLowerCase() === 'p')) {
      // Palette from anywhere, including the composer: Ctrl+K has no
      // text-editing meaning in this app, so it always toggles.
      e.preventDefault();
      isPaletteOpen() ? closePalette() : openPalette();
    } else if (e.key === 'Escape' && isPaletteOpen()) {
      closePalette();
    }
  });
}
