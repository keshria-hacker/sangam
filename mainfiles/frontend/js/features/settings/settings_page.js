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
import { SETTING_CATEGORIES, SETTINGS_SCHEMA, searchSettings } from '../../shared/settings_schema.js';
import {
  getSetting, setSetting, resetSetting, resetAllSettings, getAllSettings,
} from '../../shared/settings_store.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
import {
  renderProviderKeysSection, renderOmnirouteSection, renderFeatureTogglesSection,
  renderMemorySection, renderVoiceSection, renderRoutesSection, renderDoctorSection,
  renderLearnSection, renderInsightsSection, renderQualityPreview, renderPresetsSection,
} from './sections.js';

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

  if (def.type === 'boolean') {
    el = document.createElement('label');
    el.className = 'switch';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = !!val;
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
  const ctrl = buildControl(def, () => {
    row.querySelector('.sp-changed-dot')?.classList.toggle('hidden', !isChanged(def));
  });
  right.insertBefore(ctrl, resetBtn);
  // remove the old control (first child)
  right.removeChild(right.firstChild);
}

/**
 * Render the Settings page into bodyEl.
 */
export function renderSettingsPage(bodyEl) {
  let activeCategory = 'general';
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
    if (!query) renderCustomSections(listEl, activeCategory);
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
    }
  }

  function renderCustomSections(list, category) {
    if (category === 'models') {
      safeRender(renderProviderKeysSection, list, 'provider keys');
      safeRender(renderOmnirouteSection, list, 'OmniRoute');
      safeRender(renderRoutesSection, list, 'routing');
      safeRender(renderDoctorSection, list, 'doctor');
    } else if (category === 'knowledge') {
      safeRender(renderMemorySection, list, 'memory');
    } else if (category === 'voice') {
      safeRender(renderVoiceSection, list, 'voice');
    } else if (category === 'workspace') {
      safeRender(renderFeatureTogglesSection, list, 'features');
    } else if (category === 'learn') {
      safeRender(renderLearnSection, list, 'learn');
    } else if (category === 'insights') {
      safeRender(renderInsightsSection, list, 'insights');
    } else if (category === 'output') {
      safeRender(renderQualityPreview, list, 'quality');
    } else if (category === 'general') {
      safeRender(renderPresetsSection, list, 'presets');
    }
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

  renderCats();
  renderList();
}
