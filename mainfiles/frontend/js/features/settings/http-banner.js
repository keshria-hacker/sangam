/**
 * Global LAN HTTP-fallback banner (UX-refine wave).
 *
 * Previously the "LAN connection is not encrypted" warning only rendered
 * inside Settings → Devices (devices.js showHttpBanner), so a user on an
 * unencrypted LAN connection saw nothing while chatting — the exact
 * place the warning matters. This module renders the same banner in the
 * app shell on every load, no matter which destination is open.
 *
 * Hook: inspector.js initInspector() calls showGlobalHttpBanner() — the
 * inspector init runs unconditionally in app init, and app.js wiring is
 * parent-owned in this wave, so this file must NOT be wired from app.js
 * by a worker (the parent may move the call there later; the call is
 * idempotent either way). devices.js keeps its own call as a fallback;
 * both guard on the same element id, so at most one banner exists.
 *
 * Honest scope: the banner is a client-side protocol/host check only.
 * Loopback (localhost / 127.0.0.1 / ::1) never shows it — local dev is
 * not a LAN exposure. It says nothing about TLS validity.
 */

console.log('[Module] settings/http-banner.js loaded');

const BANNER_ID = 'sangam-lan-http-banner';
export const HTTP_BANNER_TEXT =
  'LAN connection is not encrypted — anyone on this Wi-Fi can read your traffic.';

export function isLoopbackHost(hostname) {
  return hostname === 'localhost' || hostname === '127.0.0.1' ||
    hostname === '[::1]' || hostname === '::1';
}

export function shouldShowHttpBanner() {
  return window.location.protocol === 'http:' &&
    !isLoopbackHost(window.location.hostname);
}

/** Render the global banner once. Returns true if it is now visible. */
export function showGlobalHttpBanner() {
  if (!shouldShowHttpBanner()) return false;
  if (document.getElementById(BANNER_ID)) return true;
  const banner = document.createElement('div');
  banner.id = BANNER_ID;
  banner.className = 'lan-banner';
  banner.setAttribute('role', 'alert');
  banner.textContent = HTTP_BANNER_TEXT;
  document.body.prepend(banner);
  return true;
}
