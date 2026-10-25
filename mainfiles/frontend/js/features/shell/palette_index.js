/**
 * Command-palette index — A1 perfect-flow shell (§3.3).
 *
 * Pure module: no imports, no DOM, no network. The palette UI builds
 * this index from live data (destinations, settings sections, installed
 * skills, saved prompts, models, conversations) and searches it; the
 * tests import it directly from Node with fixture data.
 *
 * An item: { id, label, group, keywords, action } where action is a
 * plain descriptor the palette UI interprets:
 *   { type: 'navigate', dest, section?, param? }
 *   { type: 'new-chat' } | { type: 'new-project' } | { type: 'new-artifact' }
 *   { type: 'switch-model', modelId } | { type: 'toggle-auto' }
 *   { type: 'install-skill' } | { type: 'settings', section }
 *   { type: 'run-prompt', body } | { type: 'open-chat', chatId }
 *   { type: 'command', command } — a built-in palette command id.
 * Items carry no behaviour, so the index is safe to snapshot in tests.
 */

export const PALETTE_GROUPS = [
  'Destinations',
  'Create',
  'Models',
  'Settings',
  'Skills',
  'Prompts',
  'Conversations',
  'Commands',
];

/**
 * Build the full index. Every input list is optional; a missing list
 * simply contributes no items — it never invents entries.
 *   destinations: [{ id, title }] (router DESTINATIONS)
 *   settingsSections: [{ id, label }]
 *   skills: [{ name }] — installed skill/extension names
 *   prompts: [{ name, body }] — saved prompt templates
 *   models: [{ id, label? }] — available models for "Switch to …"
 *   chats: [{ id, title }] — recent conversations
 */
export function buildPaletteIndex(input = {}) {
  const items = [];
  const push = (id, label, group, action, keywords = '') => {
    items.push({ id, label, group, keywords: `${label} ${keywords}`.trim(), action });
  };

  for (const d of input.destinations || []) {
    push(`dest:${d.id}`, `Go to ${d.title}`, 'Destinations',
      { type: 'navigate', dest: d.id }, d.id);
  }
  push('new-chat', 'New chat', 'Create', { type: 'new-chat' }, 'chat new');
  push('new-project', 'New project', 'Create', { type: 'new-project' }, 'project workspace');
  push('new-artifact', 'New artifact', 'Create', { type: 'new-artifact' }, 'artifact studio create');
  push('toggle-auto', 'Toggle Auto mode', 'Models', { type: 'toggle-auto' }, 'auto mode composer');
  for (const m of input.models || []) {
    push(`model:${m.id}`, `Switch model to ${m.label || m.id}`, 'Models',
      { type: 'switch-model', modelId: m.id }, m.id);
  }
  for (const s of input.settingsSections || []) {
    push(`settings:${s.id}`, `Settings: ${s.label}`, 'Settings',
      { type: 'settings', section: s.id }, s.id);
  }
  push('install-skill', 'Install a skill', 'Skills', { type: 'install-skill' }, 'skill pack marketplace');
  for (const s of input.skills || []) {
    const name = s.name || s.id;
    if (!name) continue;
    push(`skill:${name}`, `Skill: ${name}`, 'Skills',
      { type: 'navigate', dest: 'library', section: 'skills' }, 'skill');
  }
  for (const p of input.prompts || []) {
    if (!p.name) continue;
    push(`prompt:${p.name}`, `Run prompt: ${p.name}`, 'Prompts',
      { type: 'run-prompt', body: p.body || '' }, 'prompt template');
  }
  for (const c of input.chats || []) {
    if (!c.id) continue;
    push(`chat:${c.id}`, `Open conversation: ${c.title || 'Untitled chat'}`, 'Conversations',
      { type: 'open-chat', chatId: c.id }, 'conversation chat');
  }
  push('cmd:theme', 'Toggle theme', 'Commands', { type: 'command', command: 'theme' });
  push('cmd:websearch', 'Toggle web search', 'Commands', { type: 'command', command: 'websearch' });
  push('cmd:export', 'Export current chat as Markdown', 'Commands', { type: 'command', command: 'export' });
  push('cmd:copy', 'Copy last response', 'Commands', { type: 'command', command: 'copy' });
  push('cmd:regen', 'Regenerate last response', 'Commands', { type: 'command', command: 'regen' });
  return items;
}

/** Case-insensitive substring search over label + keywords. Empty query returns all. */
export function searchPaletteIndex(items, query) {
  const q = (query || '').trim().toLowerCase();
  if (!q) return [...items];
  return items.filter((it) =>
    it.label.toLowerCase().includes(q) || it.keywords.toLowerCase().includes(q));
}

/** Coverage check used by tests: which required surfaces does the index reach? */
export function paletteCoverage(items) {
  const has = (pred) => items.some(pred);
  return {
    destinations: has((i) => i.group === 'Destinations'),
    settingsSections: has((i) => i.group === 'Settings'),
    skills: has((i) => i.group === 'Skills'),
    prompts: has((i) => i.group === 'Prompts'),
    newChat: has((i) => i.action.type === 'new-chat'),
    newProject: has((i) => i.action.type === 'new-project'),
    newArtifact: has((i) => i.action.type === 'new-artifact'),
    switchModel: has((i) => i.action.type === 'switch-model'),
    toggleAuto: has((i) => i.action.type === 'toggle-auto'),
    installSkill: has((i) => i.action.type === 'install-skill'),
  };
}
