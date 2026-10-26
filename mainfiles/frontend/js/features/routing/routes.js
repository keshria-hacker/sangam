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

/** Evaluate routing rules against a message. Returns model_id or null.
 * Phase 7: evaluates on the backend so every client and automation uses it.
 * Falls back to local evaluation if the backend is unreachable.
 */
export async function evaluateRoutes(message) {
  try {
    const res = await (await apiFetch('/routing/evaluate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    })).json();
    if (res && res.matched) return res.model_id;
    return null;
  } catch {
    // Fallback: local evaluation
    return evaluateRoutesLocal(message);
  }
}

/** Local fallback for routing evaluation (same logic as backend). */
export function evaluateRoutesLocal(message) {
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
        <h4>Usage</h4>
        <div id="quotaView"><p class="settings-hint">Loading…</p></div>
        <button class="btn-secondary btn-sm" id="quotaOpen" type="button">Open full usage in Settings → Usage</button>
      </section>
    </div>`;

  renderRouteList(bodyEl);
  renderComboList(bodyEl);
  loadQuota(bodyEl);

  bodyEl.querySelector('#routeAdd')?.addEventListener('click', () => showRouteForm(bodyEl));
  bodyEl.querySelector('#comboAdd')?.addEventListener('click', () => showComboForm(bodyEl));
  // UI-simplify: Quota was a second, smaller copy of Settings → Usage.
  // The numbers stay here on the card; the full view lives in Settings.
  bodyEl.querySelector('#quotaOpen')?.addEventListener('click', () => {
    import('../tabs/tabs.js').then((m) => m.showToolSection('settings', 'usage')).catch(() => {});
  });
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

/** Model picker for the inline forms: a dropdown from the /models list
 * (no memorised ids), falling back to a free-text input when no models
 * are available yet. */
function modelPickerHtml(models, attrs) {
  if (!models.length) {
    return `<input class="provider-key-input" ${attrs} placeholder="Model id (no models found yet)" aria-label="Model id">`;
  }
  return `<select class="provider-key-input" ${attrs} aria-label="Model">
    <option value="">Choose a model…</option>
    ${models.map((id) => `<option value="${escapeHtml(id)}">${escapeHtml(id)}</option>`).join('')}
  </select>`;
}

async function showRouteForm(bodyEl) {
  const existing = bodyEl.querySelector('[data-route-form]');
  if (existing) { existing.querySelector('input, select')?.focus(); return; }
  const models = await fetchModels();
  const list = bodyEl.querySelector('#routeList');
  const form = document.createElement('div');
  form.className = 'route-row';
  form.dataset.routeForm = '';
  form.innerHTML = `
    <input class="provider-key-input" data-route-kw placeholder="Keywords, comma-separated (e.g. code, debug)" aria-label="Keywords" style="flex:2;min-width:160px">
    ${modelPickerHtml(models, 'data-route-model')}
    <button class="btn-primary btn-sm" type="button" data-route-save>Save</button>
    <button class="btn-secondary btn-sm" type="button" data-route-cancel>Cancel</button>`;
  list.before(form);
  const kwInput = form.querySelector('[data-route-kw]');
  kwInput.focus();
  form.querySelector('[data-route-cancel]').addEventListener('click', () => form.remove());
  form.querySelector('[data-route-save]').addEventListener('click', () => {
    const keywords = kwInput.value.trim();
    const model_id = form.querySelector('[data-route-model]').value.trim();
    if (!keywords) { showToast({ type: 'info', message: 'Enter at least one keyword.' }); kwInput.focus(); return; }
    if (!model_id) { showToast({ type: 'info', message: 'Choose a model.' }); return; }
    const rules = getRoutes();
    rules.push({ keywords, model_id, enabled: true });
    setRoutes(rules);
    form.remove();
    renderRouteList(bodyEl);
    showToast({ type: 'success', title: 'Route added' });
  });
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
  const existing = bodyEl.querySelector('[data-combo-form]');
  if (existing) { existing.querySelector('input')?.focus(); return; }
  const models = await fetchModels();
  const list = bodyEl.querySelector('#comboList');
  const form = document.createElement('div');
  form.className = 'route-row';
  form.dataset.comboForm = '';
  form.style.flexWrap = 'wrap';
  form.innerHTML = `
    <input class="provider-key-input" data-combo-name placeholder="Combo name (e.g. Fast draft)" aria-label="Combo name" style="flex:1;min-width:160px">
    <div data-combo-steps style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
      ${modelPickerHtml(models, 'data-combo-step')}
    </div>
    <button class="btn-secondary btn-sm" type="button" data-combo-add-step>+ Add step</button>
    <button class="btn-primary btn-sm" type="button" data-combo-save>Save</button>
    <button class="btn-secondary btn-sm" type="button" data-combo-cancel>Cancel</button>`;
  list.before(form);
  const nameInput = form.querySelector('[data-combo-name]');
  nameInput.focus();
  form.querySelector('[data-combo-add-step]').addEventListener('click', () => {
    const stepWrap = document.createElement('span');
    stepWrap.innerHTML = modelPickerHtml(models, 'data-combo-step');
    form.querySelector('[data-combo-steps]').appendChild(stepWrap);
  });
  form.querySelector('[data-combo-cancel]').addEventListener('click', () => form.remove());
  form.querySelector('[data-combo-save]').addEventListener('click', () => {
    const name = nameInput.value.trim();
    const steps = [...form.querySelectorAll('[data-combo-step]')].map((el) => el.value.trim()).filter(Boolean);
    if (!name) { showToast({ type: 'info', message: 'Enter a combo name.' }); nameInput.focus(); return; }
    if (!steps.length) { showToast({ type: 'info', message: 'Choose at least one model step.' }); return; }
    const combos = getCombos();
    combos.push({ name, steps });
    setSetting('modelCombos', JSON.stringify(combos));
    form.remove();
    renderComboList(bodyEl);
    showToast({ type: 'success', title: 'Combo added' });
  });
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
