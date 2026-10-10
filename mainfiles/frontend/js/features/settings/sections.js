/**
 * Settings custom sections — migrated from the deleted legacy settings modal
 * (Phase 8 B2). These render below the schema-driven rows in their category:
 *
 * - 'models'    → provider keys manager + OmniRoute gateway + routes UI
 * - 'knowledge' → memory list (delegates to memory-ui.js)
 * - 'voice'     → voice settings (delegates to voice.js)
 * - 'workspace' → feature toggles
 */
import { apiFetch, apiPost } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
import { PROVIDER_COLORS } from '../../shared/constants.js';
import { loadProvidersAndModels } from '../models/models.js';

console.log('[Module] settings/sections.js loaded');

// ---------------------------------------------------------------------------
// Provider keys (was: settings.js loadAndRenderProviderKeys)
// ---------------------------------------------------------------------------

const FALLBACK_PROVIDERS = [
  'anthropic', 'openai', 'nvidia', 'together', 'groq',
  'openrouter', 'deepseek', 'mistral', 'gemini', 'omniroute',
];

function providerLabel(pid) {
  const labels = {
    anthropic: 'Anthropic', openai: 'OpenAI', nvidia: 'NVIDIA NIM',
    together: 'Together AI', groq: 'Groq', openrouter: 'OpenRouter',
    deepseek: 'DeepSeek', mistral: 'Mistral', gemini: 'Gemini',
    omniroute: 'OmniRoute',
  };
  return labels[pid] || pid;
}

export async function renderProviderKeysSection(container) {
  const wrap = document.createElement('div');
  wrap.className = 'sp-custom-section';
  wrap.innerHTML = `<h3 class="sp-section-title"><i class="fa-solid fa-key"></i> Provider API keys</h3>
    <div class="sp-section-body" data-pk-list><p class="settings-hint">Loading…</p></div>`;
  container.appendChild(wrap);
  const list = wrap.querySelector('[data-pk-list]');

  let keys = [];
  try {
    keys = await (await apiFetch('/settings/providers')).json();
    if (!Array.isArray(keys)) keys = [];
  } catch {
    keys = [];
    showToast({ type: 'info', title: 'Provider keys', message: 'Backend unavailable — showing manual entry boxes.' });
  }

  const entries = keys.length ? keys : FALLBACK_PROVIDERS.map((pid) => ({
    provider_id: pid, label: providerLabel(pid), linked: false, masked_key: null,
  }));

  list.innerHTML = entries.map((k) => {
    const pid = k.provider_id;
    const color = PROVIDER_COLORS[pid] || '#9AA1AC';
    const linked = Boolean(k.linked);
    const state = linked ? (k.masked_key || 'Linked') : 'Not linked';
    return `
      <div class="provider-status-row" data-provider="${escapeHtml(pid)}">
        <span class="provider-dot" style="--dot-color:${color}"></span>
        <span class="provider-label">${escapeHtml(k.label || providerLabel(pid))}</span>
        <span class="provider-state ${linked ? 'online' : 'offline'}" style="font-family:var(--font-mono);">${escapeHtml(state)}</span>
        <input type="password" class="provider-key-input" placeholder="${linked ? 'Paste a new key to replace it…' : 'Paste API key…'}"
               data-provider="${escapeHtml(pid)}" aria-label="${escapeHtml(providerLabel(pid))} API key">
        <button class="icon-btn save-key-btn" title="${linked ? 'Replace key' : 'Save key'}" aria-label="${linked ? 'Replace key' : 'Save key'}" data-provider="${escapeHtml(pid)}">
          <i class="fa-solid ${linked ? 'fa-pen' : 'fa-check'}"></i>
        </button>
        ${linked ? `<button class="icon-btn remove-key-btn" title="Remove key" aria-label="Remove key" data-provider="${escapeHtml(pid)}"><i class="fa-solid fa-trash"></i></button>` : ''}
        ${linked ? `<button class="icon-btn refresh-models-btn" title="Fetch models from API" aria-label="Refresh models" data-provider="${escapeHtml(pid)}"><i class="fa-solid fa-rotate"></i></button>` : ''}
      </div>`;
  }).join('');

  list.querySelectorAll('.save-key-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const pid = btn.dataset.provider;
      const input = list.querySelector(`.provider-key-input[data-provider="${pid}"]`);
      const value = input.value.trim();
      if (!value) { showToast({ type: 'info', message: 'Paste a key first.' }); return; }
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
      try {
        await apiFetch(`/settings/providers/${encodeURIComponent(pid)}/key`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ api_key: value }),
        });
        showToast({ type: 'success', title: 'Provider linked', message: `${providerLabel(pid)} is ready to use.` });
        await loadProvidersAndModels();
        wrap.remove();
        renderProviderKeysSection(container);
      } catch (err) {
        showToast({ type: 'error', title: 'Could not save key', message: err?.message || String(err) });
        btn.innerHTML = '<i class="fa-solid fa-check"></i>';
      }
    });
  });

  list.querySelectorAll('.remove-key-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const pid = btn.dataset.provider;
      try {
        await apiFetch(`/settings/providers/${encodeURIComponent(pid)}/key`, { method: 'DELETE' });
        showToast({ type: 'info', message: `${providerLabel(pid)} key removed.` });
        await loadProvidersAndModels();
        wrap.remove();
        renderProviderKeysSection(container);
      } catch (err) {
        showToast({ type: 'error', title: 'Could not remove key', message: err?.message || String(err) });
      }
    });
  });

  list.querySelectorAll('.refresh-models-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const pid = btn.dataset.provider;
      btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
      try {
        const data = await (await apiFetch(`/settings/providers/${encodeURIComponent(pid)}/models/refresh`)).json();
        const count = data.count ?? 0;
        showToast({ type: 'success', title: providerLabel(pid),
          message: count === 1 ? 'Fetched 1 model from the API' : `Fetched ${count} models from the API` });
        await loadProvidersAndModels();
      } catch (err) {
        showToast({ type: 'error', title: 'Could not refresh models', message: err?.message || String(err) });
        btn.innerHTML = '<i class="fa-solid fa-rotate"></i>';
      }
    });
  });
}

// ---------------------------------------------------------------------------
// OmniRoute gateway (was: settings.js initOmnirouteSection)
// ---------------------------------------------------------------------------

export function renderOmnirouteSection(container) {
  const wrap = document.createElement('div');
  wrap.className = 'sp-custom-section';
  wrap.innerHTML = `
    <h3 class="sp-section-title"><i class="fa-solid fa-cloud"></i> OmniRoute gateway</h3>
    <div class="sp-section-body">
      <p class="settings-hint">Point Sangam at an OpenAI-compatible gateway to auto-discover models.</p>
      <div class="omniroute-presets" style="display:flex;gap:8px;margin-bottom:8px">
        <button class="btn-secondary btn-sm" type="button" data-endpoint="http://localhost:8080/v1">Local</button>
        <button class="btn-secondary btn-sm" type="button" data-endpoint="https://api.openai.com/v1">OpenAI</button>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <input class="provider-key-input" data-or-endpoint placeholder="Gateway endpoint (https://…/v1)" aria-label="OmniRoute endpoint" style="flex:2;min-width:220px">
        <input class="provider-key-input" data-or-key type="password" placeholder="API key" aria-label="OmniRoute API key" style="flex:1;min-width:140px">
      </div>
      <div style="display:flex;gap:8px;margin-top:8px;align-items:center">
        <button class="btn-primary btn-sm" type="button" data-or-save>Save</button>
        <button class="btn-secondary btn-sm" type="button" data-or-sync>Sync models</button>
        <span class="settings-hint" data-or-status></span>
      </div>
    </div>`;
  container.appendChild(wrap);

  const endpointInput = wrap.querySelector('[data-or-endpoint]');
  const keyInput = wrap.querySelector('[data-or-key]');
  const statusLine = wrap.querySelector('[data-or-status]');

  async function loadStatus() {
    try {
      const res = await (await apiFetch('/omniroute/status')).json();
      if (!endpointInput.dataset.touched) endpointInput.value = res.endpoint || '';
      if (!res.has_key) statusLine.textContent = 'No API key saved.';
      else if (!res.reachable) statusLine.textContent = `Key saved, gateway not reachable at ${res.endpoint}.`;
      else statusLine.textContent = `${res.model_count} models available via OmniRoute.`;
    } catch {
      statusLine.textContent = 'Could not reach backend.';
    }
  }

  endpointInput.addEventListener('input', () => { endpointInput.dataset.touched = '1'; });
  wrap.querySelectorAll('.omniroute-presets button').forEach((b) => {
    b.addEventListener('click', () => {
      endpointInput.value = b.dataset.endpoint;
      endpointInput.dataset.touched = '1';
    });
  });
  wrap.querySelector('[data-or-save]').addEventListener('click', async () => {
    const endpoint = endpointInput.value.trim();
    const apiKey = keyInput.value.trim();
    if (!endpoint && !apiKey) {
      showToast({ type: 'info', message: 'Enter an endpoint or API key first.' });
      return;
    }
    try {
      await apiPost('/omniroute/config', { endpoint: endpoint || null, api_key: apiKey || null });
      keyInput.value = '';
      showToast({ type: 'success', title: 'OmniRoute saved' });
      loadStatus();
    } catch (err) {
      showToast({ type: 'error', title: 'Save failed', message: err?.message || String(err) });
    }
  });
  wrap.querySelector('[data-or-sync]').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const res = await (await apiPost('/omniroute/sync', {})).json();
      showToast({ type: 'success', title: `${res.count} models synced`,
        message: 'They now appear in the model selector.' });
      loadStatus();
      window.dispatchEvent(new CustomEvent('sangam:models-changed'));
    } catch (err) {
      showToast({ type: 'error', title: 'Sync failed', message: err?.message || String(err) });
    } finally {
      btn.disabled = false;
    }
  });

  loadStatus();
}

// ---------------------------------------------------------------------------
// Feature toggles (was: settings.js loadFeatureToggles — the old "Features" tab)
// ---------------------------------------------------------------------------

export async function renderFeatureTogglesSection(container) {
  const wrap = document.createElement('div');
  wrap.className = 'sp-custom-section';
  wrap.innerHTML = `<h3 class="sp-section-title"><i class="fa-solid fa-puzzle-piece"></i> Features</h3>
    <div class="sp-section-body" data-ft-list><p class="settings-hint">Loading…</p></div>`;
  container.appendChild(wrap);
  const list = wrap.querySelector('[data-ft-list]');

  let features = {};
  try {
    features = (await (await apiFetch('/features')).json()).features || {};
  } catch { /* offline */ }

  const defs = [
    ['voice', 'Voice', 'Microphone dictation and text-to-speech'],
    ['image_gen', 'Image generation', 'Image Studio and generation tools'],
    ['multi_agent', 'Multi-agent teams', 'Agent teams with fan-out/fan-in'],
    ['learning', 'Learning mode', 'Interactive lessons and tutor'],
    ['analytics', 'Analytics', 'Local-first usage insights (opt-in)'],
  ];
  list.innerHTML = defs.map(([name, label, desc]) => `
    <div class="sp-setting-row">
      <div class="sp-setting-info">
        <div class="sp-setting-label">${escapeHtml(label)}</div>
        <div class="sp-setting-desc">${escapeHtml(desc)}</div>
      </div>
      <div class="sp-setting-right">
        <button class="btn-secondary btn-sm" type="button" data-feature="${name}"
                aria-pressed="${!!features[name]}">${features[name] ? 'On' : 'Off'}</button>
      </div>
    </div>`).join('');

  list.querySelectorAll('[data-feature]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const name = btn.dataset.feature;
      const want = btn.getAttribute('aria-pressed') !== 'true';
      btn.disabled = true;
      try {
        const res = await apiPost(`/features/${encodeURIComponent(name)}`, { enabled: want });
        const data = await res.json();
        const on = !!data.enabled;
        btn.setAttribute('aria-pressed', String(on));
        btn.textContent = on ? 'On' : 'Off';
        document.dispatchEvent(new CustomEvent('sangam:features-changed',
          { detail: { features: data.features || {} } }));
        const initMap = {
          voice: ['../voice/voice.js', 'initVoice'],
          image_gen: ['../image/image.js', 'initImage'],
          multi_agent: ['../teams/teams.js', 'initTeams'],
          learning: ['../learn/learn.js', 'initLearn'],
          analytics: ['../analytics/analytics.js', 'initAnalytics'],
        };
        const [modPath, fn] = initMap[name] || [];
        if (modPath) import(modPath).then((m) => m[fn]?.()).catch(() => {});
        showToast({ type: 'success', title: `Feature ${want ? 'enabled' : 'disabled'}` });
      } catch (err) {
        showToast({ type: 'error', title: 'Could not toggle feature', message: err?.message || String(err) });
      } finally {
        btn.disabled = false;
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Memory section (delegates to memory-ui.js)
// ---------------------------------------------------------------------------

export function renderMemorySection(container) {
  const wrap = document.createElement('div');
  wrap.className = 'sp-custom-section';
  wrap.innerHTML = `<h3 class="sp-section-title"><i class="fa-solid fa-brain"></i> Memory</h3>
    <div class="sp-section-body" data-mem-body><p class="settings-hint">Loading…</p></div>`;
  container.appendChild(wrap);
  import('./memory-ui.js').then((m) => {
    const body = wrap.querySelector('[data-mem-body]');
    body.innerHTML = '';
    m.renderMemorySection(body);
  }).catch(() => {
    wrap.querySelector('[data-mem-body]').innerHTML =
      '<p class="settings-hint">Memory settings unavailable.</p>';
  });
}

// ---------------------------------------------------------------------------
// Voice section (delegates to voice.js)
// ---------------------------------------------------------------------------

export function renderVoiceSection(container) {
  const wrap = document.createElement('div');
  wrap.className = 'sp-custom-section';
  wrap.innerHTML = `<h3 class="sp-section-title"><i class="fa-solid fa-microphone"></i> Voice</h3>
    <div class="sp-section-body" data-voice-body><p class="settings-hint">Loading…</p></div>`;
  container.appendChild(wrap);
  import('../voice/voice.js').then((m) => {
    const body = wrap.querySelector('[data-voice-body]');
    body.innerHTML = '';
    if (m.isVoiceEnabled()) m.renderVoiceSettings(body);
    else body.innerHTML = '<p class="settings-hint">Enable the Voice feature (Workspace → Features) to configure voice.</p>';
  }).catch(() => {
    wrap.querySelector('[data-voice-body]').innerHTML =
      '<p class="settings-hint">Voice settings unavailable.</p>';
  });
}

// ---------------------------------------------------------------------------
// Phase 8 B7: merged-away tabs as Settings sub-pages.
// ---------------------------------------------------------------------------

/** Routes UI inside Settings → Models & Routing. */
export function renderRoutesSection(container) {
  const wrap = document.createElement('div');
  wrap.className = 'sp-custom-section';
  wrap.innerHTML = `<h3 class="sp-section-title"><i class="fa-solid fa-route"></i> Routing rules</h3>
    <div class="sp-section-body" data-routes-body><p class="settings-hint">Loading…</p></div>`;
  container.appendChild(wrap);
  import('../routing/routes.js').then((m) => {
    const body = wrap.querySelector('[data-routes-body]');
    body.innerHTML = '';
    if (m.renderRoutesTab) m.renderRoutesTab(body);
    else body.innerHTML = '<p class="settings-hint">Routes UI unavailable.</p>';
  }).catch(() => {
    wrap.querySelector('[data-routes-body]').innerHTML =
      '<p class="settings-hint">Routes UI unavailable.</p>';
  });
}

/** Doctor inside Settings → Models & Routing. */
export function renderDoctorSection(container) {
  const wrap = document.createElement('div');
  wrap.className = 'sp-custom-section';
  wrap.innerHTML = `<h3 class="sp-section-title"><i class="fa-solid fa-stethoscope"></i> Doctor</h3>
    <div class="sp-section-body" data-doctor-body><p class="settings-hint">Loading…</p></div>`;
  container.appendChild(wrap);
  import('../home/home.js').then((m) => {
    const body = wrap.querySelector('[data-doctor-body]');
    body.innerHTML = '';
    if (m.renderDoctor) m.renderDoctor(body);
    else body.innerHTML = '<p class="settings-hint">Doctor unavailable.</p>';
  }).catch(() => {
    wrap.querySelector('[data-doctor-body]').innerHTML =
      '<p class="settings-hint">Doctor unavailable.</p>';
  });
}

/** Learn mode as a Settings sub-page. */
export function renderLearnSection(container) {
  const wrap = document.createElement('div');
  wrap.className = 'sp-custom-section';
  wrap.innerHTML = `<div class="sp-section-body" data-learn-body><p class="settings-hint">Loading…</p></div>`;
  container.appendChild(wrap);
  import('../learn/learn.js').then((m) => {
    const body = wrap.querySelector('[data-learn-body]');
    body.innerHTML = '';
    if (m.renderLearnTab) m.renderLearnTab(body);
    else body.innerHTML = '<p class="settings-hint">Learn unavailable.</p>';
  }).catch(() => {
    wrap.querySelector('[data-learn-body]').innerHTML =
      '<p class="settings-hint">Learn unavailable.</p>';
  });
}

/** Analytics as a Settings sub-page. */
export function renderInsightsSection(container) {
  const wrap = document.createElement('div');
  wrap.className = 'sp-custom-section';
  wrap.innerHTML = `<div class="sp-section-body" data-insights-body><p class="settings-hint">Loading…</p></div>`;
  container.appendChild(wrap);
  import('../analytics/analytics.js').then((m) => {
    const body = wrap.querySelector('[data-insights-body]');
    body.innerHTML = '';
    if (m.renderAnalyticsTab) m.renderAnalyticsTab(body);
    else body.innerHTML = '<p class="settings-hint">Analytics unavailable.</p>';
  }).catch(() => {
    wrap.querySelector('[data-insights-body]').innerHTML =
      '<p class="settings-hint">Analytics unavailable.</p>';
  });
}

/**
 * D3: quality / de-slop preview (POST /quality/preview had no frontend).
 * Lives in Settings → Output style & Quality.
 */
export function renderQualityPreview(container) {
  const wrap = document.createElement('div');
  wrap.className = 'sp-custom-section';
  wrap.innerHTML = `
    <h3 class="sp-section-title"><i class="fa-solid fa-wand-magic-sparkles"></i> De-slop preview</h3>
    <p class="settings-hint">Paste text to see what the no-slop cleanup would change — before it ever touches your chats.</p>
    <div class="sp-section-body">
      <textarea class="provider-key-input" data-qp-input rows="5" style="width:100%;box-sizing:border-box"
        placeholder="Paste AI-generated text here…" aria-label="Text to preview"></textarea>
      <div style="display:flex;gap:8px;margin-top:8px">
        <button class="btn-primary btn-sm" type="button" data-qp-run>Preview cleanup</button>
      </div>
      <div data-qp-out style="margin-top:8px"></div>
    </div>`;
  container.appendChild(wrap);
  const input = wrap.querySelector('[data-qp-input]');
  const out = wrap.querySelector('[data-qp-out]');
  wrap.querySelector('[data-qp-run]').addEventListener('click', async () => {
    const text = input.value.trim();
    if (!text) { showToast({ type: 'info', title: 'Paste some text first' }); return; }
    out.innerHTML = '<p class="settings-hint">Cleaning…</p>';
    try {
      const data = await (await apiFetch('/quality/preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })).json();
      const cleaned = data.cleaned ?? data.preview ?? '';
      const changed = data.changed ?? (cleaned !== text);
      out.innerHTML = changed
        ? `<h4>Cleaned</h4><pre class="lib-skill-md">${escapeHtml(cleaned)}</pre>`
        : '<p class="settings-hint">No slop detected — text is already clean.</p>';
    } catch (err) {
      out.innerHTML = `<p class="team-error">Preview failed: ${escapeHtml(err?.message || String(err))}</p>`;
    }
  });
}
