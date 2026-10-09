/**
 * Browser-like tab system (mount-once).
 *
 * - The "main" tab is the only chat. It is pinned: always open, never closable.
 * - Tool tabs open as separate tabs so they never block chat.
 * - Each tool view is mounted ONCE and hidden/shown on switch — state
 *   (running logs, results, form input) survives tab switches.
 * - The "+" picker respects feature flags.
 */
import { apiFetch } from '../../shared/http.js';

const TOOL_DEFS = {
  home:      { title: 'Home',          icon: 'fa-house',               feature: null },
  settings:  { title: 'Settings',      icon: 'fa-gear',                feature: null },
  knowledge: { title: 'Knowledge',     icon: 'fa-brain',               feature: null },
  agents:    { title: 'Agent Hub',     icon: 'fa-robot',               feature: null },
  create:    { title: 'Create',        icon: 'fa-wand-magic-sparkles', feature: null },
  library:   { title: 'Library',       icon: 'fa-book',               feature: null },
  skills:    { title: 'Skills',        icon: 'fa-wand-magic-sparkles', feature: null },
  teams:     { title: 'Agent teams',   icon: 'fa-users',               feature: 'multi_agent' },
  learn:     { title: 'Learn',         icon: 'fa-graduation-cap',      feature: 'learning' },
  analytics: { title: 'Analytics',     icon: 'fa-chart-simple',        feature: 'analytics' },
  images:    { title: 'Image studio',  icon: 'fa-image',               feature: 'image_gen' },
  code:      { title: 'Code agent',    icon: 'fa-code',                feature: null },
  design:    { title: 'Design studio', icon: 'fa-palette',             feature: null },
};

const openTabs = []; // [{ id, tool, title, icon, mounted }]
let activeTabId = 'main';
let renderers = {};
let featureCache = null;

export function registerTabRenderer(tool, fn) {
  renderers[tool] = fn;
}

function $(sel) { return document.querySelector(sel); }

async function getFeatures() {
  if (featureCache) return featureCache;
  try {
    const data = await (await apiFetch('/features')).json();
    featureCache = data.features || {};
  } catch {
    featureCache = {};
  }
  return featureCache;
}

/** Refresh the cached flags (call after a toggle in Settings). */
export function invalidateFeatureCache() { featureCache = null; }

function renderTabStrip() {
  const list = $('#toolTabList');
  if (!list) return;
  list.innerHTML = '';
  for (const t of openTabs) {
    const el = document.createElement('div');
    el.className = 'tab' + (t.id === activeTabId ? ' tab-active' : '');
    el.setAttribute('role', 'tab');
    el.setAttribute('aria-selected', t.id === activeTabId);
    el.dataset.tabId = t.id;
    el.innerHTML = `<i class="fa-solid ${t.icon}"></i><span>${t.title}</span>
      <button class="tab-close" aria-label="Close ${t.title} tab"><i class="fa-solid fa-xmark"></i></button>`;
    el.addEventListener('click', (e) => {
      if (e.target.closest('.tab-close')) {
        closeTab(t.id);
      } else {
        switchTab(t.id);
      }
    });
    list.appendChild(el);
  }
  const mainTab = $('#mainTab');
  if (mainTab) {
    mainTab.classList.toggle('tab-active', activeTabId === 'main');
    mainTab.setAttribute('aria-selected', activeTabId === 'main');
  }
}

/** Open (or focus) a tool tab. Returns the tab id. */
export function openToolTab(tool) {
  const def = TOOL_DEFS[tool];
  if (!def) return null;
  let tab = openTabs.find((t) => t.tool === tool);
  if (!tab) {
    tab = { id: `tool-${tool}`, tool, title: def.title, icon: def.icon, mounted: false };
    openTabs.push(tab);
  }
  switchTab(tab.id);
  return tab.id;
}

export function closeTab(tabId) {
  if (tabId === 'main') return;
  const i = openTabs.findIndex((t) => t.id === tabId);
  if (i >= 0) {
    // Remove the mounted container so a reopen starts fresh
    document.getElementById(`tabbody-${tabId}`)?.remove();
    openTabs.splice(i, 1);
  }
  if (activeTabId === tabId) switchTab('main');
  else renderTabStrip();
}

/** Mount the tool view once into its own persistent container. */
function mountTab(tab) {
  if (tab.mounted) return;
  const body = $('#toolViewBody');
  const container = document.createElement('div');
  container.id = `tabbody-${tab.id}`;
  container.className = 'tool-tab-body';
  container.dataset.tool = tab.tool;
  body.appendChild(container);
  const render = renderers[tab.tool];
  if (render) {
    try { render(container); } catch (err) { console.error('tab render failed', tab.tool, err); }
  } else {
    container.innerHTML = `<p class="settings-hint">Loading ${tab.title}…</p>`;
  }
  tab.mounted = true;
}

export function switchTab(tabId) {
  activeTabId = tabId;
  const isMain = tabId === 'main';
  $('#chatView')?.classList.toggle('hidden', !isMain);
  $('#toolView')?.classList.toggle('hidden', isMain);
  if (!isMain) {
    const tab = openTabs.find((t) => t.id === tabId);
    if (tab) {
      $('#toolViewTitle').innerHTML = `<i class="fa-solid ${tab.icon}"></i> ${tab.title}`;
      mountTab(tab); // mount once
      // Show this tab's container, hide the others
      document.querySelectorAll('#toolViewBody .tool-tab-body').forEach((el) => {
        el.classList.toggle('hidden', el.id !== `tabbody-${tabId}`);
      });
    }
  }
  renderTabStrip();
}

export function getActiveTabId() {
  return activeTabId;
}

export function initTabs() {
  $('#mainTab')?.addEventListener('click', () => switchTab('main'));
  $('#toolViewClose')?.addEventListener('click', () => closeTab(activeTabId));
  $('#tabAddBtn')?.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleToolPicker();
  });
  document.addEventListener('click', () => closeToolPicker());
  renderTabStrip();
}

async function toggleToolPicker() {
  closeToolPicker();
  const features = await getFeatures();
  const btn = $('#tabAddBtn');
  const menu = document.createElement('div');
  menu.id = 'toolPickerMenu';
  menu.className = 'tool-picker-menu';
  menu.innerHTML = Object.entries(TOOL_DEFS).map(([key, def]) => {
    const off = def.feature && !features[def.feature];
    return `
    <button type="button" data-tool="${key}"${off ? ' disabled' : ''} title="${off ? 'Enable in Settings → Features' : def.title}">
      <i class="fa-solid ${def.icon}"></i><span>${def.title}</span>
      ${off ? '<span class="tool-off">off</span>' : ''}
    </button>`;
  }).join('');
  menu.querySelectorAll('button:not([disabled])').forEach((b) => {
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      openToolTab(b.dataset.tool);
      closeToolPicker();
    });
  });
  const rect = btn.getBoundingClientRect();
  menu.style.position = 'fixed';
  menu.style.left = `${rect.left}px`;
  menu.style.top = `${rect.bottom + 6}px`;
  document.body.appendChild(menu);
}

function closeToolPicker() {
  document.getElementById('toolPickerMenu')?.remove();
}
