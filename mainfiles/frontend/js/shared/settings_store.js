/**
 * Settings store — typed settings with server persistence (Sangam-native).
 *
 * Source of truth: shared/settings_schema.js (keys, defaults, validation).
 * Persistence: PUT /api/user/settings (server), localStorage (cache).
 * Emits 'sangam:settings-changed' { key, value } on change.
 */
import { apiFetch } from './http.js';
import { showToast } from './toast.js';
import { getAllDefaults, SETTINGS_SCHEMA } from './settings_schema.js';

console.log('[Module] settings_store.js loaded');

const CACHE_KEY = 'sangam:settings-cache';
let settings = { ...getAllDefaults() };
let loaded = false;
let saveTimer = null;
let saveRetries = 0;
const MAX_SAVE_RETRIES = 3;

function validate(key, value) {
  const def = SETTINGS_SCHEMA.find((s) => s.key === key);
  if (!def) return false;
  switch (def.type) {
    case 'boolean': return typeof value === 'boolean';
    case 'number': return typeof value === 'number' && !Number.isNaN(value);
    case 'string': return typeof value === 'string';
    case 'select':
      return def.options.some((o) => o.v === value);
    case 'multiselect':
      return Array.isArray(value) && value.every((v) => def.options.some((o) => o.v === v));
    default: return false;
  }
}

export function getSetting(key) {
  return settings[key];
}

export function getAllSettings() {
  return { ...settings };
}

export function setSetting(key, value) {
  if (!validate(key, value)) {
    console.warn('[settings] invalid value for', key, value);
    return false;
  }
  settings[key] = value;
  try { localStorage.setItem(CACHE_KEY, JSON.stringify(settings)); } catch {}
  document.dispatchEvent(new CustomEvent('sangam:settings-changed', { detail: { key, value } }));
  scheduleSave();
  return true;
}

export function resetSetting(key) {
  const def = SETTINGS_SCHEMA.find((s) => s.key === key);
  if (def) setSetting(key, def.default);
}

export function resetAllSettings() {
  settings = { ...getAllDefaults() };
  try { localStorage.setItem(CACHE_KEY, JSON.stringify(settings)); } catch {}
  document.dispatchEvent(new CustomEvent('sangam:settings-changed', { detail: { key: '*' } }));
  scheduleSave();
}

function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, 800);
}

async function saveNow() {
  try {
    await apiFetch('/user/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ settings }),
    });
    saveRetries = 0;
  } catch (e) {
    // Never fail silently: the UI applied the value optimistically, so tell
    // the user it didn't persist (they'd otherwise discover the revert later).
    console.warn('[settings] save failed', e);
    showToast({ type: 'error', title: 'Settings not saved', message: 'Will retry on your next change.' });
    // Bounded retry — a dead backend must not spin the save loop forever.
    if (++saveRetries <= MAX_SAVE_RETRIES) scheduleSave();
    else saveRetries = 0;
  }
}

/** Load settings: server first, cache fallback. */
export async function loadSettings() {
  // Cache first for instant paint
  try {
    const cached = JSON.parse(localStorage.getItem(CACHE_KEY) || '{}');
    for (const [k, v] of Object.entries(cached)) {
      if (validate(k, v)) settings[k] = v;
    }
  } catch {}
  // Then server (source of truth)
  let serverSettings = {};
  try {
    const data = await (await apiFetch('/user/settings')).json();
    serverSettings = data.settings || {};
    for (const [k, v] of Object.entries(serverSettings)) {
      if (validate(k, v)) settings[k] = v;
    }
    try { localStorage.setItem(CACHE_KEY, JSON.stringify(settings)); } catch {}
  } catch (e) {
    console.warn('[settings] load failed, using cache', e);
  }
  // Phase 8 B3: one-time migration from the legacy localStorage blob.
  // If the server has no settings but the legacy key exists, push the mapped
  // values once, then delete the legacy key.
  if (Object.keys(serverSettings).length === 0) {
    await migrateLegacyBlob();
  }
  loaded = true;
  return { ...settings };
}

/**
 * One-time migration from legacy `localStorage 'sangam-settings'`.
 * Maps old keys onto the schema, pushes to the server, clears the old key.
 */
async function migrateLegacyBlob() {
  let legacy = null;
  try {
    legacy = JSON.parse(localStorage.getItem('sangam-settings') || 'null');
  } catch { /* ignore */ }
  if (!legacy || typeof legacy !== 'object') return;

  const FONT_SIZE_MAP = { sm: 12, md: 14, lg: 16 };
  const mapped = {};
  if (legacy.theme && validate('theme', legacy.theme)) mapped.theme = legacy.theme;
  if (legacy.fontSize != null) {
    const n = typeof legacy.fontSize === 'number' ? legacy.fontSize
      : FONT_SIZE_MAP[legacy.fontSize];
    if (n && validate('fontSize', n)) mapped.fontSize = n;
  }
  if (typeof legacy.voiceAutoSpeak === 'boolean') mapped.voiceAutoSpeak = legacy.voiceAutoSpeak;
  if (typeof legacy.voiceId === 'string') mapped.voiceId = legacy.voiceId;

  // Opportunistic: pull formality/expertise from the dying /user/preferences
  // endpoint before it is removed (B3 deletes it).
  try {
    const pref = await (await apiFetch('/user/preferences')).json();
    if (pref) {
      if (validate('formality', pref.formality)) mapped.formality = pref.formality;
      if (validate('expertise', pref.expertise_level)) mapped.expertise = pref.expertise_level;
    }
  } catch { /* endpoint gone or offline — skip */ }

  for (const [k, v] of Object.entries(mapped)) settings[k] = v;
  if (Object.keys(mapped).length) {
    try {
      await apiFetch('/user/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings }),
      });
      console.log('[settings] migrated legacy settings:', Object.keys(mapped).join(', '));
    } catch (e) {
      console.warn('[settings] migration push failed', e);
    }
  }
  try { localStorage.removeItem('sangam-settings'); } catch {}
}

export function isSettingsLoaded() { return loaded; }
