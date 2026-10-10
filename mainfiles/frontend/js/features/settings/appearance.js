/**
 * Appearance — applies theme / font / density settings to the document.
 *
 * Phase 8 B2: replaces the deleted settings.js applySettings(). Reads from
 * the typed settings store (settings_store.js), not the legacy
 * localStorage 'sangam-settings' blob. Re-applies on 'sangam:settings-changed'.
 */
import { getSetting } from '../../shared/settings_store.js';
import { CODE_THEME_URLS } from '../../shared/constants.js';

console.log('[Module] settings/appearance.js loaded');

let wired = false;

/** Apply current appearance settings to the document. */
export function applyAppearance() {
  const theme = getSetting('theme') || 'dark';
  const root = document.documentElement;
  const effective = theme === 'system'
    ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    : theme;
  root.setAttribute('data-theme', effective);

  const themeIcon = document.getElementById('themeToggle')?.querySelector('i');
  if (themeIcon) themeIcon.className = effective === 'dark' ? 'fa-solid fa-moon' : 'fa-solid fa-sun';

  document.body.setAttribute('data-font-size', String(getSetting('fontSize') ?? 14));
  document.body.setAttribute('data-density', String(getSetting('density') || 'comfortable'));

  // Code highlight theme follows the effective theme (no separate setting).
  const codeTheme = effective === 'dark' ? 'github-dark' : 'github';
  const themeEl = document.getElementById('hljs-theme');
  if (themeEl && CODE_THEME_URLS[codeTheme]) {
    themeEl.href = CODE_THEME_URLS[codeTheme];
    document.body.setAttribute('data-code-theme', codeTheme);
  }
}

/** Toggle dark/light theme (header button + Ctrl+Shift+T). */
export function toggleTheme() {
  import('../../shared/settings_store.js').then(({ getSetting, setSetting }) => {
    const cur = document.documentElement.getAttribute('data-theme');
    setSetting('theme', cur === 'dark' ? 'light' : 'dark');
  });
}

/** Bind the header theme toggle; re-apply appearance on any settings change. */
export function initAppearance() {
  applyAppearance();
  if (wired) return;
  wired = true;
  document.getElementById('themeToggle')?.addEventListener('click', toggleTheme);
  document.addEventListener('sangam:settings-changed', (e) => {
    const key = e.detail?.key;
    if (!key || key === '*' || ['theme', 'fontSize', 'density'].includes(key)) {
      applyAppearance();
    }
  });
}
