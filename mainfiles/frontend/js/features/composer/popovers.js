/**
 * Composer popovers — Auto mode / Tools / Tune (perfect-flow spec §3.2).
 *
 * Auto is a mode selector, not a button. Options: Auto (default),
 * Answer only, Research, Code, Create, Agent. In Auto the
 * response-intelligence pipeline decides the tools; the Tools popover
 * shows what Auto chose for the current composer text (via a dry-run
 * POST /intelligence/route, which never calls a provider) and any
 * checkbox change there is a per-message override — it is consumed by
 * the next send and then cleared, never persisted. In Manual tool mode
 * (Settings → Chat → Tool Mode) the toggles are persistent instead.
 *
 * There is deliberately NO Runs button here: run history lives in
 * Agents → Run History (today: Work → Activity, until the IA swap
 * re-homes it) and in the response action menu ("View run").
 *
 * Legacy mode ids (chat/think/agent/research/code/image) still work
 * through setMode(), mapped onto the composer modes, so older callers
 * (slash commands, presets) keep working.
 */
import { getSetting, setSetting } from '../../shared/settings_store.js';
import { apiFetch } from '../../shared/http.js';
import {
  getReasoningEffort, setReasoningEffort, getMaxTokens, setMaxTokens,
  getTemperature, setTemperature, getAgentModeEnabled, setAgentModeEnabled,
  getThinkingDisplay, setThinkingDisplayPref,
} from '../../core/state.js';

console.log('[Module] popovers.js loaded');

export const COMPOSER_MODES = [
  { id: 'auto',     label: 'Auto',        icon: 'fa-wand-magic-sparkles', desc: 'Pipeline decides: answer, search, code, create, or agent' },
  { id: 'answer',   label: 'Answer only', icon: 'fa-comment',            desc: 'Direct answer, no tools or search' },
  { id: 'research', label: 'Research',    icon: 'fa-magnifying-glass',   desc: 'Web research with citations' },
  { id: 'code',     label: 'Code',        icon: 'fa-code',               desc: 'Code agent with file tools' },
  { id: 'create',   label: 'Create',      icon: 'fa-pen-nib',            desc: 'Artifacts, diagrams, images' },
  { id: 'agent',    label: 'Agent',       icon: 'fa-robot',              desc: 'Uses tools to get things done, with approval' },
];
// Back-compat name: older code imported MODES.
export const MODES = COMPOSER_MODES;

const LEGACY_MODE_MAP = {
  chat: 'auto', think: 'auto', agent: 'agent',
  research: 'research', code: 'code', image: 'create',
};

let currentMode = 'auto';

export function getComposerMode() { return currentMode; }
export function getMode() { return currentMode; }
export function setComposerMode(mode) {
  if (!COMPOSER_MODES.some((m) => m.id === mode)) return;
  currentMode = mode;
  // Code mode keeps the legacy code-agent path; agent mode keeps the
  // agent path; every other composer mode streams normally.
  setAgentModeEnabled(mode === 'agent' || mode === 'code');
  document.dispatchEvent(new CustomEvent('sangam:mode-changed', { detail: { mode } }));
  renderModeButton();
}
export function setMode(mode) {
  if (mode === 'think' && getReasoningEffort() === 'none') setReasoningEffort('medium');
  setComposerMode(LEGACY_MODE_MAP[mode] || mode);
}

function renderModeButton() {
  const btn = document.getElementById('modeBtn');
  const m = COMPOSER_MODES.find((x) => x.id === currentMode);
  if (btn && m) {
    btn.innerHTML = `<i class="fa-solid ${m.icon}"></i><span>${m.label}</span><i class="fa-solid fa-chevron-down"></i>`;
    btn.dataset.mode = currentMode;
  }
}

const TOOL_DEFS = [
  { id: 'web_search',          label: 'Web search',          icon: 'fa-globe',       desc: 'Search the web for current info' },
  { id: 'deep_crawl',          label: 'Deep crawl',          icon: 'fa-spider',      desc: 'Follow sources beyond the first results' },
  { id: 'code_execution',      label: 'Code execution',      icon: 'fa-terminal',    desc: 'Run code in the sandbox' },
  { id: 'browser',             label: 'Browser',             icon: 'fa-window-maximize', desc: 'Open pages and read them like a user' },
  { id: 'image',               label: 'Image',               icon: 'fa-image',       desc: 'Generate images' },
  { id: 'memory_recall',       label: 'Memory recall',       icon: 'fa-brain',       desc: 'Recall from your memories' },
  { id: 'artifact_generation', label: 'Artifact generation', icon: 'fa-file-code',   desc: 'Build files, pages, and diagrams' },
];

// Persistent toggle set (Manual tool mode, and the fallback display set).
let enabledTools = new Set(['web_search', 'memory_recall']);
if (getSetting('webSearchEnabled') === false) enabledTools.delete('web_search');
// Per-message overrides (Auto tool mode only): tool id -> bool, consumed
// by the next send and then cleared. Never persisted.
let messageOverrides = new Map();
// Last Auto decision for the current composer text (dry-run only).
let autoChosen = null;

export function getToolMode() { return getSetting('toolMode') || 'auto'; }
export function getEffectiveTools() {
  if (getToolMode() === 'auto' && autoChosen) {
    const out = new Set(autoChosen);
    messageOverrides.forEach((on, id) => { if (on) out.add(id); else out.delete(id); });
    return [...out];
  }
  return [...enabledTools];
}
export function getEnabledTools() { return getEffectiveTools(); }
export function isToolEnabled(id) { return getEffectiveTools().includes(id); }
export function setToolEnabled(id, on) {
  if (!TOOL_DEFS.some((t) => t.id === id)) return;
  if (getToolMode() === 'auto') {
    // Auto: this message only. The next send consumes and clears it.
    messageOverrides.set(id, on);
  } else {
    if (on) enabledTools.add(id); else enabledTools.delete(id);
    if (id === 'web_search') setSetting('webSearchEnabled', on);
  }
  document.dispatchEvent(new CustomEvent('sangam:tools-changed', { detail: { tools: getEffectiveTools() } }));
  renderToolsButton();
}
/** Overrides for the next send; clears the per-message map. */
export function getMessageToolOverrides() { return Object.fromEntries(messageOverrides); }
export function consumeMessageToolOverrides() {
  const out = getMessageToolOverrides();
  messageOverrides.clear();
  return out;
}
export function clearMessageToolOverrides() { messageOverrides.clear(); }

function renderToolsButton() {
  const btn = document.getElementById('toolsBtn');
  if (btn) {
    const n = getEffectiveTools().length;
    btn.innerHTML = `<i class="fa-solid fa-wrench"></i><span>Tools${n ? ` · ${n}` : ''}</span><i class="fa-solid fa-chevron-down"></i>`;
  }
}

function closeAllPopovers() {
  document.querySelectorAll('.composer-popover').forEach((p) => p.classList.add('hidden'));
}

/** Dry-run Auto routing for the current composer text. Never a provider call. */
async function fetchAutoChosen(text) {
  if (!text || !text.trim()) return null;
  try {
    const res = await apiFetch('/intelligence/route', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    }, false);
    if (!res.ok) return null;
    const data = await res.json();
    return new Set(Array.isArray(data.tools) ? data.tools : []);
  } catch {
    return null;
  }
}

export function initPopovers() {
  const savedMode = getSetting('composerMode');
  if (COMPOSER_MODES.some((m) => m.id === savedMode)) currentMode = savedMode;
  renderModeButton();
  renderToolsButton();
  document.addEventListener('sangam:settings-changed', (event) => {
    if (event.detail?.key === 'webSearchEnabled') {
      const enabled = event.detail.value !== false;
      if (enabled) enabledTools.add('web_search');
      else enabledTools.delete('web_search');
      document.dispatchEvent(new CustomEvent('sangam:tools-changed', { detail: { tools: getEffectiveTools() } }));
      renderToolsButton();
    }
    if (event.detail?.key === 'composerMode' && COMPOSER_MODES.some((m) => m.id === event.detail.value)) {
      currentMode = event.detail.value;
      setAgentModeEnabled(currentMode === 'agent' || currentMode === 'code');
      renderModeButton();
    }
    if (event.detail?.key === 'toolMode') renderToolsButton();
  });

  // Mode popover (Auto is the default; the pipeline decides in Auto).
  const modeBtn = document.getElementById('modeBtn');
  const modePop = document.getElementById('modePopover');
  modeBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    const wasHidden = modePop.classList.contains('hidden');
    closeAllPopovers();
    if (wasHidden) {
      modePop.innerHTML = COMPOSER_MODES.map((m) => `
        <button class="popover-option${m.id === currentMode ? ' selected' : ''}" data-mode="${m.id}">
          <i class="fa-solid ${m.icon}"></i>
          <span><strong>${m.label}</strong><small>${m.desc}</small></span>
          ${m.id === currentMode ? '<i class="fa-solid fa-check"></i>' : ''}
        </button>`).join('');
      modePop.classList.remove('hidden');
      modePop.querySelectorAll('[data-mode]').forEach((b) => {
        b.addEventListener('click', () => {
          setComposerMode(b.dataset.mode);
          setSetting('composerMode', b.dataset.mode);
          closeAllPopovers();
        });
      });
    }
  });

  // Tools popover: in Auto it shows what Auto chose for the current text
  // and lets the user override for this message only; in Manual the
  // toggles are persistent.
  const toolsBtn = document.getElementById('toolsBtn');
  const toolsPop = document.getElementById('toolsPopover');
  toolsBtn?.addEventListener('click', async (e) => {
    e.stopPropagation();
    const wasHidden = toolsPop.classList.contains('hidden');
    closeAllPopovers();
    if (wasHidden) {
      const auto = getToolMode() === 'auto' && currentMode === 'auto';
      if (auto) {
        const text = document.getElementById('messageInput')?.value || '';
        autoChosen = await fetchAutoChosen(text);
        renderToolsButton();
      }
      const effective = new Set(getEffectiveTools());
      const note = auto
        ? (autoChosen
          ? `Auto chose ${autoChosen.size ? [...autoChosen].join(', ') : 'no tools'} for this message. Changes here apply to this message only.`
          : 'Auto decides on send. Changes here apply to this message only.')
        : 'Manual tool mode: these toggles stay on for every message.';
      toolsPop.innerHTML = `<div class="popover-note">${note}</div>` + TOOL_DEFS.map((t) => `
        <label class="popover-check">
          <input type="checkbox" data-tool="${t.id}"${effective.has(t.id) ? ' checked' : ''}>
          <i class="fa-solid ${t.icon}"></i>
          <span><strong>${t.label}</strong><small>${t.desc}</small></span>
        </label>`).join('');
      toolsPop.classList.remove('hidden');
      toolsPop.querySelectorAll('[data-tool]').forEach((cb) => {
        cb.addEventListener('change', () => setToolEnabled(cb.dataset.tool, cb.checked));
      });
    }
  });

  // Tune popover
  const tuneBtn = document.getElementById('tuneBtn');
  const tunePop = document.getElementById('tunePopover');
  tuneBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    const wasHidden = tunePop.classList.contains('hidden');
    closeAllPopovers();
    if (wasHidden) {
      tunePop.innerHTML = `
        <div class="tune-row"><label>Reasoning effort</label>
          <select id="tuneEffort">
            <option value="none">Auto</option><option value="low">Low</option>
            <option value="medium">Medium</option><option value="high">High</option>
            <option value="extra_high">Extra High</option>
          </select></div>
        <div class="tune-row"><label>Max tokens</label>
          <select id="tuneTokens">
            <option value="auto">Auto</option><option value="512">512</option>
            <option value="1024">1,024</option><option value="2048">2,048</option>
            <option value="4096">4,096</option><option value="8192">8,192</option>
          </select></div>
        <div class="tune-row"><label>Temperature</label>
          <span class="tune-temp"><span id="tuneTempVal"></span><input type="range" id="tuneTemp" min="0" max="2" step="0.1"></span></div>
        <div class="tune-row"><label>Output style</label>
          <select id="tuneStyle">
            <option value="normal">Normal</option><option value="concise">Concise</option>
            <option value="adhd">ADHD-friendly</option><option value="no-slop">No-slop</option>
            <option value="verbose">Verbose</option><option value="teacher">Teacher</option>
          </select></div>
        <div class="tune-row"><label>Thinking block</label>
          <select id="tuneThinking">
            <option value="expand">Always expand</option><option value="collapse">Collapsed</option>
            <option value="hide">Hide</option>
          </select></div>`;
      tunePop.classList.remove('hidden');
      // Init values
      tunePop.querySelector('#tuneEffort').value = getReasoningEffort();
      tunePop.querySelector('#tuneTokens').value = getMaxTokens();
      const tempEl = tunePop.querySelector('#tuneTemp');
      tempEl.value = getTemperature();
      tunePop.querySelector('#tuneTempVal').textContent = getTemperature().toFixed(1);
      tunePop.querySelector('#tuneStyle').value = getSetting('outputStyle') || 'normal';
      tunePop.querySelector('#tuneThinking').value = getThinkingDisplay();
      // Wire
      tunePop.querySelector('#tuneEffort').addEventListener('change', (e) => setReasoningEffort(e.target.value));
      tunePop.querySelector('#tuneTokens').addEventListener('change', (e) => setMaxTokens(e.target.value));
      tempEl.addEventListener('input', (e) => {
        setTemperature(parseFloat(e.target.value));
        tunePop.querySelector('#tuneTempVal').textContent = parseFloat(e.target.value).toFixed(1);
      });
      tunePop.querySelector('#tuneStyle').addEventListener('change', (e) => setSetting('outputStyle', e.target.value));
      tunePop.querySelector('#tuneThinking').addEventListener('change', (e) => setThinkingDisplayPref(e.target.value));
    }
  });

  document.addEventListener('click', (e) => {
    if (!e.target.closest('.composer-popover') && !e.target.closest('#modeBtn,#toolsBtn,#tuneBtn')) {
      closeAllPopovers();
    }
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeAllPopovers();
  });
}
