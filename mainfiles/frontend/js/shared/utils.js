/**
 * Shared utility + DOM helper functions.
 * This is the single source of truth for shared helpers (utils.js and the
 * former dom.js were merged to remove duplicated exports like $, $$,
 * createEl, debounce, trapFocus and the class helpers).
 */

import { FILE_ICON_MAP, SUPPORTED_FILE_EXTENSIONS, NON_CHAT_MARKERS } from './constants.js';

/**
 * Shorthand for document.querySelector
 */
export const $ = (selector) => document.querySelector(selector);

/**
 * Shorthand for document.querySelectorAll as array
 */
export const $$ = (selector) => Array.from(document.querySelectorAll(selector));

/**
 * Escape HTML special characters to prevent XSS.
 */
export function escapeHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[c]));
}

/**
 * Format bytes to human-readable string.
 */
export function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * Extract file extension from filename.
 */
export function extOf(filename) {
  const parts = filename.split('.');
  return parts.length > 1 ? parts.pop().toLowerCase() : '';
}

/**
 * Get file icon/color info for a file.
 */
export function getFileInfo(filename) {
  const ext = extOf(filename);
  return FILE_ICON_MAP[ext] || { icon: 'fa-file', color: '#9AA1AC' };
}

/**
 * Format ISO timestamp to local time string (HH:MM).
 */
export function formatTime(iso) {
  if (!iso) return '';
  try {
    const date = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

/**
 * Get current time as HH:MM string.
 */
export function nowTime() {
  return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/**
 * Bucket an ISO date string into a human-readable category.
 */
export function bucketFor(isoDate) {
  const d = new Date(isoDate.endsWith('Z') ? isoDate : isoDate + 'Z');
  const now = new Date();
  const diffDays = Math.floor((now - d) / 86400000);

  if (diffDays <= 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  if (diffDays <= 7) return 'Previous 7 days';
  if (diffDays <= 30) return 'Previous 30 days';
  return 'Older';
}

/**
 * Debounce function execution.
 */
export function debounce(fn, delay) {
  let timeoutId;
  return (...args) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn(...args), delay);
  };
}

/**
 * Throttle function execution.
 */
export function throttle(fn, limit) {
  let inThrottle;
  return (...args) => {
    if (!inThrottle) {
      fn(...args);
      inThrottle = true;
      setTimeout(() => (inThrottle = false), limit);
    }
  };
}

/**
 * Generate a random ID string.
 */
export function generateId(prefix = '') {
  return `${prefix}${Math.random().toString(36).slice(2, 9)}`;
}

/**
 * Check if a model ID matches any non-chat markers.
 */
export function isNonChatModel(modelId) {
  const lowered = modelId.toLowerCase();
  return NON_CHAT_MARKERS.some((marker) => lowered.includes(marker));
}

/**
 * Generate a human-readable name from model ID.
 */
export function deriveModelName(modelId) {
  return modelId.split('/').pop() || modelId;
}

/**
 * Deep clone an object.
 */
export function deepClone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

/**
 * Check if value is a plain object.
 */
export function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Safe JSON parse with fallback.
 */
export function safeJsonParse(str, fallback = null) {
  try {
    return JSON.parse(str);
  } catch {
    return fallback;
  }
}

/**
 * Sleep for specified milliseconds.
 */
export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Retry a promise-returning function with exponential backoff.
 */
export async function retry(fn, options = {}) {
  const {
    retries = 3,
    baseDelay = 1000,
    maxDelay = 10000,
    shouldRetry = () => true,
  } = options;

  let lastError;
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await fn();
    } catch (error) {
      lastError = error;
      if (attempt === retries || !shouldRetry(error)) break;

      const delay = Math.min(baseDelay * Math.pow(2, attempt), maxDelay);
      await sleep(delay);
    }
  }
  throw lastError;
}

/**
 * Create an AbortSignal that aborts after timeout.
 */
export function abortAfter(ms) {
  const controller = new AbortController();
  setTimeout(() => controller.abort(), ms);
  return controller.signal;
}

/**
 * Combine multiple AbortSignals into one.
 */
export function combineAbortSignals(...signals) {
  const controller = new AbortController();

  const abort = () => controller.abort();
  signals.forEach((signal) => {
    if (signal.aborted) abort();
    else signal.addEventListener('abort', abort, { once: true });
  });

  return controller.signal;
}

/**
 * Check if we're on a mobile viewport.
 */
export function isMobile() {
  return window.innerWidth <= 900;
}

/**
 * Lock/unlock body scroll.
 */
export function setBodyScrollLock(locked) {
  document.body.style.overflow = locked ? 'hidden' : '';
}

/**
 * Focus an element safely (with timeout for overlay transitions).
 */
export function safeFocus(element, delay = 0) {
  if (!element) return;
  setTimeout(() => {
    try {
      element.focus({ preventScroll: true });
    } catch {
      // Ignore focus errors
    }
  }, delay);
}

/**
 * Trap focus within an element (for modals).
 */
export function trapFocus(element) {
  const focusable = element.querySelectorAll(
    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"]):not([disabled])'
  );

  const first = focusable[0];
  const last = focusable[focusable.length - 1];

  function handleTab(e) {
    if (e.key !== 'Tab') return;

    if (e.shiftKey) {
      if (document.activeElement === first) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  element.addEventListener('keydown', handleTab);
  return () => element.removeEventListener('keydown', handleTab);
}

/**
 * Create an element with attributes and children.
 * @param {string} tag - Tag name
 * @param {Object} props - Properties: class, id, dataset, style, etc.
 * @param {string|Node|Array} children - HTML string, node, or array of nodes
 * @returns {HTMLElement}
 */
export function createEl(tag, props = {}, children = '') {
  const el = document.createElement(tag);

  Object.entries(props).forEach(([key, value]) => {
    if (key === 'class') el.className = value;
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key === 'style') Object.assign(el.style, value);
    else if (key.startsWith('on') && typeof value === 'function') {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else {
      el.setAttribute(key, value);
    }
  });

  if (typeof children === 'string') {
    el.insertAdjacentHTML('beforeend', children);
  } else if (children instanceof Node) {
    el.appendChild(children);
  } else if (Array.isArray(children)) {
    children.forEach((child) => {
      if (child instanceof Node) el.appendChild(child);
      else el.insertAdjacentHTML('beforeend', child);
    });
  }

  return el;
}

/**
 * Add class(es) to element.
 */
export function addClass(el, ...classes) {
  if (el) el.classList.add(...classes);
}

/**
 * Remove class(es) from element.
 */
export function removeClass(el, ...classes) {
  if (el) el.classList.remove(...classes);
}

/**
 * Toggle class on element.
 */
export function toggleClass(el, className, force) {
  if (el) el.classList.toggle(className, force);
}

/**
 * Check if element has class.
 */
export function hasClass(el, className) {
  return el?.classList.contains(className) ?? false;
}

/**
 * Remove all children from an element.
 */
export function empty(el) {
  if (!el) return;
  while (el.firstChild) {
    el.removeChild(el.firstChild);
  }
}

/**
 * Set multiple attributes at once.
 */
export function setAttrs(el, attrs) {
  if (!el) return;
  Object.entries(attrs).forEach(([key, value]) => {
    if (value === null || value === undefined) {
      el.removeAttribute(key);
    } else {
      el.setAttribute(key, value);
    }
  });
}

/**
 * Get data attribute value.
 */
export function getData(el, key) {
  return el?.dataset[key];
}

/**
 * Set data attribute.
 */
export function setData(el, key, value) {
  if (!el) return;
  el.dataset[key] = value;
}

/**
 * Show element (removes hidden state).
 */
export function show(el, display = '') {
  if (!el) return;
  el.style.display = display || (el.tagName === 'TR' ? 'table-row' : el.tagName === 'TD' ? 'table-cell' : '');
  el.classList.remove('hidden');
}

/**
 * Hide element (adds hidden state).
 */
export function hide(el) {
  if (!el) return;
  el.style.display = 'none';
  el.classList.add('hidden');
}

/**
 * Toggle element visibility.
 */
export function toggle(el, force) {
  if (!el) return;
  const hidden = el.classList.contains('hidden');
  if (force === undefined) force = hidden;
  if (force) show(el); else hide(el);
}

/**
 * Lock/unlock body scroll (for modals) using a reference counter so nested
 * overlays don't unlock the page early.
 */
let _scrollLockCount = 0;
export function lockBodyScroll() {
  _scrollLockCount++;
  if (_scrollLockCount === 1) {
    document.body.style.overflow = 'hidden';
  }
}

export function unlockBodyScroll() {
  _scrollLockCount = Math.max(0, _scrollLockCount - 1);
  if (_scrollLockCount === 0) {
    document.body.style.overflow = '';
  }
}