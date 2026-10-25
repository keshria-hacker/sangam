/**
 * Nav source of truth — defines the studio rail (Sangam-native).
 *
 * Grouped by intent, not technology. Each item: icon, label, badge,
 * action. Feeds the rail, command palette, and deep links.
 * Features that are off show as muted with "Turn on" (never invisible).
 */
import { openToolTab, showTool, switchTab } from '../features/tabs/tabs.js';
import { apiPost } from '../shared/http.js';
import { showToast } from '../shared/toast.js';

console.log('[Module] nav.js loaded');

// A1 perfect-flow IA (§3): the sidebar IS the map of the app. Chat is
// pinned at the top; the 8 destinations below it, in spec order, are
// the only top-level places. Old destinations (Home/Work/Create/
// Knowledge) are gone: their contents live inside the new destinations
// as segmented sub-navigation, never as rail items or nested tabs.
// The sidebar footer (avatar, usage meter, palette hint, help) lives
// in index.html, not in this rail list.
export const NAV_ITEMS = [
  { id: 'chat',      label: 'Chat',      icon: 'fa-message',             action: 'chat' },
  { id: 'projects',  label: 'Projects',  icon: 'fa-folder-open',        action: 'view:projects' },
  { id: 'studio',    label: 'Studio',    icon: 'fa-wand-magic-sparkles', action: 'view:studio' },
  { id: 'code',      label: 'Code',      icon: 'fa-code',               action: 'view:code' },
  { id: 'research',  label: 'Research',  icon: 'fa-magnifying-glass',   action: 'view:research' },
  { id: 'agents',    label: 'Agents',    icon: 'fa-robot',              action: 'view:agents' },
  { id: 'library',   label: 'Library',   icon: 'fa-book',               action: 'view:library' },
  { id: 'settings',  label: 'Settings',  icon: 'fa-gear',               action: 'view:settings' },
];
export const NAV_BOTTOM = [];

let handlers = {};

export function registerNavHandler(action, fn) {
  handlers[action] = fn;
}

export function navigate(action) {
  if (handlers[action]) {
    handlers[action]();
    return;
  }
  if (action === 'chat') {
    switchTab('main');
    return;
  }
  // view:xxx shows the destination in the main view (rail navigation).
  if (action.startsWith('view:')) {
    showTool(action.slice(5));
    return;
  }
  // Default: tab:xxx shows the tool in the main view (Phase 8 B6: rail replaces view)
  if (action.startsWith('tab:')) {
    openToolTab(action.slice(4));
  }
}

/** Mark one rail item active (visual + aria-current) and move focus into
 *  the newly shown view so keyboard/screen-reader users land on content. */
export function markRailActive(container, itemId) {
  container.querySelectorAll('.rail-item').forEach((b) => {
    b.classList.remove('active');
    b.removeAttribute('aria-current');
  });
  const btn = container.querySelector(`.rail-item[data-nav="${itemId}"]`);
  if (btn) {
    btn.classList.add('active');
    btn.setAttribute('aria-current', 'page');
  }
  const toolHidden = document.getElementById('toolView')?.classList.contains('hidden');
  // A1: there is no title bar to focus anymore; land on the destination
  // content itself (or the chat view for Chat).
  const target = !toolHidden ? document.getElementById('toolViewBody') : document.getElementById('chatView');
  if (target) {
    if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
    target.focus({ preventScroll: true });
  }
}

/** Build the rail DOM into a container. */
export function renderRail(container, features = {}) {
  container.innerHTML = '';
  const all = [...NAV_ITEMS, ...NAV_BOTTOM];
  for (const item of all) {
    const off = item.feature && !features[item.feature];
    const btn = document.createElement('button');
    btn.className = 'rail-item' + (off ? ' rail-off' : '');
    btn.dataset.nav = item.id;
    btn.title = off ? `${item.label} — enable in Settings → Features` : item.label;
    btn.setAttribute('aria-label', item.label);
    btn.innerHTML = `<i class="fa-solid ${item.icon}"></i><span>${item.label}</span>`
      + (off ? '<span class="rail-turnon">Turn on</span>' : '')
      + `<span class="rail-badge hidden"></span>`;
    btn.addEventListener('click', () => {
      if (off) {
        // A5: "Turn on" enables the feature, then opens it — never
        // sends the user to Settings instead.
        enableAndOpen(item, btn, container);
      } else {
        navigate(item.action);
        markRailActive(container, item.id);
      }
    });
    container.appendChild(btn);
  }
}

/**
 * A5: Enable a feature via the backend, refresh the rail, then open it.
 * The rail item said "Turn on" — so clicking turns it on.
 */
async function enableAndOpen(item, btn, container) {
  btn.disabled = true;
  try {
    const res = await apiPost(`/features/${encodeURIComponent(item.feature)}`, { enabled: true });
    const data = await res.json();
    showToast({ type: 'success', title: `${item.label} turned on` });
    // Re-render the rail with fresh feature state, then navigate.
    const features = data.features || {};
    renderRail(container, features);
    navigate(item.action);
    markRailActive(container, item.id);
  } catch (err) {
    showToast({ type: 'error', title: `Could not turn on ${item.label}`, message: err?.message || String(err) });
    btn.disabled = false;
  }
}

/** Set a live badge on a rail item (e.g. running count). */
export function setRailBadge(itemId, text) {  const btn = document.querySelector(`.rail-item[data-nav="${itemId}"]`);
  const badge = btn?.querySelector('.rail-badge');
  if (badge) {
    badge.textContent = text || '';
    badge.classList.toggle('hidden', !text);
  }
}
