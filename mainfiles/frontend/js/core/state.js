/**
 * Reactive state management using simple signals.
 * Lightweight alternative to frameworks - uses plain objects with
 * subscriber callbacks for reactivity.
 */

import { DEFAULT_SETTINGS, CHAT_BUCKETS, PROVIDER_COLORS } from '../shared/constants.js';
import { bucketFor } from '../shared/utils.js';

/**
 * Create a reactive signal.
 * @param {any} initialValue - Initial value
 * @returns {[get: () => any, set: (value: any) => void, subscribe: (fn: (value) => void) => () => void]}
 */
export function createSignal(initialValue) {
  let value = initialValue;
  const subscribers = new Set();

  const get = () => value;

  const set = (newValue) => {
    const nextValue = typeof newValue === 'function' ? newValue(value) : newValue;
    if (Object.is(nextValue, value)) return;
    value = nextValue;
    subscribers.forEach((fn) => fn(value));
  };

  const subscribe = (fn) => {
    subscribers.add(fn);
    return () => subscribers.delete(fn);
  };

  return [get, set, subscribe];
}

/**
 * Create a computed signal derived from other signals.
 * @param {Function} compute - Computation function
 * @returns {[get: () => any, subscribe: (fn) => () => void]}
 */
export function createComputed(compute) {
  let value = compute();
  const subscribers = new Set();

  const get = () => value;

  const recompute = () => {
    const nextValue = compute();
    if (!Object.is(nextValue, value)) {
      value = nextValue;
      subscribers.forEach((fn) => fn(value));
    }
  };

  // Note: In a real implementation, we'd track dependencies automatically.
  // For simplicity, consumers must call recompute() when dependencies change.

  const subscribe = (fn) => {
    subscribers.add(fn);
    return () => subscribers.delete(fn);
  };

  return [get, recompute, subscribe];
}

/**
 * Create a synchronized signal that mirrors a source signal.
 * @param {Function} sourceGet - Source signal getter
 * @returns {[get: () => any, set: (value) => void, subscribe: (fn) => () => void]}
 */
export function createSyncedSignal(sourceGet) {
  let value = sourceGet();
  const subscribers = new Set();

  const sync = () => {
    const nextValue = sourceGet();
    if (!Object.is(nextValue, value)) {
      value = nextValue;
      subscribers.forEach((fn) => fn(value));
    }
  };

  return [
    () => {
      sync();
      return value;
    },
    (newValue) => {
      // For synced signals, set is a no-op (read-only from source)
      // But we allow it for local mutations that will be synced back
      value = typeof newValue === 'function' ? newValue(value) : newValue;
      subscribers.forEach((fn) => fn(value));
    },
    (fn) => {
      subscribers.add(fn);
      return () => subscribers.delete(fn);
    },
  ];
}

// ============================================================================
// Application State
// ============================================================================

// Core state signals
export const [getProviders, setProviders] = createSignal([]);
export const [getModels, setModels] = createSignal([]);
export const [getChats, setChats] = createSignal([]);
export const [getActiveChatId, setActiveChatId] = createSignal(null);
export const [getSelectedModel, setSelectedModel] = createSignal(null);
export const [getActiveProviderFilter, setActiveProviderFilter] = createSignal('all');
export const [getMessages, setMessages] = createSignal([]);
export const [getAttachedFiles, setAttachedFiles] = createSignal([]);
export const [getIsGenerating, setIsGenerating] = createSignal(false);
export const [getAbortController, setAbortController] = createSignal(null);
export const [getLastUserText, setLastUserText] = createSignal('');
export const [getWebSearchEnabled, setWebSearchEnabled] = createSignal(false);
export const [getSidebarCollapsed, setSidebarCollapsed] = createSignal(false);
export const [getBackendReachable, setBackendReachable] = createSignal(null);
export const [getMaxTokens, setMaxTokens] = createSignal('1024');
export const [getReasoningEffort, setReasoningEffort] = createSignal('medium');
export const [getTemperature, setTemperature] = createSignal(0.7);

// Settings state (persisted to localStorage)
let _savedSettings = null;
try {
  const saved = localStorage.getItem('sangam-settings');
  _savedSettings = saved ? JSON.parse(saved) : null;
} catch {
  _savedSettings = null;
}

const [getSettings, setSettings, subscribeSettings] = createSignal({
  ...DEFAULT_SETTINGS,
  ..._savedSettings,
});

// Persist settings changes
subscribeSettings((newSettings) => {
  try {
    localStorage.setItem('sangam-settings', JSON.stringify(newSettings));
  } catch (e) {
    console.warn('Failed to persist settings:', e);
  }
});

export { getSettings, setSettings };

// Provider metadata cache
export const [getProviderMeta, setProviderMeta] = createSignal({});

/**
 * Get provider metadata (label, state, color) for a provider ID.
 */
export function getProviderInfo(providerId) {
  const meta = getProviderMeta()[providerId];
  if (meta) return meta;

  return {
    label: providerId,
    state: 'offline',
    color: PROVIDER_COLORS[providerId] || '#9AA1AC',
  };
}

/**
 * Update provider info cache from /api/providers response.
 */
export function updateProviderInfo(providers) {
  const meta = {};
  providers.forEach((p) => {
    meta[p.id] = {
      label: p.label || p.id,
      state: p.state || 'offline',
      color: PROVIDER_COLORS[p.id] || '#9AA1AC',
    };
  });
  setProviderMeta(meta);
}

/**
 * Chat history bucketing helpers.
 */
export function getChatBuckets(chats = getChats()) {
  const buckets = {};
  CHAT_BUCKETS.forEach((bucket) => (buckets[bucket] = []));

  chats.forEach((chat) => {
    const bucket = bucketFor(chat.updated_at);
    if (buckets[bucket]) buckets[bucket].push(chat);
  });

  return buckets;
}

/**
 * Filter chats by search query and return bucketed.
 */
export function filterChats(query, chats = getChats()) {
  const q = query.trim().toLowerCase();
  const buckets = getChatBuckets(chats);

  if (!q) return buckets;

  const filtered = {};
  Object.entries(buckets).forEach(([bucket, items]) => {
    filtered[bucket] = items.filter((c) => c.title.toLowerCase().includes(q));
  });

  return filtered;
}

/**
 * Get models filtered by provider and search query.
 */
export function filterModels(searchQuery = '', providerFilter = getActiveProviderFilter()) {
  const q = searchQuery.trim().toLowerCase();
  const models = getModels();

  return models.filter((m) => {
    const info = getProviderInfo(m.provider);
    const matchesProvider = providerFilter === 'all' || m.provider === providerFilter;
    const matchesQuery =
      m.name.toLowerCase().includes(q) || info.label.toLowerCase().includes(q);
    return matchesProvider && matchesQuery;
  });
}

/**
 * Group models by provider.
 */
export function groupModelsByProvider(models) {
  const grouped = {};
  models.forEach((m) => {
    const info = getProviderInfo(m.provider);
    const key = m.provider;
    if (!grouped[key]) grouped[key] = { info, models: [] };
    grouped[key].models.push(m);
  });
  return grouped;
}

/**
 * Select a model - update selectedModel signal.
 */
export function selectModel(model, { silent = false } = {}) {
  if (!model) return;
  setSelectedModel(model);
  setMaxTokens(model.max_tokens || '1024');
}

/**
 * Reset chat-related state (for new chat).
 */
export function resetChatState() {
  setActiveChatId(null);
  setMessages([]);
  setAttachedFiles([]);
  setLastUserText('');
  setIsGenerating(false);
  setAbortController(null);
}

/**
 * Reset all app state (for logout).
 */
export function resetAllState() {
  setProviders([]);
  setModels([]);
  setChats([]);
  resetChatState();
  setSelectedModel(null);
  setActiveProviderFilter('all');
  setSidebarCollapsed(false);
  setBackendReachable(null);
  setWebSearchEnabled(false);
  setTemperature(0.7);
  setMaxTokens('1024');
  setReasoningEffort('medium');
  // Don't reset settings - those are user preferences
}

/**
 * Initialize app state on boot.
 */
export function initAppState() {
  // Load persisted settings
  const settings = getSettings();
  const root = document.documentElement;
  const effectiveTheme = settings.theme === 'system'
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : settings.theme;

  root.setAttribute('data-theme', effectiveTheme);
  document.body.setAttribute('data-font-size', settings.fontSize);
  document.body.setAttribute('data-chat-width', settings.chatWidth);
  document.body.setAttribute('data-animations', settings.animations ? 'on' : 'off');
}