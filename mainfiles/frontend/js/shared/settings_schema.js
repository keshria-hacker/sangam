/**
 * Settings schema — single source of truth for all user settings (Sangam-native).
 *
 * Each setting: { key, label, description, type, default, category, options? }
 * Types: 'boolean' | 'string' | 'number' | 'select' | 'multiselect'
 *
 * The Settings page renders from this schema: searchable, resettable,
 * persisted server-side via /user/settings (localStorage as cache).
 */
export const SETTING_CATEGORIES = [
  { id: 'general',     label: 'General',            icon: 'fa-gear' },
  { id: 'appearance',  label: 'Appearance',         icon: 'fa-palette' },
  { id: 'workspace',   label: 'Workspace layout',   icon: 'fa-table-columns' },
  { id: 'chat',        label: 'Chat & Composer',    icon: 'fa-comment' },
  { id: 'models',     label: 'Models & Routing',   icon: 'fa-server' },
  // placeholder      label: 'Models & Routing',   icon: 'fa-server' },
  { id: 'agents',      label: 'Agents & Safety',    icon: 'fa-robot' },
  { id: 'knowledge',   label: 'Knowledge & Memory', icon: 'fa-brain' },
  { id: 'voice',       label: 'Voice',              icon: 'fa-microphone' },
  { id: 'create',      label: 'Create',             icon: 'fa-wand-magic-sparkles' },
  { id: 'output',      label: 'Output style & Quality', icon: 'fa-pen' },
  { id: 'library',     label: 'Library',            icon: 'fa-book' },
  { id: 'shortcuts',   label: 'Shortcuts',          icon: 'fa-keyboard' },
  { id: 'privacy',     label: 'Privacy & Data',     icon: 'fa-shield-halved' },
  { id: 'doctor',      label: 'Doctor & About',     icon: 'fa-stethoscope' },
];

export const SETTINGS_SCHEMA = [
  // ---- General ----
  { key: 'language', label: 'Language', description: 'Interface language.', type: 'select',
    options: [{ v: 'en', l: 'English' }, { v: 'hi', l: 'Hindi' }], default: 'en', category: 'general' },
  { key: 'startupView', label: 'Startup view', description: 'What to show on launch.', type: 'select',
    options: [{ v: 'home', l: 'Home' }, { v: 'chat', l: 'Chat' }, { v: 'last', l: 'Last view' }],
    default: 'home', category: 'general' },

  // ---- Appearance ----
  { key: 'theme', label: 'Theme', description: 'Color theme.', type: 'select',
    options: [{ v: 'dark', l: 'Dark' }, { v: 'light', l: 'Light' }, { v: 'system', l: 'System' }],
    default: 'dark', category: 'appearance' },
  { key: 'density', label: 'Density', description: 'UI spacing density.', type: 'select',
    options: [{ v: 'comfortable', l: 'Comfortable' }, { v: 'compact', l: 'Compact' }],
    default: 'comfortable', category: 'appearance' },
  { key: 'fontSize', label: 'Font size', description: 'Base font size in pixels.', type: 'number',
    default: 14, min: 11, max: 20, category: 'appearance' },
  { key: 'reduceMotion', label: 'Reduce motion', description: 'Minimize animations.', type: 'boolean',
    default: false, category: 'appearance' },

  // ---- Chat & Composer ----
  { key: 'defaultMode', label: 'Default composer mode', description: 'Mode for new chats.', type: 'select',
    options: [{ v: 'chat', l: 'Chat' }, { v: 'think', l: 'Think' }, { v: 'agent', l: 'Agent' },
              { v: 'research', l: 'Research' }, { v: 'code', l: 'Code' }, { v: 'image', l: 'Image' }],
    default: 'chat', category: 'chat' },
  { key: 'thinkingDisplay', label: 'Thinking block', description: 'How to show model reasoning.', type: 'select',
    options: [{ v: 'expand', l: 'Always expand' }, { v: 'collapse', l: 'Collapsed' }, { v: 'hide', l: 'Hide' }],
    default: 'collapse', category: 'chat' },
  { key: 'defaultTemperature', label: 'Default temperature', type: 'number',
    default: 0.7, min: 0, max: 2, step: 0.1, category: 'chat',
    description: 'Creativity of responses.' },
  { key: 'defaultMaxTokens', label: 'Default max tokens', description: 'Max output length; Auto = provider default.', type: 'select',
    options: [{ v: 'auto', l: 'Auto' }, { v: '512', l: '512' }, { v: '1024', l: '1,024' },
              { v: '2048', l: '2,048' }, { v: '4096', l: '4,096' }, { v: '8192', l: '8,192' }],
    default: 'auto', category: 'chat' },
  { key: 'routingRules', label: 'Routing rules', description: 'Keyword → model mappings (JSON array).', type: 'string',
    default: '[]', category: 'models' },
  { key: 'modelCombos', label: 'Model combos', description: 'Named model chains (JSON array).', type: 'string',
    default: '[]', category: 'models' },
  { key: 'sendKey', label: 'Send key', description: 'Keyboard shortcut to send.', type: 'select',
    options: [{ v: 'ctrl+enter', l: 'Ctrl+Enter' }, { v: 'enter', l: 'Enter' }],
    default: 'ctrl+enter', category: 'chat' },
  { key: 'queueWhileStreaming', label: 'Queue while streaming', description: 'Allow typing the next message during generation.', type: 'boolean',
    default: true, category: 'chat' },
  { key: 'showThinking', label: 'Show thinking', description: 'Show the Thinking block by default.', type: 'boolean',
    default: true, category: 'chat' },

  // ---- Agents & Safety ----
  { key: 'agentMaxSteps', label: 'Default max steps', description: 'Max tool steps per agent run.', type: 'number',
    default: 8, min: 1, max: 25, category: 'agents' },
  { key: 'agentMaxCost', label: 'Max cost per run (USD)', description: 'Stop a run exceeding this cost. 0 = no limit.', type: 'number',
    default: 0, min: 0, max: 100, step: 0.1, category: 'agents' },
  { key: 'requireApproval', label: 'Require approval for', description: 'Tool types needing approval.', type: 'multiselect',
    options: [{ v: 'write_file', l: 'Write files' }, { v: 'run_bash', l: 'Run commands' },
              { v: 'mcp_write', l: 'MCP write tools' }],
    default: ['write_file', 'run_bash'], category: 'agents' },
  { key: 'notifyOnDone', label: 'Notify on completion', description: 'Browser notification when a run finishes.', type: 'boolean',
    default: true, category: 'agents' },

  // ---- Knowledge & Memory ----
  { key: 'memoryAutoExtract', label: 'Auto-extract memories', description: 'Save important facts from conversations.', type: 'boolean',
    default: true, category: 'knowledge' },
  { key: 'memoryScope', label: 'Memory scope', description: 'Where memories apply.', type: 'select',
    options: [{ v: 'global', l: 'Global' }, { v: 'project', l: 'Per project' }],
    default: 'global', category: 'knowledge' },
  { key: 'preCompactionSave', label: 'Save before compaction', description: 'Save trimmed context to memory first.', type: 'boolean',
    default: true, category: 'knowledge' },

  // ---- Voice ----
  { key: 'voiceAutoSpeak', label: 'Auto-speak responses', type: 'boolean',
    default: false, category: 'voice', description: 'Read responses aloud automatically.' },
  { key: 'voiceId', label: 'Voice', description: 'TTS voice.', type: 'string',
    default: '', category: 'voice' },
  { key: 'voiceSpeed', label: 'Speech speed', type: 'number',
    default: 1.0, min: 0.5, max: 2.0, step: 0.1, category: 'voice',
    description: 'Playback speed multiplier.' },

  // ---- Output ----
  { key: 'outputStyle', label: 'Output style', description: 'Default response style.', type: 'select',
    options: [{ v: 'normal', l: 'Normal' }, { v: 'concise', l: 'Concise' },
              { v: 'adhd', l: 'ADHD-friendly' }, { v: 'no-slop', l: 'No-slop' },
              { v: 'verbose', l: 'Verbose' }, { v: 'teacher', l: 'Teacher' }],
    default: 'normal', category: 'output' },
  { key: 'noSlop', label: 'No-slop cleanup', description: 'Remove AI writing clichés.', type: 'boolean',
    default: false, category: 'output' },
  { key: 'adhdFriendly', label: 'ADHD-friendly formatting', description: 'Answer-first, numbered steps, capped lists.', type: 'boolean',
    default: false, category: 'output' },
  { key: 'formality', label: 'Formality', description: 'How formal replies should read.', type: 'select',
    options: [{ v: 'casual', l: 'Casual' }, { v: 'neutral', l: 'Neutral' }, { v: 'formal', l: 'Formal' }],
    default: 'neutral', category: 'output' },
  { key: 'expertise', label: 'Technical depth', description: 'Match answers to your expertise.', type: 'select',
    options: [{ v: 'beginner', l: 'Beginner' }, { v: 'general', l: 'General' }, { v: 'expert', l: 'Expert' }],
    default: 'general', category: 'output' },

  // ---- Privacy ----
  { key: 'analyticsOptIn', label: 'Usage analytics', description: 'Local-only, opt-in.', type: 'boolean',
    default: false, category: 'privacy' },
];

/** Get the default value for a key. */
export function getDefault(key) {
  const s = SETTINGS_SCHEMA.find((x) => x.key === key);
  return s ? s.default : undefined;
}

/** Get all defaults as an object. */
export function getAllDefaults() {
  const out = {};
  for (const s of SETTINGS_SCHEMA) out[s.key] = s.default;
  return out;
}

/** Search settings by text. */
export function searchSettings(query) {
  const q = query.toLowerCase();
  return SETTINGS_SCHEMA.filter((s) =>
    s.label.toLowerCase().includes(q) ||
    (s.description || '').toLowerCase().includes(q) ||
    s.key.toLowerCase().includes(q));
}
