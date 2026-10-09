/**
 * Browser-like tab system.
 *
 * - The "main" tab is the only chat. It is pinned: always open, never closable.
 * - Tool tabs (skills, teams, learn, analytics, images) open as separate tabs
 *   so they never block or cover the chat view.
 * - Opening a tool that is already open just switches to its tab.
 */

const TOOL_DEFS = {
  skills:    { title: 'Skills',    icon: 'fa-wand-magic-sparkles' },
  teams:     { title: 'Agent teams', icon: 'fa-users' },
  learn:     { title: 'Learn',      icon: 'fa-graduation-cap' },
  analytics: { title: 'Analytics',  icon: 'fa-chart-simple' },
  images:    { title: 'Image studio', icon: 'fa-image' },
  code:      { title: 'Code agent', icon: 'fa-code' },
  design:    { title: 'Design studio', icon: 'fa-palette' },
};

const openTabs = []; // [{ id, tool, title, icon }]
let activeTabId = 'main';
let renderers = {}; // tool -> (bodyEl) => void, registered by feature modules

export function registerTabRenderer(tool, fn) {
  renderers[tool] = fn;
}

function $(sel) { return document.querySelector(sel); }

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
    tab = { id: `tool-${tool}`, tool, title: def.title, icon: def.icon };
    openTabs.push(tab);
  }
  switchTab(tab.id);
  return tab.id;
}

export function closeTab(tabId) {
  if (tabId === 'main') return; // main tab never closes
  const i = openTabs.findIndex((t) => t.id === tabId);
  if (i >= 0) openTabs.splice(i, 1);
  if (activeTabId === tabId) switchTab('main');
  else renderTabStrip();
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
      const body = $('#toolViewBody');
      body.innerHTML = '';
      const render = renderers[tab.tool];
      if (render) {
        try { render(body); } catch (err) { console.error('tab render failed', tab.tool, err); }
      } else {
        body.innerHTML = `<p class="settings-hint">Loading ${tab.title}…</p>`;
      }
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

function toggleToolPicker() {
  closeToolPicker();
  const btn = $('#tabAddBtn');
  const menu = document.createElement('div');
  menu.id = 'toolPickerMenu';
  menu.className = 'tool-picker-menu';
  menu.innerHTML = Object.entries(TOOL_DEFS).map(([key, def]) => `
    <button type="button" data-tool="${key}">
      <i class="fa-solid ${def.icon}"></i><span>${def.title}</span>
    </button>`).join('');
  menu.querySelectorAll('button').forEach((b) => {
    b.addEventListener('click', (e) => {
      e.stopPropagation();
      openToolTab(b.dataset.tool);
      closeToolPicker();
    });
  });
  // Position under the + button
  const rect = btn.getBoundingClientRect();
  menu.style.position = 'fixed';
  menu.style.left = `${rect.left}px`;
  menu.style.top = `${rect.bottom + 6}px`;
  document.body.appendChild(menu);
}

function closeToolPicker() {
  document.getElementById('toolPickerMenu')?.remove();
}
