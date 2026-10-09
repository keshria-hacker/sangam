/**
 * Routes / Combos / Quota UI (Sangam-native, Phase 5).
 *
 * Routes: conditional model routing (e.g. "code → codemodel").
 * Combos: model chains (draft → refine).
 * Quota: usage display from analytics.
 *
 * Stored in settings (no backend table needed for Phase 5).
 */
import { getSetting, setSetting } from '../../shared/settings_store.js';
import { apiFetch } from '../../shared/http.js';
import { escapeHtml } from '../../shared/utils.js';
import { showToast } from '../../shared/toast.js';

console.log('[Module] routes.js loaded');

export function getRoutes() {
  try {
    return JSON.parse(getSetting('routingRules') || '[]');
  } catch { return []; }
}

export function setRoutes(rules) {
  setSetting('routingRules', JSON.stringify(rules));
}

export function getCombos() {
  try {
    return JSON.parse(getSetting('modelCombos') || '[]');
  } catch { return []; }
}

/** Evaluate routing rules against a message. Returns model_id or null. */
export function evaluateRoutes(message) {
  const rules = getRoutes();
  const lower = message.toLowerCase();
  for (const r of rules) {
    if (!r.enabled) continue;
    const keywords = (r.keywords || '').toLowerCase().split(',').map((k) => k.trim()).filter(Boolean);
    if (keywords.some((k) => lower.includes(k))) {
      return r.model_id;
    }
  }
  return null;
}

export async function renderRoutesTab(bodyEl) {
  bodyEl.innerHTML = `
    <div class="routes-view">
      <h3><i class="fa-solid fa-route"></i> Routes, Combos & Quota</h3>

      <section class="routes-section">
        <h4>Routing rules <button class="btn-secondary btn-sm" id="routeAdd">+ Add rule</button></h4>
        <p class="settings-hint">If a message contains the keywords, use the specified model.</p>
        <div id="routeList"></div>
      </section>

      <section class="routes-section">
        <h4>Combos</h4>
        <p class="settings-hint">Chain models: draft with a fast model, refine with a smart one.</p>
        <div id="comboList"></div>
        <button class="btn-secondary btn-sm" id="comboAdd">+ Add combo</button>
      </section>

      <section class="routes-section">
        <h4>Quota</h4>
        <div id="quotaView"><p class="settings-hint">Loading…</p></div>
      </section>
    </div>`;

  renderRouteList(bodyEl);
  renderComboList(bodyEl);
  loadQuota(bodyEl);

  bodyEl.querySelector('#routeAdd')?.addEventListener('click', () => showRouteForm(bodyEl));
  bodyEl.querySelector('#comboAdd')?.addEventListener('click', () => showComboForm(bodyEl));
}

function renderRouteList(bodyEl) {
  const list = bodyEl.querySelector('#routeList');
  const rules = getRoutes();
  list.innerHTML = rules.length ? rules.map((r, i) => `
    <div class="route-row">
      <span class="route-kw">${escapeHtml(r.keywords)}</span>
      <i class="fa-solid fa-arrow-right"></i>
      <span class="route-model">${escapeHtml(r.model_id)}</span>
      <label class="switch"><input type="checkbox" data-i="${i}"${r.enabled ? ' checked' : ''}>
        <span class="switch-track"><span class="switch-thumb"></span></span></label>
      <button class="icon-btn" data-del="${i}" aria-label="Delete rule"><i class="fa-solid fa-trash"></i></button>
    </div>`).join('')
    : '<p class="settings-hint">No routing rules yet.</p>';
  list.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', () => {
    const rules = getRoutes();
    rules.splice(Number(b.dataset.del), 1);
    setRoutes(rules);
    renderRouteList(bodyEl);
  }));
  list.querySelectorAll('input[type=checkbox]').forEach((cb) => cb.addEventListener('change', () => {
    const rules = getRoutes();
    rules[Number(cb.dataset.i)].enabled = cb.checked;
    setRoutes(rules);
  }));
}

async function showRouteForm(bodyEl) {
  const models = await fetchModels();
  const keywords = prompt('Keywords (comma-separated):');
  if (!keywords) return;
  const model_id = prompt(`Model ID (available: ${models.slice(0, 5).join(', ')}…):`);
  if (!model_id) return;
  const rules = getRoutes();
  rules.push({ keywords, model_id, enabled: true });
  setRoutes(rules);
  renderRouteList(bodyEl);
  showToast({ type: 'success', title: 'Route added' });
}

async function fetchModels() {
  try {
    const data = await (await apiFetch('/models')).json();
    return (data.models || []).map((m) => m.id);
  } catch { return []; }
}

function renderComboList(bodyEl) {
  const list = bodyEl.querySelector('#comboList');
  const combos = getCombos();
  list.innerHTML = combos.length ? combos.map((c, i) => `
    <div class="route-row">
      <span><strong>${escapeHtml(c.name)}</strong>: ${escapeHtml(c.steps.join(' → '))}</span>
      <button class="icon-btn" data-del="${i}" aria-label="Delete combo"><i class="fa-solid fa-trash"></i></button>
    </div>`).join('')
    : '<p class="settings-hint">No combos yet. Example: "Fast draft" = gpt-4o-mini → gpt-4o.</p>';
  list.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', () => {
    const combos = getCombos();
    combos.splice(Number(b.dataset.del), 1);
    setSetting('modelCombos', JSON.stringify(combos));
    renderComboList(bodyEl);
  }));
}

async function showComboForm(bodyEl) {
  const name = prompt('Combo name:');
  if (!name) return;
  const steps = prompt('Model IDs in order (comma-separated):');
  if (!steps) return;
  const combos = getCombos();
  combos.push({ name, steps: steps.split(',').map((s) => s.trim()).filter(Boolean) });
  setSetting('modelCombos', JSON.stringify(combos));
  renderComboList(bodyEl);
  showToast({ type: 'success', title: 'Combo added' });
}

async function loadQuota(bodyEl) {
  const view = bodyEl.querySelector('#quotaView');
  try {
    const data = await (await apiFetch('/analytics/summary')).json();
    const s = data.summary || {};
    view.innerHTML = `
      <div class="memory-stats">
        <span class="memory-stat"><strong>Messages</strong>${s.messages || 0}</span>
        <span class="memory-stat"><strong>Tokens</strong>${(s.tokens || 0).toLocaleString()}</span>
        <span class="memory-stat"><strong>Cost</strong>$${(s.cost_usd || 0).toFixed(2)}</span>
      </div>
      <p class="settings-hint">Set per-run cost caps in Settings → Agents & Safety.</p>`;
  } catch {
    view.innerHTML = '<p class="settings-hint">Analytics not enabled.</p>';
  }
}
