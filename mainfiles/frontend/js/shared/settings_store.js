/**
 * Settings store — typed settings with server persistence (Sangam-native).
 *
 * Source of truth: shared/settings_schema.js (keys, defaults, validation).
 * Persistence: PUT /api/user/settings (server), localStorage (cache).
 * Emits 'sangam:settings-changed' { key, value } on change.
 */
import { apiFetch } from './http.js';
import { getAllDefaults, SETTINGS_SCHEMA } from './settings_schema.js';

console.log('[Module] settings_store.js loaded');

const CACHE_KEY = 'sangam:settings-cache';
let settings = { ...getAllDefaults() };
let loaded = false;
let saveTimer = null;

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
  } catch (e) {
    console.warn('[settings] save failed', e);
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
  try {
    const data = await (await apiFetch('/user/settings')).json();
    const server = data.settings || {};
    for (const [k, v] of Object.entries(server)) {
      if (validate(k, v)) settings[k] = v;
    }
    try { localStorage.setItem(CACHE_KEY, JSON.stringify(settings)); } catch {}
  } catch (e) {
    console.warn('[settings] load failed, using cache', e);
  }
  loaded = true;
  return { ...settings };
}

export function isSettingsLoaded() { return loaded; }
