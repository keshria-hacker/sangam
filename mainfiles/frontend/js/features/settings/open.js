/**
 * openSettings — single owner for "open the Settings page".
 *
 * Phase 8 B2: the legacy settings modal is deleted. Every entry point
 * (Ctrl+, , command palette, chat error link, models "link a key" link,
 * rail Settings) now opens the schema-driven Settings page via the nav
 * handler registered in app.js initRail().
 */
import { navigate } from '../../core/nav.js';

console.log('[Module] settings/open.js loaded');

export function openSettings() {
  navigate('settings');
}
