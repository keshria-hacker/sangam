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
  { id: 'chat',        label: 'Chat & Composer',    icon: 'fa-comment' },
  { id: 'models',      label: 'Models & Routing',   icon: 'fa-server' },
  { id: 'agents',      label: 'Agents & Safety',    icon: 'fa-robot' },
  { id: 'knowledge',   label: 'Knowledge & Memory', icon: 'fa-brain' },
  { id: 'research',    label: 'Research & Web',     icon: 'fa-globe' },
  { id: 'voice_output', label: 'Voice & Output',    icon: 'fa-microphone' },
  // Batch 6: LAN pairing + paired devices live here, not as a new tab.
  { id: 'devices',     label: 'Devices',            icon: 'fa-mobile-screen' },
  // Phase 8 C: 14 categories merged to 7. Removed: workspace, create, library,
  // shortcuts, privacy (analyticsOptIn -> general), doctor (-> models),
  // learn/insights are sub-pages not settings categories.
];

export const SETTINGS_SCHEMA = [
  // ---- General ----
  { key: 'language', label: 'Language', description: 'Interface language.', type: 'select',
    options: [{ v: 'en', l: 'English' }, { v: 'hi', l: 'Hindi' }], default: 'en', category: 'general' },

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
  // A2 composer modes (spec §3.2): Auto is the default; the pipeline
  // decides answer/search/code/create/agent per message. Consumed by
  // features/composer/popovers.js and features/chat/chat.js.
  { key: 'composerMode', label: 'Composer mode', description: 'Mode for the composer. Auto (default) lets the response-intelligence pipeline decide whether to answer, search, code, create, or run an agent — no user action needed.', type: 'select',
    options: [{ v: 'auto', l: 'Auto' }, { v: 'answer', l: 'Answer only' }, { v: 'research', l: 'Research' },
              { v: 'code', l: 'Code' }, { v: 'create', l: 'Create' }, { v: 'agent', l: 'Agent' }],
    default: 'auto', category: 'chat' },
  { key: 'toolMode', label: 'Tool mode', description: 'Auto: the Tools popover shows what Auto chose and changes apply to this message only. Manual: Tools toggles stay on for every message.', type: 'select',
    options: [{ v: 'auto', l: 'Auto' }, { v: 'manual', l: 'Manual' }],
    default: 'auto', category: 'chat' },
  { key: 'adaptiveDepth', label: 'Adaptive depth follow-ups', description: 'Offer "explain more" / "short version" follow-ups based on novice vs expert signals in your message.', type: 'boolean',
    default: true, category: 'chat' },
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
  { key: 'showThinking', label: 'Show thinking', description: 'Show the Thinking block by default.', type: 'boolean',
    default: true, category: 'chat' },

  // ---- Agents & Safety ----
  { key: 'agentMaxSteps', label: 'Default max steps', description: 'Max tool steps per agent run.', type: 'number',
    default: 8, min: 1, max: 25, category: 'agents' },
  { key: 'requireApproval', label: 'Require approval for', description: 'Tool types needing approval.', type: 'multiselect',
    options: [{ v: 'write_file', l: 'Write files' }, { v: 'run_bash', l: 'Run commands' },
              { v: 'mcp_write', l: 'MCP write tools' }],
    default: ['write_file', 'run_bash'], category: 'agents' },
  { key: 'notifyOnDone', label: 'Notify on completion', description: 'Browser notification when a run finishes.', type: 'boolean',
    default: true, category: 'agents' },

  // ---- Knowledge & Memory ----
  { key: 'memoryAutoExtract', label: 'Auto-extract memories', description: 'Save important facts from conversations.', type: 'boolean',
    default: true, category: 'knowledge' },

  // ---- Research ----
  { key: 'webSearchEnabled', label: 'Web search', description: 'Allow current web results to be added to research and chat responses.', type: 'boolean',
    default: true, category: 'research' },
  { key: 'webSearchMaxResults', label: 'Results per search', description: 'Maximum number of sources to use for a web search.', type: 'number',
    default: 5, min: 1, max: 10, category: 'research' },

  // ---- Voice ----
  { key: 'voiceAutoSpeak', label: 'Auto-speak responses', type: 'boolean',
    default: false, category: 'voice_output', description: 'Read responses aloud automatically.' },
  { key: 'voiceId', label: 'Voice', description: 'TTS voice.', type: 'string',
    default: '', category: 'voice_output' },
  { key: 'voiceSpeed', label: 'Speech speed', type: 'number',
    default: 1.0, min: 0.5, max: 2.0, step: 0.1, category: 'voice_output',
    description: 'Playback speed multiplier.' },

  // ---- Output ----
  { key: 'outputStyle', label: 'Output style', description: 'Default response style.', type: 'select',
    options: [{ v: 'normal', l: 'Normal' }, { v: 'concise', l: 'Concise' },
              { v: 'adhd', l: 'ADHD-friendly' }, { v: 'no-slop', l: 'No-slop' },
              { v: 'verbose', l: 'Verbose' }, { v: 'teacher', l: 'Teacher' }],
    default: 'normal', category: 'voice_output' },
  { key: 'noSlop', label: 'No-slop cleanup', description: 'Removes named AI clichés (delve into, tapestry, crucial, furthermore…) from responses at save time. Edit only — use the De-slop preview Detect mode to audit without rewriting.', type: 'boolean',
    default: false, category: 'voice_output' },
  { key: 'adhdFriendly', label: 'ADHD-friendly formatting', description: 'Post-hoc formatting only: strips throat-clearing openers, reflows paragraphs over 600 chars, caps lists at 5 items with a +N more note. The prompt-level ADHD style block is also injected into chat when this is on (see /api/quality/adhd-style).', type: 'boolean',
    default: false, category: 'voice_output' },
  { key: 'formality', label: 'Formality', description: 'How formal replies should read.', type: 'select',
    options: [{ v: 'casual', l: 'Casual' }, { v: 'neutral', l: 'Neutral' }, { v: 'formal', l: 'Formal' }],
    default: 'neutral', category: 'voice_output' },
  { key: 'expertise', label: 'Technical depth', description: 'Match answers to your expertise.', type: 'select',
    options: [{ v: 'beginner', l: 'Beginner' }, { v: 'general', l: 'General' }, { v: 'expert', l: 'Expert' }],
    default: 'general', category: 'voice_output' },

  // ---- Privacy ----
  { key: 'analyticsOptIn', label: 'Usage analytics', description: 'Local-only, opt-in.', type: 'boolean',
    default: false, category: 'general' },

  // ---- Devices & LAN (Batch 6) ----
  { key: 'LAN_ENABLED', label: 'Allow devices on my Wi-Fi (LAN mode)',
    description: 'Opt-in, off by default. Lets a phone on the same Wi-Fi pair with this laptop and use the same Sangam. Pairing still needs your approval on this laptop.',
    type: 'boolean', default: false, category: 'devices' },
  { key: 'LAN_ALLOW_HTTP', label: 'Allow unencrypted LAN (HTTP fallback)',
    description: 'Off by default. Only turn on if a phone browser rejects the self-signed certificate. While on, anyone on this Wi-Fi can read your traffic.',
    type: 'boolean', default: false, category: 'devices' },
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
