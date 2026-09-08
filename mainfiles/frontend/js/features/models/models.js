/**
 * Models feature - Model selection, provider listing, and live model fetching.
 */

import { getApiBaseUrl, apiFetch, streamChatCompletion } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml, bucketFor } from '../../shared/utils.js';
import {
  getProviders, setProviders, getModels, setModels, getSelectedModel, setSelectedModel,
  getActiveProviderFilter, setActiveProviderFilter, getReasoningEffort
} from '../../core/state.js';
import { PROVIDER_COLORS } from '../../shared/constants.js';

console.log('[Module] models.js loaded');

let elements = {};

/**
 * Initialize DOM element references.
 */
export function initElements() {
  elements = {
    modelSelector: $('#modelSelector'),
    modelSelectorBtn: $('#modelSelectorBtn'),
    modelDropdown: $('#modelDropdown'),
    modelSearch: $('#modelSearch'),
    modelSearchClear: $('#modelSearchClear'),
    modelList: $('#modelList'),
    modelProviderFilters: $('#modelProviderFilters'),
    connPulse: $('#connPulse'),
    onboardingHint: $('#onboardingHint'),
    providerStatusList: $('#providerStatusList'),
  };
}

/**
 * Load providers and models from backend.
 * This is the main entry point called on app start.
 */
export async function loadProvidersAndModels() {
  try {
    const [provRes, modelRes] = await Promise.all([
      apiFetch('/providers'),
      apiFetch('/models'),
    ]);

    const providers = await provRes.json();
    const models = await modelRes.json();

    setProviders(providers);
    setModels(models);

    if (!models.length) {
      handleNoModels();
      return;
    }

    elements.onboardingHint?.classList.add('hidden');

    // Re-enable send button in case it was disabled by handleNoModels()
    const sendBtnEl = document.getElementById('sendBtn');
    if (sendBtnEl) sendBtnEl.disabled = false;

    // Select first available model or previously selected
    const selected = getSelectedModel();
    let model = models.find((m) => m.id === selected?.id) || models[0];
    selectModel(model, { silent: true });

    renderModelList();
    renderProviderFilters();
    renderProviderStatusList();
    renderConnPulse();

    // Chat list is loaded by app.js via sidebarLoadChatList()
  } catch (err) {
    handleLoadError(err);
  }
}

/**
 * Handle case when no models are available.
 */
function handleNoModels() {
  setSelectedModel(null);
  elements.modelSelectorBtn.querySelector('.model-name').textContent = 'No model available';
  elements.modelSelectorBtn.querySelector('.model-provider').textContent = 'Link a provider or start Ollama';
  const sendBtn = document.getElementById('sendBtn');
  if (sendBtn) sendBtn.disabled = true;
  if (elements.modelSelectorBtn) elements.modelSelectorBtn.disabled = true;
  renderProviderFilters();
  renderModelList();
  renderProviderStatusList();
  renderConnPulse();
  elements.onboardingHint?.classList.remove('hidden');
  showToast({ type: 'info', title: 'No models available', message: 'Start Ollama with a downloaded model, or link a provider key in Settings.' });
}

/**
 * Handle provider/model load error.
 */
function handleLoadError(err) {
  setProviders([]);
  setModels([]);
  elements.modelSelectorBtn.querySelector('.model-name').textContent = 'Connection error';
  elements.modelSelectorBtn.querySelector('.model-provider').textContent = err.message;
  const sendBtn = document.getElementById('sendBtn');
  if (sendBtn) sendBtn.disabled = true;
  renderProviderFilters();
  renderModelList();
  renderProviderStatusList();
  renderConnPulse();
}

/**
 * Get provider display info.
 */
function getProviderInfo(providerId) {
  const status = getProviders().find((p) => p.id === providerId);
  return {
    label: status?.label || providerId,
    state: status?.state || 'offline',
    color: PROVIDER_COLORS[providerId] || '#9AA1AC',
  };
}

/**
 * Render model dropdown list.
 */

// Determine speed class for a model (placeholder logic)
function getModelSpeedClass(model) {
  const name = (model.name || "").toLowerCase();
  const ctx = model.context_window || model.max_tokens || 0;
  if (name.includes("haiku") || name.includes("mini") || name.includes("3.5") || ctx <= 8192) return "fast";
  if (name.includes("opus") || name.includes("4o") || name.includes("sonnet") || ctx > 32768) return "slow";
  return "medium";
}

// Format context window nicely
function formatContextSize(model) {
  const ctx = model.context_window || model.max_tokens || 0;
  if (ctx >= 1000000) return Math.round(ctx/1000000) + "M";
  if (ctx >= 1000) return Math.round(ctx/1000) + "k";
  return ctx.toString();
}

export function renderModelList(filter = '') {
  const q = filter.trim().toLowerCase();
  const list = elements.modelList;
  if (!list) return;

  list.innerHTML = '';

  const models = getModels();
  if (!models.length) {
    list.innerHTML = `<div class="no-results">No selectable models yet.<br><button class="btn-secondary" type="button" id="openProviderSettingsBtn">Link a provider key or start Ollama</button></div>`;
    $('#openProviderSettingsBtn')?.addEventListener('click', () => {
      closeModelDropdown();
      import('../features/settings/settings.js').then((m) => m.openSettings());
    });
    return;
  }

  const grouped = {};
  models
    .filter((m) => {
      const info = getProviderInfo(m.provider);
      return (getActiveProviderFilter() === 'all' || m.provider === getActiveProviderFilter())
        && (m.name.toLowerCase().includes(q) || info.label.toLowerCase().includes(q));
    })
    .forEach((m) => { (grouped[m.provider] ||= []).push(m); });

  const providerIds = Object.keys(grouped);
  if (!providerIds.length) {
    list.innerHTML = `<div class="no-results">No models match "${filter}"</div>`;
    return;
  }

  providerIds.forEach((pid) => {
    const info = getProviderInfo(pid);
    const label = document.createElement('div');
    label.className = 'model-group-label';
    label.textContent = `${info.label}${info.state !== 'online' ? (info.state === 'local' ? ' · local' : ' · not linked') : ''}`;
    list.appendChild(label);

    grouped[pid].forEach((m) => {
      const opt = document.createElement('button');
      opt.className = 'model-option' + (m.id === getSelectedModel()?.id ? ' selected' : '');
      opt.setAttribute('role', 'option');
      opt.setAttribute('aria-selected', String(m.id === getSelectedModel()?.id));
      var speedClass = getModelSpeedClass(m);
      var ctxStr = formatContextSize(m);
      opt.innerHTML = `
        <span class="provider-dot" style="--dot-color:${info.color}"></span>
        <span class="model-option-meta">
          <span class="model-option-name">${escapeHtml(m.name)}</span>
          <small>${escapeHtml(info.label)}${m.litellm_id ? ` · <code>${escapeHtml(m.litellm_id)}</code>` : ''}</small>
        </span>
        <span class="model-option-context">${ctxStr}</span>
        <span class="model-option-speed ${speedClass}"></span>
        <span class="status-dot ${info.state}" title="${info.state === 'online' ? 'Connected' : info.state === 'local' ? 'Local runtime' : 'Not linked'}"></span>
      `;
      opt.addEventListener('click', () => { selectModel(m); closeModelDropdown(); });
      list.appendChild(opt);
    });
  });
}

/**
 * Render provider filter buttons.
 */
export function renderProviderFilters() {
  const container = elements.modelProviderFilters;
  if (!container) return;

  const providerIds = [...new Set(getModels().map((m) => m.provider))];
  if (!providerIds.includes(getActiveProviderFilter())) setActiveProviderFilter('all');

  container.innerHTML = ['all', ...providerIds].map((providerId) => {
    const label = providerId === 'all' ? 'All providers' : getProviderInfo(providerId).label;
    return `<button type="button" class="${getActiveProviderFilter() === providerId ? 'active' : ''}" data-provider-filter="${escapeHtml(providerId)}">${escapeHtml(label)}</button>`;
  }).join('');

  container.querySelectorAll('[data-provider-filter]').forEach((button) => {
    button.addEventListener('click', () => {
      setActiveProviderFilter(button.dataset.providerFilter);
      renderProviderFilters();
      renderModelList(elements.modelSearch.value);
    });
  });
}

/**
 * Select a model and update UI.
 */
export function selectModel(model, opts = {}) {
  if (!model) return;
  setSelectedModel(model);
  const info = getProviderInfo(model.provider);
  elements.modelSelectorBtn.querySelector('.provider-dot').style.setProperty('--dot-color', info.color);
  elements.modelSelectorBtn.querySelector('.model-name').textContent = model.name;
  elements.modelSelectorBtn.querySelector('.model-provider').textContent = info.label;

  // Update status indicator on model selector button
  let statusEl = elements.modelSelectorBtn.querySelector('.status-dot');
  if (!statusEl) {
    statusEl = document.createElement('span');
    statusEl.className = 'status-dot';
    elements.modelSelectorBtn.appendChild(statusEl);
  }
  statusEl.className = `status-dot ${info.state}`;
  statusEl.title = info.state === 'online' ? 'Connected' : info.state === 'local' ? 'Local runtime' : 'Not linked';

  // Update reasoning effort indicator
  const reasoningEl = elements.modelSelectorBtn.querySelector('.reasoning-effort');
  const effort = getReasoningEffort();
  const hasReasoning = effort !== 'none';

  if (reasoningEl) {
    if (hasReasoning) {
      const labels = { low: 'Low', medium: 'Medium', high: 'High', extra_high: 'Extra High' };
      reasoningEl.innerHTML = `<i class="fa-solid fa-brain"></i> ${labels[effort] || effort}`;
      reasoningEl.classList.remove('hidden');
    } else {
      reasoningEl.classList.add('hidden');
    }
  }

  const sendBtn = document.getElementById('sendBtn');
  if (sendBtn) sendBtn.disabled = false;
  if (!opts.silent) renderModelList(elements.modelSearch.value);
}

/**
 * Open model dropdown.
 */
export function openModelDropdown() {
  elements.modelSelector.classList.add('open');
  elements.modelSelectorBtn.setAttribute('aria-expanded', 'true');
  elements.modelSearch.value = '';
  elements.modelSearchClear?.classList.add('hidden');
  renderModelList();
  setTimeout(() => elements.modelSearch.focus(), 50);
  document.addEventListener('click', outsideModelDropdown, true);
}

/**
 * Close model dropdown.
 */
export function closeModelDropdown() {
  elements.modelSelector.classList.remove('open');
  elements.modelSelectorBtn.setAttribute('aria-expanded', 'false');
  document.removeEventListener('click', outsideModelDropdown, true);
}

function outsideModelDropdown(e) {
  if (!elements.modelSelector?.contains(e.target)) closeModelDropdown();
}

/**
 * Render connection pulse indicator.
 */
export function renderConnPulse() {
  const providers = getProviders();
  const online = providers.filter((p) => p.state === 'online').length;
  const local = providers.filter((p) => p.state === 'local').length;

  // Fully replace connPulse content — clears the stale "Checking providers"
  // text node from the HTML so we don't get duplicate text.
  if (elements.connPulse) {
    const statusText = online + local > 0 ? `${online} online · ${local} local` : 'No providers linked';
    const dotColor = online > 0 ? 'var(--success)' : 'var(--text-tertiary)';
    elements.connPulse.innerHTML = `<span class="pulse-dot" style="background:${dotColor}"></span> ${statusText}`;
  }
}

/**
 * Render provider status list in sidebar.
 */
export function renderProviderStatusList() {
  const list = elements.providerStatusList;
  if (!list) return;

  const providers = getProviders();
  if (!providers.length) {
    list.innerHTML = `<div class="no-results">No providers linked yet. Open Settings to add provider API keys.</div>`;
    return;
  }

  list.innerHTML = providers.map((p) => `
    <div class="provider-status-row">
      <span class="provider-dot" style="--dot-color:${PROVIDER_COLORS[p.id] || '#9AA1AC'}"></span>
      <span class="provider-label">${escapeHtml(p.label)}</span>
      <span class="provider-state ${p.state}">${p.state === 'online' ? 'Connected' : p.state === 'local' ? 'Local runtime' : ''}</span>
    </div>`).join('');
}

/**
 * Initialize model selector event listeners.
 */
export function initModelSelector() {
  initElements();

  elements.modelSelectorBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    elements.modelSelector.classList.contains('open') ? closeModelDropdown() : openModelDropdown();
  });

  elements.modelSearch?.addEventListener('input', () => {
    renderModelList(elements.modelSearch.value);
    elements.modelSearchClear?.classList.toggle('hidden', elements.modelSearch.value.trim() === '');
  });

  elements.modelSearchClear?.addEventListener('click', () => {
    elements.modelSearch.value = '';
    elements.modelSearch.focus();
    elements.modelSearchClear.classList.add('hidden');
    renderModelList('');
  });
}