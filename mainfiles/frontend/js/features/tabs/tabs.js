/**
 * Shell navigation — tabs on top (2026-10-25 user correction).
 *
 * The tab bar at the top of the app IS the navigation. There is no
 * sidebar and no sidebar destination button: the perfect-flow spec's
 * "no destination opens another destination as a tab" contradicted
 * the user's standing vision (Chat pinned as the only chat, everything
 * else opening as separate tool tabs) and was followed without
 * flagging it. This module restores that vision.
 *
 * There are exactly 8 destinations (see shell/router.js), each a real
 * page rendered into the main view; Chat is pinned first, never
 * closable, never duplicated. Every other destination opens as a
 * switchable, closable tab: navigating to a destination that already
 * has a tab focuses it (restoring that tab's stored param/section/
 * URL) instead of duplicating it. Closing a tab activates the most
 * recently used remaining tab, falling back to Chat; closing can
 * never leave a blank screen. Tabs start as the full destination set
 * (so the bar is also the map of the app) and closed tabs disappear
 * until reopened via the palette, a deep link, or a composer action.
 * With many tabs open the bar scrolls horizontally, never wraps.
 * Sub-navigation inside a destination is a segmented control at the
 * top of that destination's content area.
 *
 * Navigation stays URL-addressable: /chat, /projects/:id,
 * /studio/:artifact, /code/:repo, /research/:notebook, /agents/:id,
 * /library, /settings/:section (plus ?section= for in-destination
 * segments). Tab switches push URL state, so browser back/forward
 * moves between tabs, and a deep link opens (or focuses) the right
 * tab on load. Unknown routes render a 404 page with a "back to Chat"
 * action. Old destination ids (home/work/create/knowledge/…) REDIRECT
 * through router.js instead of 404ing, so old palette actions, slash
 * commands, and specs keep resolving.
 *
 * Compatibility: the tab API (showTool, showToolSection, showToolSub,
 * openToolTab, switchTab, closeTab, registerTabRenderer,
 * registerSectionActivator, getActiveViewTool, getActiveTabId) is
 * preserved — those functions now open/focus/close real tabs.
 */
import { DESTINATIONS, parseRoute, urlFor, resolveLegacyId, breadcrumbText } from '../shell/router.js';

const TOOL_DEFS = Object.fromEntries(DESTINATIONS.map((d) => [d.id, d]));

/** Old (destination, section) pairs -> new (destination, segment). */
const SECTION_MAP = {
  'work:agents': ['agents', 'hub'],
  'work:teams': ['agents', 'hub'],
  'work:compare': ['agents', 'hub'],
  'work:workflows': ['agents', 'workflows'],
  'work:activity': ['agents', 'run-history'],
  'work:runs': ['agents', 'run-history'],
  'work:security': ['agents', 'security'],
  'work:engineering': ['code', 'engineering'],
  'work:code': ['code', 'agent'],
  'agents:teams': ['agents', 'hub'],
  'agents:compare': ['agents', 'hub'],
  'agents:runs': ['agents', 'run-history'],
  'create:media': ['studio', 'media'],
  'create:image': ['studio', 'create'],
  'create:voice': ['studio', 'create'],
  'create:design': ['studio', 'design'],
  'knowledge:study': ['research', 'explore'],
  'knowledge:notebooks': ['research', 'notebooks'],
  'library:skills': ['library', 'skills'],
  'library:mcp': ['library', 'mcp'],
  'library:extensions': ['library', 'extensions'],
  'library:templates': ['library', 'templates'],
  'settings:usage': ['settings', 'data'],
  'settings:models': ['settings', 'models'],
};

/** Section activators registered by destination modules on render:
 *  dest -> fn(section) that switches the destination's segmented control. */
const sectionActivators = new Map();
export function registerSectionActivator(dest, fn) {
  sectionActivators.set(dest, fn);
}

function activateSection(dest, section) {
  if (!section) return;
  const tryActivate = () => {
    const fn = sectionActivators.get(dest);
    if (fn) { try { fn(section); } catch {} return true; }
    for (const attr of ['data-dest-section', 'data-agentsub', 'data-libtab', 'data-worksection', 'data-createsub']) {
      const btn = document.querySelector(`[${attr}="${section}"]`);
      if (btn) { btn.click(); return true; }
    }
    return false;
  };
  if (tryActivate()) return;
  let n = 0;
  const t = setInterval(() => {
    if (tryActivate() || ++n > 25) clearInterval(t);
  }, 120);
}

let renderers = {};
export function registerTabRenderer(tool, fn) {
  renderers[tool] = fn;
}
/** Alias with the new name; renderers are per-destination. */
export function registerDestinationRenderer(dest, fn) {
  renderers[dest] = fn;
}

function $(sel) { return document.querySelector(sel); }

/** Refresh the cached flags (call after a toggle in Settings). No-op now:
 *  the old tab picker (the only feature-flag consumer) is gone. Kept
 *  so existing callers do not break. */
export function invalidateFeatureCache() { /* no-op */ }

const viewCache = new Map(); // dest -> { container, lastParam, lastSection }
let activeDest = 'chat';
let activeParam = null;
let activeSection = null;
let currentParsed = null;

export function getActiveViewTool() { return activeDest === 'chat' ? null : activeDest; }
export function getActiveDestination() { return activeDest; }
export function getActiveTabId() { return activeDest === 'chat' ? 'main' : `view-${activeDest}`; }

/* ------------------------------------------------------------------ */
/* Tab-bar state. One tab per destination (keyed by destination id);  */
/* each tab remembers the param/section/URL it was last left at, so   */
/* switching back restores where the user was instead of resetting   */
/* to the destination landing page. Chat is always first and can     */
/* never be closed. `mru` is most-recently-used first, and decides   */
/* which tab activates when the active tab is closed.                */
/* ------------------------------------------------------------------ */
let openTabs = DESTINATIONS.map((d) => ({ dest: d.id, param: null, section: null, url: d.path }));
let activeTab = 'chat';
let mru = ['chat'];
let lastTabBarSignature = null;

function tabEntry(dest) {
  return openTabs.find((t) => t.dest === dest) || null;
}

function touchMru(dest) {
  mru = [dest, ...mru.filter((d) => d !== dest)];
}

/** Ensure a tab exists for a destination and make it active. */
function ensureTab(dest, { param = null, section = null, url = null } = {}) {
  let entry = tabEntry(dest);
  if (!entry) {
    entry = { dest, param, section, url };
    openTabs.push(entry);
  } else {
    entry.param = param;
    entry.section = section;
    entry.url = url;
  }
  activeTab = dest;
  touchMru(dest);
  return entry;
}

/**
 * Render the tab bar. Skips rebuilding the DOM when nothing changed
 * (same tab set, same active tab) so focus is never stolen by a
 * re-render during ordinary navigation.
 */
function renderTabBar() {
  const scroll = $('#tabBarScroll');
  if (!scroll) return;
  const signature = openTabs.map((t) => `${t.dest}@${t.url || ''}`).join('|') + `#${activeTab}`;
  if (signature === lastTabBarSignature) return;
  lastTabBarSignature = signature;
  scroll.innerHTML = '';
  for (const tab of openTabs) {
    const def = TOOL_DEFS[tab.dest];
    if (!def) continue;
    const item = document.createElement('div');
    item.className = 'tab-item';
    item.dataset.tab = tab.dest;
    item.setAttribute('role', 'tab');
    const selected = activeTab === tab.dest;
    item.setAttribute('aria-selected', String(selected));
    if (selected) item.classList.add('active');
    const label = document.createElement('button');
    label.type = 'button';
    label.className = 'tab-item-label';
    // data-nav keeps every existing [data-nav="…"] caller (specs,
    // composer actions) working: clicking a tab label focuses it.
    label.dataset.nav = tab.dest;
    label.title = def.title;
    label.setAttribute('aria-label', `${def.title} tab`);
    label.innerHTML = `<i class="fa-solid ${def.icon}" aria-hidden="true"></i><span>${def.title}</span>`
      + (tab.dest === 'chat' ? '<i class="fa-solid fa-thumbtack tab-pin" aria-hidden="true" title="Pinned"></i>' : '');
    label.addEventListener('click', () => {
      const entry = tabEntry(tab.dest);
      navigate(tab.dest, {
        param: entry ? entry.param : null,
        section: entry ? entry.section : null,
      });
    });
    item.appendChild(label);
    if (tab.dest !== 'chat') {
      const close = document.createElement('button');
      close.type = 'button';
      close.className = 'tab-item-close';
      close.dataset.tabClose = tab.dest;
      close.setAttribute('aria-label', `Close ${def.title} tab`);
      close.title = `Close ${def.title}`;
      close.innerHTML = '<i class="fa-solid fa-xmark" aria-hidden="true"></i>';
      close.addEventListener('click', (e) => {
        e.stopPropagation();
        closeTabByDest(tab.dest);
      });
      item.appendChild(close);
      // Middle-click closes, like a browser tab.
      item.addEventListener('auxclick', (e) => {
        if (e.button === 1) {
          e.preventDefault();
          closeTabByDest(tab.dest);
        }
      });
    }
    scroll.appendChild(item);
  }
}

/** Close a destination tab. Chat can never be closed. */
export function closeTabByDest(dest) {
  if (dest === 'chat' || !tabEntry(dest)) return;
  const wasActive = activeTab === dest;
  openTabs = openTabs.filter((t) => t.dest !== dest);
  mru = mru.filter((d) => d !== dest);
  if (!wasActive) {
    // Inactive tab closed: active tab and URL are untouched, but the
    // bar must still re-render (signature changed).
    lastTabBarSignature = null;
    renderTabBar();
    return;
  }
  // Active tab closed: fall back to the most recently used remaining
  // tab, else Chat. This can never blank the screen: Chat always
  // exists and always renders.
  const next = mru[0] || 'chat';
  const entry = tabEntry(next);
  navigate(next, {
    param: entry ? entry.param : null,
    section: entry ? entry.section : null,
  });
}

/** Slim contextual breadcrumb INSIDE the content area, depth > 1 only.
 *  There is no top bar and no repeated title bar anywhere else. */
function renderBreadcrumb(parsed) {
  const crumb = $('#destBreadcrumb');
  if (!crumb) return;
  const text = breadcrumbText(parsed);
  if (!text) {
    crumb.classList.add('hidden');
    crumb.textContent = '';
    return;
  }
  crumb.classList.remove('hidden');
  crumb.textContent = text;
}

function renderNotFound(path) {
  const body = $('#toolViewBody');
  if (!body) return;
  activeDest = null;
  activeTab = null;
  renderTabBar();
  $('#chatView')?.classList.add('hidden');
  $('#toolView')?.classList.remove('hidden');
  renderBreadcrumb(null);
  document.querySelectorAll('#toolViewBody .tool-tab-body').forEach((el) => el.classList.add('hidden'));
  let page = document.getElementById('destNotFound');
  if (!page) {
    page = document.createElement('div');
    page.id = 'destNotFound';
    page.className = 'tool-tab-body dest-notfound';
    body.appendChild(page);
  }
  page.classList.remove('hidden');
  page.innerHTML = `<h2>Page not found</h2>
    <p class="settings-hint">There is no page at “${path}”. It may be an old link — the destinations are Chat, Projects, Studio, Code, Research, Agents, Library, and Settings.</p>
    <button type="button" class="btn-primary" id="notFoundBack">Back to Chat</button>`;
  page.querySelector('#notFoundBack')?.addEventListener('click', () => navigate('chat'));
}

/**
 * Navigate to a destination. opts: { param, section, push }.
 * push=false is used for popstate / initial load (URL already correct).
 */
export function navigate(dest, { param = null, section = null, push = true } = {}) {
  if (!TOOL_DEFS[dest]) return;
  const url = urlFor(dest, { param, section });
  if (push && window.location.pathname + window.location.search !== url) {
    window.history.pushState({ dest, param, section }, '', url);
  }
  activeDest = dest;
  activeParam = param;
  activeSection = section;
  currentParsed = parseRoute(url);
  // Tab state follows navigation: the destination's tab is created
  // (if it was closed) or focused, remembering this param/section/
  // URL for the next switch back. There is no sidebar drawer anymore
  // — nothing can linger over content after a navigation.
  ensureTab(dest, { param, section, url });
  renderTabBar();
  document.dispatchEvent(new CustomEvent('sangam:destination-changed', {
    detail: { dest, param, section },
  }));

  if (dest === 'chat') {
    $('#toolView')?.classList.add('hidden');
    $('#chatView')?.classList.remove('hidden');
    renderBreadcrumb(currentParsed);
    return;
  }

  $('#chatView')?.classList.add('hidden');
  $('#toolView')?.classList.remove('hidden');
  renderBreadcrumb(currentParsed);

  const body = $('#toolViewBody');
  if (!body) return;
  let entry = viewCache.get(dest);
  if (!entry || !entry.container.isConnected) {
    const container = document.createElement('div');
    container.id = `viewbody-${dest}`;
    container.className = 'tool-tab-body';
    container.dataset.tool = dest;
    body.appendChild(container);
    entry = { container, lastParam: null, lastSection: null, rendered: false };
    viewCache.set(dest, entry);
  }
  document.querySelectorAll('#toolViewBody .tool-tab-body').forEach((el) => {
    el.classList.toggle('hidden', el !== entry.container);
  });
  const render = renderers[dest];
  const paramChanged = entry.lastParam !== param;
  const isSettings = dest === 'settings';
  // First render (including a direct landing before app.js registered
  // renderers — the later navigation then renders, it does not stay
  // blank), or a detail-param change, re-renders. Anything else is a
  // segment switch, handled by the destination's section activator so
  // mount-once state (forms, scroll) survives.
  if (render && (!entry.rendered || paramChanged)) {
    entry.rendered = true;
    entry.lastParam = param;
    entry.lastSection = section;
    try {
      const out = render(entry.container, { param, section });
      if (out && typeof out.catch === 'function') {
        out.catch((err) => {
          console.error('destination render failed', dest, err);
          entry.container.innerHTML = `<p class="settings-hint">Could not load ${TOOL_DEFS[dest].title}: ${err?.message || err}</p>`;
        });
      }
    } catch (err) {
      console.error('destination render failed', dest, err);
      entry.container.innerHTML = `<p class="settings-hint">Could not load ${TOOL_DEFS[dest].title}: ${err?.message || err}</p>`;
    }
  } else if (render && isSettings && section && section !== entry.lastSection) {
    // Settings section switches are handled by its section activator below.
    entry.lastSection = section;
  } else {
    entry.lastParam = param;
    entry.lastSection = section;
  }
  if (section) activateSection(dest, section);
}

/** Show a destination by id, old id, or URL path. */
export function showTool(requested, opts = {}) {
  if (!requested) return;
  if (typeof requested === 'string' && requested.startsWith('/')) {
    routeFromLocation(requested);
    return;
  }
  const redirect = resolveLegacyId(requested);
  if (redirect && !TOOL_DEFS[requested]) {
    // Genuinely old id only: current ids must NOT fall through to
    // routeFromLocation, which navigates with push:false and would
    // render the destination without updating the URL (rail clicks
    // silently stopped changing the address bar).
    routeFromLocation(redirect);
    return;
  }
  if (TOOL_DEFS[requested]) {
    navigate(requested, opts);
  }
}

/** Show a destination and, if given, its segment. Old pairs remap. */
export function showToolSection(dest, section) {
  const mapped = SECTION_MAP[`${dest}:${section}`];
  if (mapped) {
    navigate(mapped[0], { section: mapped[1] });
    return;
  }
  if (TOOL_DEFS[dest]) {
    navigate(dest, { section: section || null });
    return;
  }
  const redirect = resolveLegacyId(dest);
  if (redirect) routeFromLocation(redirect);
}

/**
 * Deep-link into a destination's sub-view: shows the destination, then
 * clicks its sub-control (polls briefly for async renders).
 */
export function showToolSub(tool, subAttr, subId) {
  // Legacy attribute names map onto destination segments where known.
  const mapped = SECTION_MAP[`${tool}:${subId}`];
  if (mapped) {
    navigate(mapped[0], { section: mapped[1] });
    return;
  }
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

/**
 * Open (or focus, if already open) a destination tab. Returns the view
 * id, or null. Kept for every existing caller (palette, composer,
 * slash commands, nav handlers).
 */
export function openToolTab(tool, _opts = {}) {
  if (!tool) return null;
  showTool(tool);
  return activeDest ? `view-${activeDest}` : null;
}

/**
 * Close a tab by id: 'main' (Chat, never closable), 'view-<dest>', or
 * a bare destination id. Closing the active tab falls back to the
 * most recently used remaining tab (else Chat).
 */
export function closeTab(tabId) {
  if (tabId === 'main' || tabId === 'chat') return;
  const dest = String(tabId).startsWith('view-') ? String(tabId).slice(5) : tabId;
  closeTabByDest(dest);
}

/** Focus a tab by id ('main', 'view-<dest>', or a destination id). */
export function switchTab(tabId) {
  if (tabId === 'main' || tabId === 'chat') navigate('chat');
  else if (TOOL_DEFS[tabId]) {
    const entry = tabEntry(tabId);
    navigate(tabId, {
      param: entry ? entry.param : null,
      section: entry ? entry.section : null,
    });
  } else showTool(tabId);
}

/** Route the current (or given) URL: redirects, destinations, or 404. */
export function routeFromLocation(url = null) {
  const raw = url || (window.location.pathname + window.location.search);
  const parsed = parseRoute(raw);
  if (parsed.redirect) {
    if (!url) window.history.replaceState({}, '', parsed.redirect);
    const target = parseRoute(parsed.redirect);
    navigate(target.dest, { param: target.param, section: target.section, push: false });
    return;
  }
  if (parsed.notFound) {
    renderNotFound(parsed.path);
    return;
  }
  navigate(parsed.dest, { param: parsed.param, section: parsed.section, push: false });
}

export function initTabs() {
  window.addEventListener('popstate', () => routeFromLocation());
  // First paint: render the bar (Chat pinned + the destination set),
  // then honour the URL the user arrived on (deep link or '/') — the
  // deep-linked destination's tab is focused, Chat stays pinned.
  renderTabBar();
  routeFromLocation();
}
