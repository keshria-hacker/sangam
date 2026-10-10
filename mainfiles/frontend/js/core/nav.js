/**
 * Nav source of truth — defines the studio rail (Sangam-native).
 *
 * Grouped by intent, not technology. Each item: icon, label, badge,
 * action. Feeds the rail, command palette, and deep links.
 * Features that are off show as muted with "Turn on" (never invisible).
 */
import { showTool } from '../features/tabs/tabs.js';
import { apiPost } from '../shared/http.js';
import { showToast } from '../shared/toast.js';

console.log('[Module] nav.js loaded');

export const NAV_ITEMS = [
  { id: 'home',      label: 'Home',      icon: 'fa-house',            action: 'home',      feature: null },
  { id: 'chat',      label: 'Chat',      icon: 'fa-comment',          action: 'chat',      feature: null },
  { id: 'agents',    label: 'Agents',    icon: 'fa-robot',            action: 'tab:agents', feature: null },
  { id: 'knowledge', label: 'Knowledge', icon: 'fa-brain',            action: 'tab:knowledge', feature: null },
  { id: 'create',    label: 'Create',    icon: 'fa-wand-magic-sparkles', action: 'tab:create', feature: null },
  { id: 'code',      label: 'Code',      icon: 'fa-code',             action: 'tab:code',   feature: null },
  { id: 'learn',     label: 'Learn',     icon: 'fa-graduation-cap',   action: 'tab:learn',  feature: 'learning' },
  { id: 'library',   label: 'Library',   icon: 'fa-book',             action: 'tab:library', feature: null },
  { id: 'insights',  label: 'Insights',  icon: 'fa-chart-simple',     action: 'tab:analytics', feature: 'analytics' },
  { id: 'images',    label: 'Images',    icon: 'fa-image',            action: 'tab:images',  feature: 'image_gen' },
  { id: 'voice',     label: 'Voice',     icon: 'fa-microphone',       action: 'tab:voice',   feature: 'voice' },
];

export const NAV_BOTTOM = [
  { id: 'settings', label: 'Settings', icon: 'fa-gear', action: 'settings', feature: null },
];

let handlers = {};

export function registerNavHandler(action, fn) {
  handlers[action] = fn;
}

export function navigate(action) {
  if (handlers[action]) {
    handlers[action]();
    return;
  }
  // Default: tab:xxx shows the tool in the main view (Phase 8 B6: rail replaces view)
  if (action.startsWith('tab:')) {
    showTool(action.slice(4));
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
      }
      container.querySelectorAll('.rail-item').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
    });
    if (item.id === 'settings') btn.classList.add('rail-bottom');
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
    const fresh = container.querySelector(`.rail-item[data-nav="${item.id}"]`);
    container.querySelectorAll('.rail-item').forEach((b) => b.classList.remove('active'));
    fresh?.classList.add('active');
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
