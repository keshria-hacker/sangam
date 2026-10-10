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
  agents:    { title: 'Agents',        icon: 'fa-robot',               feature: null },
  create:    { title: 'Create',        icon: 'fa-wand-magic-sparkles', feature: null },
  library:   { title: 'Library',       icon: 'fa-book',               feature: null },
  code:      { title: 'Code',          icon: 'fa-code',                feature: null },
  // Phase 8 B7: merged pages. The old separate tabs are gone:
  // - teams, compare -> Agents page sub-views
  // - skills, automations -> Library / Agents sub-views
  // - routes -> Settings > Models & Routing
  // - learn, analytics -> Settings sub-pages
  // - images, voice -> Create sub-views
  // - design -> Create sub-view
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
    el.setAttribute('tabindex', t.id === activeTabId ? '0' : '-1');
    el.dataset.tabId = t.id;
    el.innerHTML = `<i class="fa-solid ${t.icon}"></i><span>${t.title}</span>
      <button class="tab-close" aria-label="Close ${t.title} tab" tabindex="-1"><i class="fa-solid fa-xmark"></i></button>`;
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
    mainTab.setAttribute('tabindex', activeTabId === 'main' ? '0' : '-1');
  }
}

/** Arrow-key navigation for the tab strip (WAI-ARIA tabs pattern). */
function initTabKeyboard() {
  const strip = $('#tabStrip');
  if (!strip || strip.dataset.kbWired) return;
  strip.dataset.kbWired = '1';
  strip.addEventListener('keydown', (e) => {
    const tabs = [...strip.querySelectorAll('[role="tab"]')];
    const cur = document.activeElement;
    const i = tabs.indexOf(cur);
    if (i === -1) return;
    let next = -1;
    if (e.key === 'ArrowRight') next = (i + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      cur.click();
      return;
    } else return;
    e.preventDefault();
    tabs[next].focus();
    // Activate on focus (automatic activation)
    tabs[next].click();
  });
}

/** Open (or focus) a tool tab. Returns the tab id. */
export function openToolTab(tool) {
  const def = TOOL_DEFS[tool];
  if (!def) return null;
  // Phase 8 B6: cap explicit split-view tabs at 2 (plus pinned main).
  if (openTabs.length >= 2 && !openTabs.some((t) => t.tool === tool)) {
    const oldest = openTabs[0];
    closeTab(oldest.id);
  }
  let tab = openTabs.find((t) => t.tool === tool);
  if (!tab) {
    tab = { id: `tool-${tool}`, tool, title: def.title, icon: def.icon, mounted: false };
    openTabs.push(tab);
  }
  switchTab(tab.id);
  return tab.id;
}

// ---------------------------------------------------------------------------
// Main-view navigation (Phase 8 B6).
//
// Rail items REPLACE the main view — one page at a time, no strip tab.
// The strip tabs remain only for explicit "open beside chat" split views
// (max 2, enforced above). Main-view containers are mount-once like tabs.
// ---------------------------------------------------------------------------

const viewCache = new Map(); // tool -> container
let activeViewTool = null;

/** Show a tool in the main view (rail navigation). Mount-once per tool. */
export function showTool(tool) {
  const def = TOOL_DEFS[tool];
  if (!def) return;
  activeViewTool = tool;
  activeTabId = 'main'; // strip shows main active; the rail owns the highlight
  const body = $('#toolViewBody');
  let container = viewCache.get(tool);
  if (!container || !container.isConnected) {
    container = document.createElement('div');
    container.id = `viewbody-${tool}`;
    container.className = 'tool-tab-body';
    container.dataset.tool = tool;
    body.appendChild(container);
    const render = renderers[tool];
    if (render) {
      try { render(container); } catch (err) { console.error('view render failed', tool, err); }
    } else {
      container.innerHTML = `<p class="settings-hint">Loading ${def.title}…</p>`;
    }
    viewCache.set(tool, container);
  }
  document.querySelectorAll('#toolViewBody .tool-tab-body').forEach((el) => {
    el.classList.toggle('hidden', el !== container);
  });
  $('#chatView')?.classList.add('hidden');
  $('#toolView')?.classList.remove('hidden');
  const titleEl = $('#toolViewTitle');
  if (titleEl) titleEl.innerHTML = `<i class="fa-solid ${def.icon}"></i> ${def.title}`;
  // The pinned tab shows the active rail view's name (not "Chat") so the
  // strip always matches what's on screen.
  const mainTab = $('#mainTab');
  if (mainTab) mainTab.innerHTML = `<i class="fa-solid ${def.icon}" aria-hidden="true"></i><span>${def.title}</span>`;
  renderTabStrip();
}

/** Which tool (if any) is currently shown in the main view. */
export function getActiveViewTool() { return activeViewTool; }

/**
 * Phase 8 B7: deep-link into a merged page's sub-view.
 * Shows the tool, then clicks its sub-tab (polls briefly for async renders).
 */
export function showToolSub(tool, subAttr, subId) {
  showTool(tool);
  const tryClick = () => {
    const btn = document.querySelector(`[${subAttr}="${subId}"]`);
    if (btn) { btn.click(); return true; }
    return false;
  };
  if (tryClick()) return;
  let n = 0;
  const t = setInterval(() => {
    if (tryClick() || ++n > 25) clearInterval(t);
  }, 120);
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
  activeViewTool = null; // leaving the rail view (if any)
  const isMain = tabId === 'main';
  $('#chatView')?.classList.toggle('hidden', !isMain);
  $('#toolView')?.classList.toggle('hidden', isMain);
  if (isMain) {
    // Restore the pinned tab's chat label after a rail view renamed it.
    const mainTab = $('#mainTab');
    if (mainTab) mainTab.innerHTML = `<i class="fa-solid fa-message" aria-hidden="true"></i><span>Chat</span>`;
  }
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
  const mainTab = $('#mainTab');
  mainTab?.addEventListener('click', () => switchTab('main'));
  if (mainTab && !mainTab.hasAttribute('tabindex')) mainTab.setAttribute('tabindex', '0');
  initTabKeyboard();
  $('#toolViewClose')?.addEventListener('click', () => {
    // Closing a rail view returns to chat; closing a strip tab closes it.
    if (activeViewTool) switchTab('main');
    else closeTab(activeTabId);
  });
  renderTabStrip();
}

