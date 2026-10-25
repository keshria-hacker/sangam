/**
 * Shell navigation — A1 perfect-flow IA (§3, §6.2).
 *
 * The sidebar is the single source of navigation. There are exactly 8
 * destinations (see shell/router.js), each a real page rendered into
 * the main view; Chat is pinned and is the only chat surface. There
 * are NO strip tabs and NO container-that-opens-tabs: Work and Create
 * are flattened (their contents now live in Agents / Code / Studio /
 * Research), and sub-navigation inside a destination is a segmented
 * control at the top of that destination's content area.
 *
 * Navigation is URL-addressable: /chat, /projects/:id, /studio/:artifact,
 * /code/:repo, /research/:notebook, /agents/:id, /library,
 * /settings/:section (plus ?section= for in-destination segments).
 * Unknown routes render a 404 page with a "back to Chat" action.
 * Old destination ids (home/work/create/knowledge/…) REDIRECT through
 * router.js instead of 404ing, so old palette actions, slash commands,
 * and specs keep resolving.
 *
 * Compatibility: the old tab API (showTool, showToolSection,
 * showToolSub, openToolTab, switchTab, closeTab, registerTabRenderer,
 * registerSectionActivator, getActiveViewTool, getActiveTabId) is
 * preserved — those functions now navigate destinations instead of
 * opening tabs. Nothing in the app opens a second view anymore.
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

/** Highlight the active destination in the sidebar rail. */
function markSidebarActive(dest) {
  document.querySelectorAll('.rail-item').forEach((b) => {
    const on = b.dataset.nav === dest;
    b.classList.toggle('active', on);
    if (on) b.setAttribute('aria-current', 'page');
    else b.removeAttribute('aria-current');
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
  document.querySelectorAll('.rail-item').forEach((b) => {
    b.classList.remove('active');
    b.removeAttribute('aria-current');
  });
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
  document.dispatchEvent(new CustomEvent('sangam:destination-changed', {
    detail: { dest, param, section },
  }));

  if (dest === 'chat') {
    $('#toolView')?.classList.add('hidden');
    $('#chatView')?.classList.remove('hidden');
    renderBreadcrumb(currentParsed);
    markSidebarActive('chat');
    return;
  }

  $('#chatView')?.classList.add('hidden');
  $('#toolView')?.classList.remove('hidden');
  renderBreadcrumb(currentParsed);
  markSidebarActive(dest);

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
  if (redirect) {
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
 * Old tab API: opening a "tab" now just navigates to the destination
 * (no second view is ever opened). Returns the view id, or null.
 */
export function openToolTab(tool, _opts = {}) {
  if (!tool) return null;
  const before = activeDest;
  showTool(tool);
  return activeDest ? `view-${activeDest}` : null;
}

export function closeTab(tabId) {
  if (tabId === 'main') return;
  navigate('chat');
}

export function switchTab(tabId) {
  if (tabId === 'main' || tabId === 'chat') navigate('chat');
  else if (TOOL_DEFS[tabId]) navigate(tabId);
  else showTool(tabId);
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
  // First paint: honour the URL the user arrived on (deep link or '/').
  routeFromLocation();
}
