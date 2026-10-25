/**
 * openSettings — single owner for "open the Settings page".
 *
 * Phase 8 B2: the legacy settings modal is deleted. Every entry point
 * (Ctrl+, , command palette, chat error link, models "link a key" link,
 * tab bar Settings tab) now opens the schema-driven Settings page via
 * the tab shell's navigate() (tabs.js) — the old nav.js rail module
 * was deleted with the sidebar in the tabs-on-top correction.
 */
import { navigate } from '../tabs/tabs.js';

console.log('[Module] settings/open.js loaded');

export function openSettings() {
  navigate('settings');
}
