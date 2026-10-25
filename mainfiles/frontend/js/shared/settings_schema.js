/**
 * Settings schema — single source of truth for all user settings (Sangam-native).
 *
 * Each setting: { key, label, description, type, default, category, options? }
 * Types: 'boolean' | 'string' | 'number' | 'select' | 'multiselect'
 *
 * The Settings page renders from this schema: searchable, resettable,
 * persisted server-side via /user/settings (localStorage as cache).
 */
// A1 perfect-flow (§7): the 17 spec sections, in spec order. Every
// setting in the codebase lives in exactly one of these; a section
// with no backing setting yet renders an honest "no settings" note
// (see settings_page.js) instead of a fake control. Legacy category
// ids (knowledge, research, voice_output, devices) redirect in
// settings_page.js so old deep-links keep landing somewhere real.
export const SETTING_CATEGORIES = [
  { id: 'general',    label: 'General',            icon: 'fa-gear' },
  { id: 'appearance', label: 'Appearance',         icon: 'fa-palette' },
  { id: 'chat',       label: 'Chat & Responses',   icon: 'fa-comment' },
  { id: 'models',     label: 'Models & Providers', icon: 'fa-server' },
  { id: 'tools',      label: 'Tools',              icon: 'fa-wrench' },
  { id: 'memory',     label: 'Memory & Knowledge', icon: 'fa-brain' },
  { id: 'projects',   label: 'Projects & Context', icon: 'fa-folder-open' },
  { id: 'agents',     label: 'Agents & Automation', icon: 'fa-robot' },
  { id: 'skills',     label: 'Skills & Library',   icon: 'fa-puzzle-piece' },
  { id: 'connectors', label: 'Connectors & MCP',   icon: 'fa-plug' },
  { id: 'voice',      label: 'Voice & Audio',      icon: 'fa-microphone' },
  { id: 'image',      label: 'Image & Video',      icon: 'fa-image' },
  { id: 'security',   label: 'Security',           icon: 'fa-shield-halved' },
  { id: 'data',       label: 'Data & Privacy',     icon: 'fa-database' },
  { id: 'code',       label: 'Appearance of code', icon: 'fa-code' },
  { id: 'advanced',   label: 'Advanced',           icon: 'fa-flask' },
  { id: 'about',      label: 'About',              icon: 'fa-circle-info' },
];

/** Old settings-category ids -> current section (deep-link compat). */
export const LEGACY_SETTING_SECTIONS = {
  knowledge: 'memory',
  research: 'tools',
  voice_output: 'voice',
  devices: 'security',
};

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
  // A1 design tokens (§6.2, §7 Appearance): consumed live by
  // features/settings/appearance.js — accent, font, radius, motion.
  { key: 'accentColor', label: 'Accent colour', description: 'Accent used for actions and selected states. Empty = theme default.', type: 'string',
    default: '', category: 'appearance' },
  { key: 'fontFamily', label: 'Font family', description: 'Interface font. System uses your OS default sans-serif.', type: 'select',
    options: [{ v: 'default', l: 'Default (Inter/Sora)' }, { v: 'system', l: 'System sans-serif' }, { v: 'mono', l: 'Monospace' }],
    default: 'default', category: 'appearance' },
  { key: 'cornerRadius', label: 'Corner radius', description: 'How rounded cards and buttons look.', type: 'select',
    options: [{ v: 'small', l: 'Small' }, { v: 'medium', l: 'Medium' }, { v: 'large', l: 'Large' }],
    default: 'medium', category: 'appearance' },
  { key: 'motionIntensity', label: 'Motion intensity', description: 'Animation speed. Reduced pairs with Reduce motion above.', type: 'select',
    options: [{ v: 'full', l: 'Full' }, { v: 'reduced', l: 'Reduced' }, { v: 'none', l: 'None' }],
    default: 'full', category: 'appearance' },

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
  // A4 agent-runtime defaults (Agents & Automation). These mirror the
  // task defaults in backend/agent_runtime; the task form still lets
  // each task override them. schedulerEnabled is the opt-in loop flag.
  { key: 'agentRuntime.defaultApprovalPolicy', label: 'Default task approval policy', description: 'Per-task approval policy for new tasks: default (sensitive tools ask), once, always, or deny. Blacklisted calls are denied under every policy.', type: 'select',
    options: [{ v: 'default', l: 'Default' }, { v: 'once', l: 'Once' }, { v: 'always', l: 'Always' }, { v: 'deny', l: 'Deny' }],
    default: 'default', category: 'agents' },
  { key: 'agentRuntime.tokenBudget', label: 'Default token budget per task', description: 'Token budget for new tasks; 0 = unlimited. Exceeding it stops the run.', type: 'number',
    default: 0, min: 0, category: 'agents' },
  { key: 'agentRuntime.costBudgetUsd', label: 'Default cost budget per task (USD)', description: 'Cost budget for new tasks; 0 = unlimited. Only enforced on reported (known) usage, never on estimates.', type: 'number',
    default: 0.0, min: 0, step: 0.01, category: 'agents' },
  { key: 'agentRuntime.maxConcurrentTasks', label: 'Max concurrent tasks', description: 'Cap on tasks the scheduler tick runs in one pass (safety bound).', type: 'number',
    default: 3, min: 1, max: 20, category: 'agents' },
  { key: 'agentRuntime.circuitErrorThreshold', label: 'Circuit breaker: consecutive errors', description: 'Failed steps in a row before the circuit trips and stops the run.', type: 'number',
    default: 5, min: 1, max: 50, category: 'agents' },
  { key: 'agentRuntime.circuitVelocityPerMin', label: 'Circuit breaker: steps per minute', description: 'Steps started inside 60s before the circuit trips (runaway-loop guard).', type: 'number',
    default: 30, min: 1, max: 600, category: 'agents' },
  { key: 'agentRuntime.circuitNoProgressSteps', label: 'Circuit breaker: no-progress steps', description: 'Consecutive steps with empty or unchanged output before the circuit trips.', type: 'number',
    default: 3, min: 1, max: 50, category: 'agents' },
  { key: 'agentRuntime.notifyOnTaskDone', label: 'Notify on task completion', description: 'In-app notification when a task completes, fails, needs approval, exceeds budget, or trips the circuit.', type: 'boolean',
    default: true, category: 'agents' },
  { key: 'agentRuntime.schedulerEnabled', label: 'Enable background scheduler', description: 'Opt-in scheduler loop; off by default so tests never get surprise runs. The tick endpoint works regardless. Requires restart to take effect.', type: 'boolean',
    default: false, category: 'agents', requiresRestart: true },

  // ---- Knowledge & Memory ----
  { key: 'memoryAutoExtract', label: 'Auto-extract memories', description: 'Save important facts from conversations.', type: 'boolean',
    default: true, category: 'memory' },
  // A3 (perfect-flow Projects, Memory & Knowledge): retention and
  // project-scope controls are user-visible settings, not .env-only.
  // memoryRetentionDays is advisory (0 = keep forever): the privacy
  // dashboard previews and runs the forget; nothing auto-deletes
  // without the user confirming there.
  { key: 'memoryRetentionDays', label: 'Memory retention (days)', description: 'Dashboard forget preview uses this many days by default. 0 = keep memories forever; nothing is auto-deleted.', type: 'number',
    default: 0, min: 0, max: 3650, category: 'memory' },
  { key: 'projectMemoryScope', label: 'Default project memory scope', description: 'New projects retrieve only their own sources (project) or all uploads (global). Per-project override on the project itself.', type: 'select',
    options: [{ v: 'project', l: 'Project only' }, { v: 'global', l: 'Global' }],
    default: 'project', category: 'projects' },
  { key: 'projectContextTopK', label: 'Project retrieval results', description: 'How many chunks project-scoped retrieval returns.', type: 'number',
    default: 5, min: 1, max: 20, category: 'projects' },

  // ---- Research ----
  { key: 'webSearchEnabled', label: 'Web search', description: 'Allow current web results to be added to research and chat responses.', type: 'boolean',
    default: true, category: 'tools' },
  { key: 'webSearchMaxResults', label: 'Results per search', description: 'Maximum number of sources to use for a web search.', type: 'number',
    default: 5, min: 1, max: 10, category: 'tools' },

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
    default: 'normal', category: 'chat' },
  { key: 'noSlop', label: 'No-slop cleanup', description: 'Removes named AI clichés (delve into, tapestry, crucial, furthermore…) from responses at save time. Edit only — use the De-slop preview Detect mode to audit without rewriting.', type: 'boolean',
    default: false, category: 'chat' },
  { key: 'adhdFriendly', label: 'ADHD-friendly formatting', description: 'Post-hoc formatting only: strips throat-clearing openers, reflows paragraphs over 600 chars, caps lists at 5 items with a +N more note. The prompt-level ADHD style block is also injected into chat when this is on (see /api/quality/adhd-style).', type: 'boolean',
    default: false, category: 'chat' },
  { key: 'formality', label: 'Formality', description: 'How formal replies should read.', type: 'select',
    options: [{ v: 'casual', l: 'Casual' }, { v: 'neutral', l: 'Neutral' }, { v: 'formal', l: 'Formal' }],
    default: 'neutral', category: 'chat' },
  { key: 'expertise', label: 'Technical depth', description: 'Match answers to your expertise.', type: 'select',
    options: [{ v: 'beginner', l: 'Beginner' }, { v: 'general', l: 'General' }, { v: 'expert', l: 'Expert' }],
    default: 'general', category: 'chat' },

  // ---- Privacy ----
  { key: 'analyticsOptIn', label: 'Usage analytics', description: 'Local-only, opt-in.', type: 'boolean',
    default: false, category: 'data' },

  // ---- Devices & LAN (Batch 6) ----
  { key: 'LAN_ENABLED', label: 'Allow devices on my Wi-Fi (LAN mode)',
    description: 'Opt-in, off by default. Lets a phone on the same Wi-Fi pair with this laptop and use the same Sangam. Pairing still needs your approval on this laptop.',
    type: 'boolean', default: false, category: 'security' },
  { key: 'LAN_ALLOW_HTTP', label: 'Allow unencrypted LAN (HTTP fallback)',
    description: 'Off by default. Only turn on if a phone browser rejects the self-signed certificate. While on, anyone on this Wi-Fi can read your traffic.',
    type: 'boolean', default: false, category: 'security' },

  // ---- Tools: web search provider (env WEB_SEARCH_PROVIDER has the
  // same name; the live test in Tools uses this value when set) ----
  { key: 'webSearchProvider', label: 'Web search provider', description: 'Search backend for the Tools test and chat research. Empty = free default (DuckDuckGo). A provider key is set in Models & Providers → provider keys where the provider supports it.', type: 'string',
    default: '', category: 'tools' },

  // ---- Models & Providers: A6 capability warnings / cost routing ----
  { key: 'providers.preflight_warnings', label: 'Model capability warnings', description: 'Show "this model can\'t do X" before sending when the model lacks a requested capability (server preflight; unknown models say unknown, never supported).', type: 'boolean',
    default: true, category: 'models' },
  { key: 'providers.cost_ranked_routing', label: 'Cost-ranked fallback', description: 'Order fallback candidates cheapest-first; unknown prices sort last, never as cheap.', type: 'boolean',
    default: true, category: 'models' },

  // ---- Skills & Library: A6 registry status (read-only, honest) ----
  { key: 'marketplace.registry_status', label: 'Skill registry status', description: 'Read-only: the remote registry is a stub in this build; local and git sources work. This value is informational and changing it enables nothing.', type: 'string',
    default: 'stub', category: 'skills', readonly: true },

  // ---- Image & Video: A6 studio defaults ----
  { key: 'studio.diagrams.default_accent', label: 'Default diagram accent', description: 'Single accent colour applied to new diagrams and SVG exports.', type: 'string',
    default: '#3A7BD5', category: 'image' },
  { key: 'studio.diagrams.default_font', label: 'Default diagram font', description: 'Font family for diagram text.', type: 'string',
    default: 'Inter, system-ui, sans-serif', category: 'image' },
  { key: 'studio.classroom.mp4_export', label: 'Classroom MP4 export', description: 'Not available in this build — no MP4 export service exists, so this control is disabled rather than faking an export.', type: 'string',
    default: 'off', category: 'image', unavailable: true },

  // ---- Appearance of code: A5 code-graph cap + code theme ----
  // (spec §7 calls this section "Appearance of code"; the A5 spec/QA
  // behaviour keys live here too so code tooling has one home.)
  { key: 'spec_tdd_required', label: 'Require TDD evidence', description: 'Spec v2 implement stage requires RED + GREEN test evidence for every task; a green-only claim is rejected.', type: 'boolean',
    default: true, category: 'code' },
  { key: 'spec_greencontract_min_level', label: 'Minimum verification level', description: 'Lowest GreenContract level that must pass before the verify stage; levels are cumulative.', type: 'select',
    options: [{ v: 'targeted', l: 'Targeted' }, { v: 'package', l: 'Package' }, { v: 'integration', l: 'Integration' }, { v: 'full', l: 'Full' }],
    default: 'targeted', category: 'code' },
  { key: 'qa_replay_strict', label: 'Strict replay comparison', description: 'Replay compares status and noise-normalized body exactly; any drift fails the case instead of warning.', type: 'boolean',
    default: true, category: 'code' },
  { key: 'code_graph_max_files', label: 'Code graph file cap', description: 'Maximum files indexed per graph build.', type: 'number',
    default: 500, min: 10, max: 5000, category: 'code' },
  { key: 'codeTheme', label: 'Code theme', description: 'Syntax highlighting theme for code blocks. Auto follows the light/dark theme.', type: 'select',
    options: [{ v: 'auto', l: 'Auto' }, { v: 'github-dark', l: 'GitHub Dark' }, { v: 'github', l: 'GitHub Light' }],
    default: 'auto', category: 'code' },

  // ---- Advanced: A5 deploy interface (deferred connectors) ----
  // Enabling these alone deploys nothing: /api/deploy/connectors
  // reports both connectors as deferred, and every deploy requires
  // approval when implemented (deploy_require_approval).
  { key: 'deploy_coolify_enabled', label: 'Coolify connector', description: 'Enable the (deferred) Coolify deploy connector. Off until implemented; enabling it alone deploys nothing.', type: 'boolean',
    default: false, category: 'advanced' },
  { key: 'deploy_coolify_url', label: 'Coolify instance URL', description: 'Base URL of the Coolify instance to deploy to, when implemented. Empty = unconfigured.', type: 'string',
    default: '', category: 'advanced' },
  { key: 'deploy_quickemu_enabled', label: 'Quickemu VM / sandbox launch', description: 'Enable the (deferred) Quickemu VM/sandbox launcher (developer mode only when implemented).', type: 'boolean',
    default: false, category: 'advanced' },
  { key: 'deploy_require_approval', label: 'Require approval per deploy', description: 'Every deploy or VM launch must be explicitly approved before it runs, even for the owner.', type: 'boolean',
    default: true, category: 'advanced' },
  { key: 'deploy_sandbox_mode', label: 'Sandbox mode for generated apps', description: 'Preview (sandboxed preview only) or isolated (isolated VM/sandbox when available).', type: 'select',
    options: [{ v: 'preview', l: 'Preview' }, { v: 'isolated', l: 'Isolated' }],
    default: 'preview', category: 'advanced' },
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
