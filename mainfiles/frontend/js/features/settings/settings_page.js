/**
 * Settings page — full-page settings UI driven by the settings schema (Sangam-native).
 *
 * Left: searchable category list. Main: setting rows for the selected category
 * (or cross-category search results). Each row: label, description, control,
 * per-setting Reset, and a "Changed" dot when the value differs from default.
 *
 * Controls write through settings_store (setSetting); persistence is handled
 * server-side by the store.
 *
 * Phase 8 B2: categories can also render custom sections (provider keys,
 * OmniRoute, feature toggles, memory browser, voice settings) migrated from
 * the deleted legacy modal. See ./sections.js.
 */
import { SETTING_CATEGORIES, SETTINGS_SCHEMA, searchSettings, LEGACY_SETTING_SECTIONS } from '../../shared/settings_schema.js';
import {
  getSetting, setSetting, resetSetting, resetAllSettings, getAllSettings,
} from '../../shared/settings_store.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
import {
  renderProviderKeysSection, renderConnectorsSection, renderOmnirouteSection, renderFeatureTogglesSection,
  renderMemorySection, renderVoiceSection, renderRoutesSection, renderDoctorSection,
  renderPresetsSection, renderWebSearchSection, renderInsightsSection, renderQualityPreview,
} from './sections.js';
// Batch 7: Model Fit section (Settings > Models & Routing).
import { renderModelFitSection } from '../create/fit.js';
import { renderDevicesSection } from './devices.js';
import { registerSectionActivator } from '../tabs/tabs.js';
import { apiFetch } from '../../shared/http.js';

console.log('[Module] settings_page.js loaded');

function isChanged(def) {
  const v = getSetting(def.key);
  return JSON.stringify(v) !== JSON.stringify(def.default);
}

function catLabel(id) {
  const c = SETTING_CATEGORIES.find((x) => x.id === id);
  return c ? c.label : id;
}

/** Build the control element for one setting definition. */
function buildControl(def, onChange) {
  const val = getSetting(def.key);
  let el;
  const disabled = !!def.readonly || !!def.unavailable;

  if (def.type === 'boolean') {
    el = document.createElement('label');
    el.className = 'switch';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = !!val;
    input.disabled = disabled;
    input.setAttribute('aria-label', def.label);
    input.addEventListener('change', () => {
      if (!setSetting(def.key, input.checked)) { input.checked = !!getSetting(def.key); }
      else onChange();
    });
    el.appendChild(input);
    const track = document.createElement('span');
    track.className = 'switch-track';
    const thumb = document.createElement('span');
    thumb.className = 'switch-thumb';
    track.appendChild(thumb);
    el.appendChild(track);
    return el;
  }

  if (def.type === 'select') {
    el = document.createElement('select');
    el.className = 'provider-key-input';
    el.setAttribute('aria-label', def.label);
    el.disabled = disabled;
    for (const o of def.options || []) {
      const opt = document.createElement('option');
      opt.value = o.v;
      opt.textContent = o.l;
      if (o.v === val) opt.selected = true;
      el.appendChild(opt);
    }
    el.addEventListener('change', () => {
      if (!setSetting(def.key, el.value)) { el.value = getSetting(def.key); }
      else onChange();
    });
    return el;
  }

  if (def.type === 'number') {
    el = document.createElement('input');
    el.type = 'number';
    el.className = 'provider-key-input sp-number';
    el.value = val;
    el.disabled = disabled;
    if (def.min != null) el.min = def.min;
    if (def.max != null) el.max = def.max;
    if (def.step != null) el.step = def.step;
    el.setAttribute('aria-label', def.label);
    el.addEventListener('change', () => {
      const n = Number(el.value);
      if (!setSetting(def.key, n)) { el.value = getSetting(def.key); }
      else onChange();
    });
    return el;
  }

  if (def.type === 'multiselect') {
    el = document.createElement('div');
    el.className = 'sp-multiselect';
    const cur = Array.isArray(val) ? val : [];
    for (const o of def.options || []) {
      const lab = document.createElement('label');
      lab.className = 'sp-check';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = cur.includes(o.v);
      cb.disabled = disabled;
      cb.addEventListener('change', () => {
        const next = [...el.querySelectorAll('input:checked')]
          .map((i) => i.value);
        if (!setSetting(def.key, next)) { cb.checked = !cb.checked; }
        else onChange();
      });
      cb.value = o.v;
      lab.appendChild(cb);
      lab.appendChild(document.createTextNode(o.l));
      el.appendChild(lab);
    }
    return el;
  }

  // string (default)
  el = document.createElement('input');
  el.type = 'text';
  el.className = 'provider-key-input';
  el.value = val ?? '';
  el.disabled = disabled;
  el.setAttribute('aria-label', def.label);
  el.addEventListener('change', () => {
    if (!setSetting(def.key, el.value)) { el.value = getSetting(def.key); }
    else onChange();
  });
  return el;
}

/** Build one setting row. */
function settingRow(def, opts = {}) {
  const row = document.createElement('div');
  row.className = 'sp-setting-row';
  row.dataset.key = def.key;

  const info = document.createElement('div');
  info.className = 'sp-setting-info';
  const label = document.createElement('div');
  label.className = 'sp-setting-label';
  label.textContent = def.label;
  const dot = document.createElement('span');
  dot.className = 'sp-changed-dot' + (isChanged(def) ? '' : ' hidden');
  dot.title = 'Changed from default';
  label.appendChild(dot);
  info.appendChild(label);
  if (def.description) {
    const desc = document.createElement('div');
    desc.className = 'sp-setting-desc';
    desc.textContent = def.description;
    info.appendChild(desc);
  }
  // §7: every row shows its default and its current value (the control
  // itself is the current value). Restart markers are explicit.
  const meta = document.createElement('div');
  meta.className = 'sp-setting-desc';
  const defText = def.default === undefined ? 'none'
    : (typeof def.default === 'object' ? JSON.stringify(def.default) : String(def.default));
  meta.textContent = `Default: ${defText || '(empty)'}`;
  if (def.requiresRestart) meta.textContent += ' · Requires restart';
  if (def.readonly) meta.textContent += ' · Read-only (informational)';
  if (def.unavailable) meta.textContent += ' · Not available in this build';
  info.appendChild(meta);
  if (opts.showCategory) {
    const badge = document.createElement('div');
    badge.className = 'sp-cat-badge';
    badge.textContent = catLabel(def.category);
    info.appendChild(badge);
  }
  row.appendChild(info);

  const right = document.createElement('div');
  right.className = 'sp-setting-right';
  const refreshDot = () => {
    dot.classList.toggle('hidden', !isChanged(def));
  };
  right.appendChild(buildControl(def, refreshDot));
  const resetBtn = document.createElement('button');
  resetBtn.className = 'icon-btn sp-reset-btn';
  resetBtn.type = 'button';
  resetBtn.title = `Reset "${def.label}" to default`;
  resetBtn.setAttribute('aria-label', resetBtn.title);
  resetBtn.innerHTML = '<i class="fa-solid fa-rotate-left"></i>';
  resetBtn.addEventListener('click', () => {
    resetSetting(def.key);
    refreshRowControl(row, def);
    refreshDot();
    showToast({ type: 'info', title: 'Reset', message: `"${def.label}" restored to default.` });
  });
  right.appendChild(resetBtn);
  row.appendChild(right);
  return row;
}

/** Rebuild the control of an existing row (after reset). */
function refreshRowControl(row, def) {
  const right = row.querySelector('.sp-setting-right');
  const resetBtn = right.querySelector('.sp-reset-btn');
  const oldControl = right.firstChild;
  const ctrl = buildControl(def, () => {
    row.querySelector('.sp-changed-dot')?.classList.toggle('hidden', !isChanged(def));
  });
  right.insertBefore(ctrl, resetBtn);
  oldControl?.remove();
}

/**
 * Render the Settings page into bodyEl.
 */
export function renderSettingsPage(bodyEl, opts = {}) {
  // Section may come from the URL (/settings/:section) or a palette
  // action; legacy category ids redirect to their current section.
  const requested = opts.section || 'general';
  const initial = SETTING_CATEGORIES.some((c) => c.id === requested)
    ? requested : (LEGACY_SETTING_SECTIONS[requested] || 'general');
  let activeCategory = initial;
  let query = '';

  bodyEl.innerHTML = `
    <div class="sp-page">
      <aside class="sp-sidebar">
        <div class="sp-search">
          <i class="fa-solid fa-magnifying-glass"></i>
          <input type="text" id="spSearchInput" class="provider-key-input" placeholder="Search settings…" aria-label="Search settings">
        </div>
        <nav class="sp-cats" id="spCats" aria-label="Settings categories"></nav>
      </aside>
      <main class="sp-main">
        <div class="sp-header">
          <h2 id="spTitle">General</h2>
          <div class="sp-actions">
            <button class="btn-secondary btn-sm" id="spExport" type="button" title="Download settings as JSON"><i class="fa-solid fa-download"></i> Export</button>
            <button class="btn-secondary btn-sm" id="spImportBtn" type="button" title="Import settings from JSON"><i class="fa-solid fa-upload"></i> Import</button>
            <input type="file" id="spImportFile" accept="application/json" hidden>
            <button class="btn-secondary btn-sm sp-danger" id="spResetAll" type="button" title="Reset all settings to defaults"><i class="fa-solid fa-rotate-left"></i> Reset all</button>
          </div>
        </div>
        <div class="sp-list" id="spList"></div>
      </main>
    </div>`;

  const catsEl = bodyEl.querySelector('#spCats');
  const listEl = bodyEl.querySelector('#spList');
  const titleEl = bodyEl.querySelector('#spTitle');
  const searchInput = bodyEl.querySelector('#spSearchInput');

  function countChanged(catId) {
    return SETTINGS_SCHEMA.filter((s) => s.category === catId && isChanged(s)).length;
  }

  function renderCats() {
    catsEl.innerHTML = '';
    for (const c of SETTING_CATEGORIES) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'sp-cat' + (c.id === activeCategory && !query ? ' active' : '');
      b.dataset.cat = c.id;
      const n = countChanged(c.id);
      b.innerHTML = `<i class="fa-solid ${escapeHtml(c.icon)}"></i><span>${escapeHtml(c.label)}</span>`
        + (n ? `<span class="sp-cat-count" title="${n} changed">${n}</span>` : '');
      b.addEventListener('click', () => {
        activeCategory = c.id;
        query = '';
        searchInput.value = '';
        renderCats();
        renderList();
      });
      catsEl.appendChild(b);
    }
  }

  function renderList() {
    listEl.innerHTML = '';
    let defs;
    if (query) {
      defs = searchSettings(query);
      titleEl.textContent = `Search: “${query}” (${defs.length})`;
    } else {
      defs = SETTINGS_SCHEMA.filter((s) => s.category === activeCategory);
      titleEl.textContent = catLabel(activeCategory);
    }
    if (!defs.length && query) {
      listEl.innerHTML = `<div class="no-results">No settings match “${escapeHtml(query)}”.</div>`;
      return;
    }
    for (const def of defs) {
      listEl.appendChild(settingRow(def, { showCategory: !!query }));
    }
    // Phase 8 B2: custom sections migrated from the legacy modal.
    let hasCustom = false;
    if (!query) hasCustom = renderCustomSections(listEl, activeCategory);
    if (!query && !defs.length && !hasCustom) {
      // No backing setting yet: say so, never render a fake control.
      const note = document.createElement('p');
      note.className = 'settings-hint';
      note.textContent = 'No settings in this section yet.';
      listEl.appendChild(note);
    }
  }

  /**
   * Custom (non-schema) sections per category, migrated from the old modal.
   * Rendered after the schema rows. Each render is guarded: a throwing
   * section shows an inline error instead of hanging on "Loading…".
   */
  function safeRender(fn, list, label) {
    try {
      const r = fn(list);
      if (r && typeof r.catch === 'function') {
        r.catch((err) => {
          console.warn(`[settings] section "${label}" failed`, err);
          const hint = document.createElement('p');
          hint.className = 'settings-hint settings-error-hint';
          hint.textContent = `Couldn't load the ${label} section. ${err?.message || err}`;
          list.appendChild(hint);
        });
      }
    } catch (err) {
      console.warn(`[settings] section "${label}" threw`, err);
      const hint = document.createElement('p');
      hint.className = 'settings-hint settings-error-hint';
      hint.textContent = `Couldn't load the ${label} section. ${err?.message || err}`;
      list.appendChild(hint);
    }
  }

  // Returns true when the category has custom (non-schema) content.
  function renderCustomSections(list, category) {
    if (category === 'models') {
      safeRender(renderProviderKeysSection, list, 'provider keys');
      safeRender(renderOmnirouteSection, list, 'OmniRoute');
      safeRender(renderRoutesSection, list, 'routing');
      safeRender(renderDoctorSection, list, 'doctor');
      // Batch 7: Model Fit (hardware, recommend, benchmark, Ollama pull/delete).
      safeRender(renderModelFitSection, list, 'model fit');
      return true;
    } else if (category === 'connectors') {
      safeRender(renderConnectorsSection, list, 'connectors');
      return true;
    } else if (category === 'memory') {
      safeRender(renderMemorySection, list, 'memory');
      // A3: the memory privacy dashboard lives here (Settings →
      // Memory & Knowledge). It overwrites its own container only, so
      // it gets a dedicated div after the schema rows.
      const dash = document.createElement('div');
      dash.className = 'sp-custom-section';
      list.appendChild(dash);
      import('../memory/privacy.js').then((m) => m.renderMemoryDashboard(dash)).catch((err) => {
        dash.innerHTML = `<p class="settings-hint">Could not load the memory dashboard. ${err?.message || err}</p>`;
      });
      return true;
    } else if (category === 'voice') {
      safeRender(renderVoiceSection, list, 'voice');
      // Batch 7: the quality preview was exported but never rendered;
      // wire it here so Detect/Edit + Lint are reachable.
      safeRender(renderQualityPreview, list, 'quality preview');
      return true;
    } else if (category === 'agents') {
      safeRender(renderFeatureTogglesSection, list, 'features');
      return true;
    } else if (category === 'tools') {
      safeRender(renderWebSearchSection, list, 'web search');
      return true;
    } else if (category === 'general') {
      safeRender(renderPresetsSection, list, 'presets');
      return true;
    } else if (category === 'security') {
      // Batch 6: LAN pairing + paired devices + certificate + threat model.
      safeRender(renderDevicesSection, list, 'devices');
      return true;
    } else if (category === 'data') {
      // Analytics dashboard (local-only, opt-in) lives here.
      apiFetch('/features').then((r) => r.json()).then((data) => {
        if (data.features?.analytics) safeRender(renderInsightsSection, list, 'usage');
        else {
          const hint = document.createElement('p');
          hint.className = 'settings-hint';
          hint.textContent = 'Usage analytics is off. Turn it on in Agents & Automation → Features to see the local usage dashboard here.';
          list.appendChild(hint);
        }
      }).catch(() => {});
      return true;
    } else if (category === 'advanced') {
      renderEnvInfoSection(list);
      return true;
    } else if (category === 'about') {
      renderAboutSection(list);
      return true;
    }
    return false;
  }

  // Server-only .env options: listed (visible) with an honest note that
  // the backend reads them from .env, so no fake editable control is
  // offered for them. MASTER_KEY is never listed with a value and is
  // deliberately not surfaced as an editable setting anywhere.
  function renderEnvInfoSection(list) {
    const wrap = document.createElement('div');
    wrap.className = 'sp-custom-section';
    const rows = [
      ['APP_NAME / ENV / APP_DEBUG / API_PREFIX / ALLOWED_ORIGINS', 'Server identity and CORS; set in .env, restart required.'],
      ['MASTER_KEY', 'Server-only secret for API-key encryption. Never shown or editable in the UI.'],
      ['MAX_UPLOAD_SIZE_MB', 'Upload cap; set in .env, restart required.'],
      ['Provider keys (OPENAI_API_KEY, …)', 'Set and live-tested in Models & Providers → provider keys; .env keys work too.'],
      ['Provider base URLs (OLLAMA_BASE_URL, LM_STUDIO_BASE_URL, VLLM_BASE_URL, NVIDIA_NIM_BASE_URL)', 'Local-runtime endpoints; the Models & Providers → Model Fit and Doctor sections report live status.'],
      ['REDIS_URL', 'Optional distributed rate limiting; in-memory fallback when unset. Set in .env, restart required.'],
      ['WEB_SEARCH_PROVIDER / WEB_SEARCH_API_KEY', 'Search backend; the provider is set in Tools, the key (when needed) in provider keys.'],
      ['QUALITY_NO_SLOP / QUALITY_ADHD_FRIENDLY', 'Response-quality defaults; the live toggles are in Chat & Responses.'],
      ['FEATURE_* flags', 'Feature toggles; the live toggles are in Agents & Automation → Features.'],
      ['SANGAM_AGENT_SCHEDULER / SANGAM_WORKFLOW_SCHEDULER', 'Background schedulers; the agent loop toggle is in Agents & Automation.'],
      ['SANGAM_EXTRA_ORIGINS / SANGAM_* workspace roots', 'Operator paths (security workspace, hive, cassettes, browser profile, repo root, pack feed); set in .env, restart required.'],
    ];
    wrap.innerHTML = `<h3 class="sp-section-title">Server-only options (.env)</h3>
      <div class="sp-section-body">
      <p class="settings-hint">These options are read by the backend from its environment, not from the user-settings store — so they are listed here for discoverability instead of as controls that would silently do nothing. Change them in .env on the server and restart.</p>
      <ul>${rows.map(([k, v]) => `<li><code>${k}</code> — ${v}</li>`).join('')}</ul>
      </div>`;
    list.appendChild(wrap);
  }

  function renderAboutSection(list) {
    const wrap = document.createElement('div');
    wrap.className = 'sp-custom-section';
    wrap.innerHTML = `<h3 class="sp-section-title">About Sangam</h3>
      <div class="sp-section-body">
      <p class="settings-hint">Sangam — one interface, every model, your workflow. A private, single-user AI workspace (plus opt-in LAN pairing for your own devices).</p>
      <p class="settings-hint">No version number is shown here because the backend does not expose one in this build; inventing one would be a fake claim. Architecture and attributions live in the repository docs (ARCHITECTURE.md, docs/ATTRIBUTIONS.md).</p>
      </div>`;
    list.appendChild(wrap);
  }

  // Keep "changed" dots/badges fresh when settings change elsewhere
  // (guard: tabs re-rendering shouldn't stack listeners)
  if (!bodyEl.dataset.spWired) {
    bodyEl.dataset.spWired = '1';
    document.addEventListener('sangam:settings-changed', () => {
      if (bodyEl.isConnected) renderCats();
    });
  }

  searchInput.addEventListener('input', () => {
    query = searchInput.value.trim();
    renderCats();
    renderList();
  });

  // --- Reset all (with confirm) ---
  bodyEl.querySelector('#spResetAll').addEventListener('click', () => {
    if (!window.confirm('Reset ALL settings to their defaults? This cannot be undone.')) return;
    resetAllSettings();
    renderCats();
    renderList();
    showToast({ type: 'info', title: 'Settings reset', message: 'All settings restored to defaults.' });
  });

  // --- Export JSON ---
  bodyEl.querySelector('#spExport').addEventListener('click', () => {
    const data = JSON.stringify(getAllSettings(), null, 2);
    const blob = new Blob([data], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'sangam-settings.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    showToast({ type: 'success', title: 'Exported', message: 'Settings downloaded as JSON.' });
  });

  // --- Import JSON (validate keys against schema) ---
  const fileInput = bodyEl.querySelector('#spImportFile');
  bodyEl.querySelector('#spImportBtn').addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      let applied = 0, rejected = 0;
      try {
        const data = JSON.parse(reader.result);
        if (!data || typeof data !== 'object') throw new Error('not an object');
        for (const [k, v] of Object.entries(data)) {
          if (!SETTINGS_SCHEMA.some((s) => s.key === k)) { rejected++; continue; }
          if (setSetting(k, v)) applied++; else rejected++;
        }
      } catch (err) {
        showToast({ type: 'error', title: 'Import failed', message: 'Not a valid settings JSON file.' });
        fileInput.value = '';
        return;
      }
      renderCats();
      renderList();
      showToast({
        type: rejected ? 'info' : 'success',
        title: 'Import complete',
        message: `${applied} applied${rejected ? `, ${rejected} rejected (unknown or invalid)` : ''}.`,
      });
      fileInput.value = '';
    };
    reader.readAsText(file);
  });

  // A1: section activator for palette / alias / URL deep-links. Any
  // current category id activates it; legacy ids redirect; 'usage'
  // (old analytics alias) lands on Data & Privacy.
  registerSectionActivator('settings', (section) => {
    const target = section === 'usage' ? 'data'
      : (SETTING_CATEGORIES.some((c) => c.id === section) ? section
        : (LEGACY_SETTING_SECTIONS[section] || null));
    if (!target) return;
    activeCategory = target;
    query = '';
    searchInput.value = '';
    renderCats();
    renderList();
  });

  renderCats();
  renderList();
}
