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

  // A1 design tokens (§6.2): Settings → Appearance edits these live.
  // Accent: a valid #rrggbb overrides the theme accent (and its -rgb
  // twin, which focus rings and selections use); anything else is
  // ignored rather than applied half-broken.
  const accent = String(getSetting('accentColor') || '').trim();
  if (/^#[0-9a-fA-F]{6}$/.test(accent)) {
    const r = parseInt(accent.slice(1, 3), 16);
    const g = parseInt(accent.slice(3, 5), 16);
    const b = parseInt(accent.slice(5, 7), 16);
    root.style.setProperty('--accent', accent);
    root.style.setProperty('--accent-rgb', `${r},${g},${b}`);
  } else {
    root.style.removeProperty('--accent');
    root.style.removeProperty('--accent-rgb');
  }
  const fontFamily = getSetting('fontFamily') || 'default';
  root.style.setProperty('--font-body', fontFamily === 'system'
    ? 'system-ui, sans-serif'
    : fontFamily === 'mono' ? 'ui-monospace, SFMono-Regular, Menlo, monospace' : '');
  if (fontFamily === 'default') root.style.removeProperty('--font-body');
  const radius = { small: '6px', medium: '14px', large: '22px' }[getSetting('cornerRadius')] || '14px';
  root.style.setProperty('--radius-md', radius);
  const motion = getSetting('motionIntensity') || 'full';
  const reduce = getSetting('reduceMotion');
  const dur = motion === 'none' || reduce ? '0ms' : motion === 'reduced' ? '120ms' : '200ms';
  root.style.setProperty('--dur-med', dur);
  if (motion === 'none' || reduce) root.style.setProperty('--dur-fast', '0ms');
  else root.style.removeProperty('--dur-fast');

  // Code highlight theme: explicit setting wins, Auto follows the theme.
  const codeSetting = getSetting('codeTheme') || 'auto';
  const codeTheme = codeSetting === 'auto' ? (effective === 'dark' ? 'github-dark' : 'github') : codeSetting;
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
    if (!key || key === '*' || ['theme', 'fontSize', 'density', 'accentColor', 'fontFamily',
        'cornerRadius', 'motionIntensity', 'reduceMotion', 'codeTheme'].includes(key)) {
      applyAppearance();
    }
  });
}
