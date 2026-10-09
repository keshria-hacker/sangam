/**
 * Settings feature - Settings modal, appearance, provider keys, connection.
 */

import { getApiBaseUrl, setApiBaseUrl, apiFetch, apiGet, apiPost, apiPut, apiDelete } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
import {
  getSettings, setSettings, getProviders,
  getActiveChatId, setActiveChatId
} from '../../core/state.js';
import { DEFAULT_SETTINGS, CODE_THEME_URLS, PROVIDER_COLORS, STORAGE_KEYS } from '../../shared/constants.js';
import { loadProvidersAndModels } from '../models/models.js';
console.log('[Module] settings.js loaded');

// Dynamic import to break circular dependency with chat.js
let _chatModule = null;
async function getChatModule() {
  if (!_chatModule) {
    _chatModule = await import('../chat/chat.js');
  }
  return _chatModule;
}

let elements = {};

// Initialize DOM references
export function initElements() {
  elements = {
    settingsOverlay: $('#settingsOverlay'),
    closeSettings: $('#closeSettings'),
    settingsBtn: $('#settingsBtn'),
    themeOptions: $('#themeOptions'),
    fontSizeSegmented: $('#fontSizeSegmented'),
    chatWidthSegmented: $('#chatWidthSegmented'),
    codeThemeSelect: $('#codeThemeSelect'),
    animationToggle: $('#animationToggle'),
    themeToggle: $('#themeToggle'),
    toastContainer: $('#toastContainer'),
    confirmOverlay: $('#confirmOverlay'),
    confirmTitle: $('#confirmTitle'),
    confirmMessage: $('#confirmMessage'),
    confirmDelete: $('#confirmDelete'),
    confirmCancel: $('#confirmCancel'),
    backendUrlInput: $('#backendUrlInput'),
    testBackendBtn: $('#testBackendBtn'),
    responseStyleSegmented: $('#responseStyleSegmented'),
    formalitySegmented: $('#formalitySegmented'),
    expertiseSegmented: $('#expertiseSegmented'),
    logoutBtn: $('#logoutBtn'),
    profileAvatar: $('#profileAvatar'),
    profileName: $('#profileName'),
    providerStatusList: $('#providerStatusList'),
    providerKeyManager: $('#providerKeyManager'),
  };
}

/**
 * Apply settings to document.
 */
export function applySettings() {
  const s = getSettings();
  const root = document.documentElement;
  const effectiveTheme = s.theme === 'system'
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : s.theme;

  root.setAttribute('data-theme', effectiveTheme);
  const themeIcon = elements.themeToggle?.querySelector('i');
  if (themeIcon) themeIcon.className = effectiveTheme === 'dark' ? 'fa-solid fa-moon' : 'fa-solid fa-sun';
  document.body.setAttribute('data-font-size', s.fontSize);
  document.body.setAttribute('data-chat-width', s.chatWidth);
  document.body.setAttribute('data-animations', s.animations ? 'on' : 'off');

  // Auto-select matching code theme
  const codeTheme = effectiveTheme === 'dark' ? (s.codeThemeDark || 'github-dark') : (s.codeThemeLight || 'github');
  setCodeTheme(codeTheme);

  localStorage.setItem('sangam-settings', JSON.stringify(s));
}

/**
 * Set code highlight theme.
 */
export function setCodeTheme(theme) {
  const themeEl = $('#hljs-theme');
  if (themeEl && CODE_THEME_URLS[theme]) {
    themeEl.href = CODE_THEME_URLS[theme];
    document.body.setAttribute('data-code-theme', theme);
  }
}

/**
 * Load settings from localStorage.
 */
export function loadSettings() {
  try {
    const saved = localStorage.getItem('sangam-settings');
    if (saved) {
      const parsed = JSON.parse(saved);
      // Migrate old single codeTheme to dual preferences
      if (parsed.codeTheme && !parsed.codeThemeDark) {
        parsed.codeThemeDark = parsed.codeTheme;
        parsed.codeThemeLight = (['github-dark', 'atom-one-dark', 'nord', 'dracula'].includes(parsed.codeTheme))
          ? 'github' : parsed.codeTheme;
        delete parsed.codeTheme;
      }
      setSettings({ ...DEFAULT_SETTINGS, ...parsed });
    }
  } catch (e) { /* ignore */ }
}

/**
 * Sync settings UI with current state.
 */
export function syncSettingsUI() {
  const s = getSettings();
  $$('.theme-option').forEach(b => b.classList.toggle('active', b.dataset.theme === s.theme));
  $$('#fontSizeSegmented button').forEach(b => b.classList.toggle('active', b.dataset.size === s.fontSize));
  $$('#chatWidthSegmented button').forEach(b => b.classList.toggle('active', b.dataset.width === s.chatWidth));

  const effectiveTheme = s.theme === 'system'
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : s.theme;
  elements.codeThemeSelect.value = effectiveTheme === 'dark' ? (s.codeThemeDark || 'github-dark') : (s.codeThemeLight || 'github');
  elements.animationToggle.checked = s.animations;
  if (elements.backendUrlInput) elements.backendUrlInput.value = getApiBaseUrl();
}

/**
 * Open settings modal.
 */
/**
 * Phase 4: server-persisted response style preferences.
 * Loaded when settings open, saved on segment click.
 */
export async function loadUserPreferences() {
  try {
    const pref = await (await apiGet('/user/preferences')).json();
    setActiveSegment(elements.responseStyleSegmented, pref.response_style || 'balanced', 'style');
    setActiveSegment(elements.formalitySegmented, pref.formality || 'neutral', 'tone');
    setActiveSegment(elements.expertiseSegmented, pref.expertise_level || 'general', 'expertise');
  } catch (err) {
    console.warn('Could not load preferences:', err.message);
  }
}

function setActiveSegment(container, value, attr) {
  if (!container) return;
  container.querySelectorAll('button').forEach((b) => {
    b.classList.toggle('active', b.dataset[attr] === value);
  });
}

async function saveUserPreference(patch) {
  try {
    // The PUT accepts the full object; send current selections + the change.
    const body = {
      response_style: elements.responseStyleSegmented?.querySelector('button.active')?.dataset.style || 'balanced',
      formality: elements.formalitySegmented?.querySelector('button.active')?.dataset.tone || 'neutral',
      expertise_level: elements.expertiseSegmented?.querySelector('button.active')?.dataset.expertise || 'general',
      ...patch,
    };
    await apiPut('/user/preferences', body);
    showToast({ type: 'success', title: 'Response style saved' });
  } catch (err) {
    showToast({ type: 'error', title: 'Could not save preference', message: err.message });
  }
}

export function openSettings() {
  elements.settingsTrigger = document.activeElement;
  syncSettingsUI();
  loadAndRenderProviderKeys();
  loadUserPreferences();
  elements.settingsOverlay?.classList.remove('hidden');
  updateBodyScrollLock();
  setTimeout(() => elements.closeSettings?.focus(), 0);
  // Memory section (lazy import to keep settings.js lean)
  import('./memory-ui.js').then((m) => {
    m.initMemorySettings();
    m.refreshMemorySection();
  }).catch(() => {});
  // Voice section (only populated when the backend voice flag is on)
  import('../voice/voice.js').then((m) => {
    if (m.isVoiceEnabled()) {
      document.getElementById('voiceSettingsSectionWrap')?.classList.remove('hidden');
      m.refreshVoiceSettings();
    }
  }).catch(() => {});
  loadFeatureToggles();
}

/**
 * Features section: load current flags and wire the toggles.
 */
async function loadFeatureToggles() {
  const wrap = document.getElementById('featureToggles');
  if (!wrap) return;
  let features = {};
  try {
    const data = await (await apiFetch('/features')).json();
    features = data.features || {};
  } catch {
    features = {};
  }
  wrap.querySelectorAll('[data-feature]').forEach((btn) => {
    const on = !!features[btn.dataset.feature];
    setFeatureToggle(btn, on);
  });
}

function setFeatureToggle(btn, on) {
  btn.classList.toggle('active', on);
  btn.setAttribute('aria-pressed', String(on));
  const label = btn.querySelector('span');
  if (label) label.textContent = on ? 'On' : 'Off';
}

async function onFeatureToggleClick(e) {
  const btn = e.target.closest('[data-feature]');
  if (!btn || btn.disabled) return;
  const name = btn.dataset.feature;
  const want = !btn.classList.contains('active');
  btn.disabled = true;
  try {
    const res = await apiPost(`/features/${encodeURIComponent(name)}`, { enabled: want });
    const data = await res.json();
    setFeatureToggle(btn, !!data.enabled);
    refreshFeatureButtons(data.features || {});
    // Re-run the feature's init so its module state (and button wiring) syncs.
    const initMap = {
      voice: ['../voice/voice.js', 'initVoice'],
      image_gen: ['../image/image.js', 'initImage'],
      multi_agent: ['../teams/teams.js', 'initTeams'],
      learning: ['../learn/learn.js', 'initLearn'],
      analytics: ['../analytics/analytics.js', 'initAnalytics'],
    };
    const [modPath, fn] = initMap[name] || [];
    if (modPath) {
      import(modPath).then((m) => m[fn]?.()).catch(() => {});
    }
    showToast({ type: 'success', title: `Feature ${want ? 'enabled' : 'disabled'}`, message: name.replace(/_/g, ' ') });
  } catch (err) {
    showToast({ type: 'error', title: 'Could not toggle feature', message: err.message });
  } finally {
    btn.disabled = false;
  }
}

/**
 * Show/hide feature buttons across the UI after a flag change.
 */
export function refreshFeatureButtons(features) {
  const show = (id, on) => document.getElementById(id)?.classList.toggle('hidden', !on);
  show('teamsBtn', !!features.multi_agent);
  show('learnBtn', !!features.learning);
  show('analyticsBtn', !!features.analytics);
  show('micBtn', !!features.voice);
  show('imageBtn', !!features.image_gen);
  show('imagesBtn', !!features.image_gen);
  // Voice settings section follows the voice flag.
  document.getElementById('voiceSettingsSectionWrap')?.classList.toggle('hidden', !features.voice);
  // Tool picker respects flags too
  import('../tabs/tabs.js').then((m) => m.invalidateFeatureCache?.()).catch(() => {});
}

/**
 * Close settings modal.
 */
export function closeSettingsModal() {
  elements.settingsOverlay?.classList.add('hidden');
  elements.settingsTrigger?.focus();
  updateBodyScrollLock();
}

/**
 * Get provider key entries for UI.
 */
function getProviderKeyEntries(keys = []) {
  const entries = Array.isArray(keys) ? keys : [];
  if (entries.length === 0) {
    // Fallback when backend unreachable
    return [
      { provider_id: 'anthropic', label: 'Anthropic', linked: false, masked_key: null },
      { provider_id: 'openai', label: 'OpenAI', linked: false, masked_key: null },
      { provider_id: 'nvidia', label: 'NVIDIA NIM', linked: false, masked_key: null },
      { provider_id: 'together', label: 'Together AI', linked: false, masked_key: null },
      { provider_id: 'groq', label: 'Groq', linked: false, masked_key: null },
      { provider_id: 'openrouter', label: 'OpenRouter', linked: false, masked_key: null },
      { provider_id: 'deepseek', label: 'DeepSeek', linked: false, masked_key: null },
      { provider_id: 'mistral', label: 'Mistral', linked: false, masked_key: null },
      { provider_id: 'gemini', label: 'Gemini', linked: false, masked_key: null },
      { provider_id: 'omniroute', label: 'OmniRoute', linked: false, masked_key: null },
    ];
  }
  return entries.map(k => ({
    provider_id: k.provider_id,
    linked: Boolean(k.linked),
    masked_key: k.masked_key || null,
    label: k.label || k.provider_id,
  }));
}

/**
 * Load and render provider keys from backend.
 */
async function loadAndRenderProviderKeys() {
  const container = document.getElementById('providerKeyManager');
  if (!container) return;
  renderProviderKeyManager([]);

  try {
    const res = await apiFetch('/settings/providers');
    const keys = await res.json();
    renderProviderKeyManager(keys);
  } catch (err) {
    renderProviderKeyManager([]);
    showToast({ type: 'info', title: 'Provider keys', message: 'Showing manual entry boxes; backend unavailable.' });
  }
}

/**
 * Render provider key manager UI.
 */
function renderProviderKeyManager(keys) {
  const container = document.getElementById('providerKeyManager');
  if (!container) return;

  const entries = getProviderKeyEntries(keys);
  container.innerHTML = entries.map(k => {
    const color = PROVIDER_COLORS[k.provider_id] || '#9AA1AC';
    const isLinked = Boolean(k.linked);
    const currentLabel = isLinked ? (k.masked_key || 'Linked') : 'Not linked';
    return `
      <div class="provider-status-row" data-provider="${k.provider_id}">
        <span class="provider-dot" style="--dot-color:${color}"></span>
        <span class="provider-label">${escapeHtml(k.label)}</span>
        <span class="provider-state ${isLinked ? 'online' : 'offline'}" style="font-family:var(--font-mono);">${escapeHtml(currentLabel)}</span>
        <input type="password" class="provider-key-input" placeholder="${isLinked ? 'Paste a new key to replace it…' : 'Paste API key…'}"
               data-provider="${k.provider_id}">
        <button class="icon-btn save-key-btn" title="${isLinked ? 'Replace key' : 'Save key'}" aria-label="${isLinked ? 'Replace key' : 'Save key'}" data-provider="${k.provider_id}">
          <i class="fa-solid ${isLinked ? 'fa-pen' : 'fa-check'}"></i>
        </button>
        ${isLinked ? `<button class="icon-btn remove-key-btn" title="Remove key" aria-label="Remove key" data-provider="${k.provider_id}"><i class="fa-solid fa-trash"></i></button>` : ''}
        ${isLinked ? `<button class="icon-btn refresh-models-btn" title="Fetch models from API" aria-label="Refresh models" data-provider="${k.provider_id}"><i class="fa-solid fa-rotate"></i></button>` : ''}
      </div>`;
  }).join('');

  // Save key handlers
  container.querySelectorAll('.save-key-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const pid = btn.dataset.provider;
      const input = container.querySelector(`.provider-key-input[data-provider="${pid}"]`);
      const value = input.value.trim();
      if (!value) { showToast({ type: 'info', message: 'Paste a key first.' }); return; }
      btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i>`;
      try {
        await apiFetch(`/settings/providers/${pid}/key`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ api_key: value }),
        });
        showToast({ type: 'success', title: 'Provider linked', message: `${pid} is ready to use.` });
        // Refresh models and provider status
        await loadProvidersAndModels();
        await loadAndRenderProviderKeys();
      } catch (err) {
        showToast({ type: 'error', title: 'Could not save key', message: err.message });
        btn.innerHTML = `<i class="fa-solid fa-check"></i>`;
      }
    });
  });

  // Remove key handlers
  container.querySelectorAll('.remove-key-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const pid = btn.dataset.provider;
      try {
        await apiFetch(`/settings/providers/${pid}/key`, { method: 'DELETE' });
        showToast({ type: 'info', message: `${pid} key removed.` });
        await loadProvidersAndModels();
        await loadAndRenderProviderKeys();
      } catch (err) {
        showToast({ type: 'error', title: 'Could not remove key', message: err.message });
      }
    });
  });

  // Refresh models handlers
  container.querySelectorAll('.refresh-models-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      const pid = btn.dataset.provider;
      btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i>`;
      try {
        const resp = await apiFetch(`/settings/providers/${pid}/models/refresh`);
        const data = await resp.json();
        const count = data.count ?? 0;
        showToast({
          type: 'success',
          title: pid,
          message: count === 1 ? 'Fetched 1 model from the API' : `Fetched ${count} models from the API`,
        });
        await loadProvidersAndModels();
        await loadAndRenderProviderKeys();
      } catch (err) {
        showToast({ type: 'error', title: 'Could not refresh models', message: err.message });
        btn.innerHTML = `<i class="fa-solid fa-rotate"></i>`;
      }
    });
  });
}

/**
 * Render provider status list in settings.
 */
export function renderProviderStatusList() {
  const providers = getProviders();
  const list = elements.providerStatusList;
  if (!list) return;

  if (!providers.length) {
    list.innerHTML = `<div class="no-results">No providers linked yet. Open Settings to add provider API keys.</div>`;
    return;
  }

  list.innerHTML = providers.map(p => `
    <div class="provider-status-row">
      <span class="provider-dot" style="--dot-color:${PROVIDER_COLORS[p.id] || '#9AA1AC'}"></span>
      <span class="provider-label">${escapeHtml(p.label)}</span>
      <span class="provider-state ${p.state}">${p.state === 'online' ? 'Connected' : p.state === 'local' ? 'Local runtime' : ''}</span>
    </div>`).join('');
}

/**
 * Scroll lock for modals.
 */
let _scrollLockCount = 0;
function updateBodyScrollLock() {
  const anyOpen = !elements.settingsOverlay.classList.contains('hidden') ||
                  !elements.confirmOverlay.classList.contains('hidden') ||
                  !document.getElementById('skillsOverlay')?.classList.contains('hidden');
  _scrollLockCount = anyOpen ? 1 : 0;
  document.body.style.overflow = anyOpen ? 'hidden' : '';
}

/**
 * Initialize settings event listeners.
 */
export function initSettings() {
  initElements();

  // Settings button
  elements.settingsBtn?.addEventListener('click', openSettings);
  elements.closeSettings?.addEventListener('click', closeSettingsModal);
  elements.settingsOverlay?.addEventListener('click', (e) => { if (e.target === elements.settingsOverlay) closeSettingsModal(); });

  // OmniRoute gateway (Sangam-native)
  initOmnirouteSection();

  // Feature toggles (delegated)
  document.getElementById('featureToggles')?.addEventListener('click', onFeatureToggleClick);

  // Theme options
  elements.themeOptions?.addEventListener('click', (e) => {
    const b = e.target.closest('.theme-option');
    if (!b) return;
    setSettings({ ...getSettings(), theme: b.dataset.theme });
    syncSettingsUI();
    applySettings();
  });

  // Font size
  elements.fontSizeSegmented?.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    setSettings({ ...getSettings(), fontSize: b.dataset.size });
    syncSettingsUI();
    applySettings();
  });

  // Chat width
  elements.chatWidthSegmented?.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    setSettings({ ...getSettings(), chatWidth: b.dataset.width });
    syncSettingsUI();
    applySettings();
  });

  // Phase 4: response style preferences (server-persisted)
  elements.responseStyleSegmented?.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    setActiveSegment(elements.responseStyleSegmented, b.dataset.style, 'style');
    saveUserPreference({ response_style: b.dataset.style });
  });
  elements.formalitySegmented?.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    setActiveSegment(elements.formalitySegmented, b.dataset.tone, 'tone');
    saveUserPreference({ formality: b.dataset.tone });
  });
  elements.expertiseSegmented?.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    setActiveSegment(elements.expertiseSegmented, b.dataset.expertise, 'expertise');
    saveUserPreference({ expertise_level: b.dataset.expertise });
  });

  // Code theme
  elements.codeThemeSelect?.addEventListener('change', async () => {
    const s = getSettings();
    const eff = s.theme === 'system'
      ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
      : s.theme;
    const newSettings = { ...s };
    if (eff === 'dark') newSettings.codeThemeDark = elements.codeThemeSelect.value;
    else newSettings.codeThemeLight = elements.codeThemeSelect.value;
    setSettings(newSettings);
    applySettings();
    // Re-render messages for code block theme change
    const chatModule = await getChatModule();
    chatModule.renderMessages();
  });

  // Animations
  elements.animationToggle?.addEventListener('change', () => {
    setSettings({ ...getSettings(), animations: elements.animationToggle.checked });
    applySettings();
  });

  // Theme toggle in header
  elements.themeToggle?.addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme');
    setSettings({ ...getSettings(), theme: cur === 'dark' ? 'light' : 'dark' });
    applySettings();
  });

  // Settings tabs
  document.querySelector('.settings-tabs')?.addEventListener('click', (e) => {
    const tab = e.target.closest('.settings-tab');
    if (!tab) return;
    const tabId = tab.dataset.tab;
    document.querySelectorAll('.settings-tab').forEach(t => {
      const isActive = t.dataset.tab === tabId;
      t.classList.toggle('active', isActive);
      t.setAttribute('aria-selected', isActive);
    });
    document.querySelectorAll('.settings-tabpanel').forEach(p => {
      p.hidden = p.dataset.tabpanel !== tabId;
    });
    if (tabId === 'features') loadFeatureToggles();
  });

  // Backend URL change
  elements.backendUrlInput?.addEventListener('change', (e) => {
    setApiBaseUrl(e.target.value.trim());
    showToast({ type: 'info', message: 'Backend URL updated. Reconnecting…' });
    loadProvidersAndModels();
  });

  // Test backend button
  elements.testBackendBtn?.addEventListener('click', async () => {
    const resultEl = document.getElementById('backendTestResult');
    if (!resultEl) return;
    resultEl.textContent = 'Testing…';
    resultEl.style.color = 'var(--text-tertiary)';
    try {
      const res = await apiFetch('/health');
      const data = await res.json();
      resultEl.textContent = `Connected — ${data.app}`;
      resultEl.style.color = 'var(--success)';
    } catch (err) {
      resultEl.textContent = err.message;
      resultEl.style.color = 'var(--danger)';
    }
  });

  // NOTE: #logoutBtn is bound by auth.js initProfilePopup() (confirm + logout()
  // + reload). Binding it here as well fired a second /auth/logout against the
  // already-deleted session (spurious 401) and double-reloaded the page.

  // Focus trap in settings modal
  elements.settingsOverlay?.addEventListener('keydown', (e) => {
    if (e.key !== 'Tab') return;
    if (elements.settingsOverlay.classList.contains('hidden')) return;
    const focusable = [...elements.settingsOverlay.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"]):not([disabled])'
    )].filter(el => el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });

  // Escape closes settings
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeSettingsModal();
      // Also close other modals
    }
  });
}
/* ============ OmniRoute gateway (Sangam-native UI) ============ */

async function loadOmnirouteStatus() {
  const line = document.getElementById('omnirouteStatusLine');
  const endpointInput = document.getElementById('omnirouteEndpoint');
  try {
    const res = await (await apiFetch('/omniroute/status')).json();
    if (endpointInput && !endpointInput.dataset.touched) endpointInput.value = res.endpoint || '';
    if (!line) return;
    if (!res.has_key) {
      line.textContent = 'No API key saved — add one to enable auto model discovery.';
      line.className = '';
    } else if (!res.reachable) {
      line.textContent = `Key saved, but gateway not reachable at ${res.endpoint}.`;
      line.className = 'status-warn';
    } else {
      line.textContent = `${res.model_count} models available via OmniRoute.`;
      line.className = 'status-ok';
    }
  } catch {
    if (line) line.textContent = 'Could not reach backend.';
  }
}

function initOmnirouteSection() {
  const section = document.getElementById('omnirouteSection');
  if (!section || section.dataset.wired) return;
  section.dataset.wired = '1';

  const endpointInput = document.getElementById('omnirouteEndpoint');
  endpointInput?.addEventListener('input', () => { endpointInput.dataset.touched = '1'; });

  section.querySelectorAll('.omniroute-presets button').forEach((b) => {
    b.addEventListener('click', () => {
      endpointInput.value = b.dataset.endpoint;
      endpointInput.dataset.touched = '1';
    });
  });

  document.getElementById('omnirouteSave')?.addEventListener('click', async () => {
    const endpoint = endpointInput?.value.trim();
    const apiKey = document.getElementById('omnirouteKey')?.value.trim();
    if (!endpoint && !apiKey) {
      showToast({ type: 'info', message: 'Enter an endpoint or API key first.' });
      return;
    }
    try {
      await apiPost('/omniroute/config', { endpoint: endpoint || null, api_key: apiKey || null });
      document.getElementById('omnirouteKey').value = '';
      showToast({ type: 'success', title: 'OmniRoute saved' });
      loadOmnirouteStatus();
    } catch (err) {
      showToast({ type: 'error', title: 'Save failed', message: err?.message || String(err) });
    }
  });

  document.getElementById('omnirouteSync')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const res = await (await apiPost('/omniroute/sync', {})).json();
      showToast({ type: 'success', title: `${res.count} models synced`, message: 'They now appear in the model selector.' });
      loadOmnirouteStatus();
      // Refresh the model list so new models appear immediately
      window.dispatchEvent(new CustomEvent('sangam:models-changed'));
    } catch (err) {
      showToast({ type: 'error', title: 'Sync failed', message: err?.message || String(err) });
    } finally {
      btn.disabled = false;
    }
  });

  loadOmnirouteStatus();
}
