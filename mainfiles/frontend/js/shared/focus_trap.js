/**
 * Focus trap utility — keeps keyboard focus inside a modal dialog.
 *
 * Usage:
 *   const release = trapFocus(overlayEl);
 *   // ... later, when closing:
 *   release();
 *
 * Returns a function that removes the trap and restores focus to the
 * element that was focused before the trap was installed.
 */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function trapFocus(container) {
  const prev = document.activeElement;
  function onKey(e) {
    if (e.key !== 'Tab') return;
    const focusable = [...container.querySelectorAll(FOCUSABLE)]
      .filter((el) => el.offsetParent !== null || el === document.activeElement);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }
  container.addEventListener('keydown', onKey);
  // Focus the first focusable element (or the container itself)
  setTimeout(() => {
    const first = container.querySelector(FOCUSABLE);
    if (first) first.focus();
    else if (!container.hasAttribute('tabindex')) {
      container.setAttribute('tabindex', '-1');
      container.focus();
    }
  }, 0);
  return function release() {
    container.removeEventListener('keydown', onKey);
    if (prev && typeof prev.focus === 'function') {
      try { prev.focus(); } catch {}
    }
  };
}
