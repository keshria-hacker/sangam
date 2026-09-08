/**
 * Toast notification system.
 * Provides consistent, dismissible notifications with deduplication.
 */

import { $, createEl, show, hide, addClass, removeClass, escapeHtml } from './utils.js';
import { TOAST_TYPES, TOAST_ICONS } from './constants.js';

const TOAST_CONTAINER_ID = 'toastContainer';
const VISIBLE_TOASTS = new Map(); // dedupKey -> toast element

/**
 * Show a toast notification.
 * @param {Object} options
 * @param {string} options.type - 'success' | 'error' | 'info'
 * @param {string} [options.title] - Toast title (bold)
 * @param {string} [options.message] - Toast message
 * @param {number} [options.duration=4200] - Auto-dismiss duration in ms
 */
export function showToast({ type = 'info', title = '', message = '', duration = 4200 }) {
  const container = $(`#${TOAST_CONTAINER_ID}`);
  if (!container) {
    console.warn('Toast container not found');
    return;
  }

  // Deduplication key
  const dedupKey = `${type}:${title}:${message}`;
  if (VISIBLE_TOASTS.has(dedupKey)) {
    // Refresh existing toast timer
    const existing = VISIBLE_TOASTS.get(dedupKey);
    resetToastTimer(existing, duration);
    return;
  }

  const toast = createEl('div', {
    class: `toast ${type}`,
    dataset: { dedup: dedupKey },
  }, `
    <i class="fa-solid ${TOAST_ICONS[type] || TOAST_ICONS.info}"></i>
    <div class="toast-text">${title ? `<strong>${escapeHtml(title)}</strong>` : ''}${message ? ` ${escapeHtml(message)}` : ''}</div>
    <button class="toast-close" aria-label="Dismiss"><i class="fa-solid fa-xmark"></i></button>
    <div class="toast-bar"></div>
  `);

  container.appendChild(toast);
  VISIBLE_TOASTS.set(dedupKey, toast);

  const remove = () => {
    removeClass(toast, 'visible');
    addClass(toast, 'leaving');
    const bar = toast.querySelector('.toast-bar');
    if (bar) bar.style.animationPlayState = 'paused';
    setTimeout(() => {
      toast.remove();
      VISIBLE_TOASTS.delete(dedupKey);
    }, 180);
  };

  // Animate progress bar
  requestAnimationFrame(() => {
    const bar = toast.querySelector('.toast-bar');
    if (bar) {
      bar.style.animation = `toastShrink ${duration}ms linear forwards`;
    }
    addClass(toast, 'visible');
  });

  // Click to dismiss
  toast.querySelector('.toast-close').addEventListener('click', remove);
  setTimeout(remove, duration);
}

/**
 * Reset timer on existing toast (for deduplication).
 */
function resetToastTimer(toast, duration) {
  const bar = toast.querySelector('.toast-bar');
  if (bar) {
    bar.style.animation = 'none';
    bar.offsetHeight; // force reflow
    bar.style.animation = `toastShrink ${duration}ms linear forwards`;
  }
}

/**
 * Show success toast (convenience).
 */
export function showSuccess(message, title = '', duration) {
  showToast({ type: TOAST_TYPES.SUCCESS, title, message, duration });
}

/**
 * Show error toast (convenience).
 */
export function showError(message, title = '', duration) {
  showToast({ type: TOAST_TYPES.ERROR, title, message, duration });
}

/**
 * Show info toast (convenience).
 */
export function showInfo(message, title = '', duration) {
  showToast({ type: TOAST_TYPES.INFO, title, message, duration });
}

/**
 * Clear all toasts.
 */
export function clearToasts() {
  const container = $(`#${TOAST_CONTAINER_ID}`);
  if (!container) return;
  VISIBLE_TOASTS.forEach((toast) => toast.remove());
  VISIBLE_TOASTS.clear();
}

/**
 * Initialize toast system (called on app bootstrap).
 */
export function initToasts() {
  // Container is in HTML, nothing to do
}