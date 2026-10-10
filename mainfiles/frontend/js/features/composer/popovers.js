/**
 * Composer popovers — Mode / Tools / Tune (Sangam-native, Phase 2).
 *
 * Replaces the scattered pill controls with three intent-grouped popovers:
 * - Mode: Chat, Think, Agent, Research, Code, Image
 * - Tools: web search, memory recall, image gen, voice reply, documents, MCP, code tools
 * - Tune: reasoning effort, token cap, temperature, output style, streaming, context %
 */
import { getSetting, setSetting } from '../../shared/settings_store.js';
import {
  getReasoningEffort, setReasoningEffort, getMaxTokens, setMaxTokens,
  getTemperature, setTemperature, getAgentModeEnabled, setAgentModeEnabled,
  getThinkingDisplay, setThinkingDisplayPref,
} from '../../core/state.js';

console.log('[Module] popovers.js loaded');

export const MODES = [
  { id: 'chat',     label: 'Chat',     icon: 'fa-comment',            desc: 'Normal conversation' },
  { id: 'think',    label: 'Think',    icon: 'fa-brain',              desc: 'Deep reasoning, shows thinking' },
  { id: 'agent',    label: 'Agent',    icon: 'fa-robot',              desc: 'Uses tools to get things done' },
  { id: 'research', label: 'Research', icon: 'fa-magnifying-glass',   desc: 'Web research with citations' },
  { id: 'code',     label: 'Code',     icon: 'fa-code',               desc: 'Code agent with file tools' },
  { id: 'image',    label: 'Image',    icon: 'fa-image',              desc: 'Generate images' },
];

let currentMode = 'chat';

export function getMode() { return currentMode; }
export function setMode(mode) {
  if (!MODES.some((m) => m.id === mode)) return;
  currentMode = mode;
  // Map modes to underlying state
  setAgentModeEnabled(mode === 'agent' || mode === 'code');
  if (mode === 'think' && getReasoningEffort() === 'none') setReasoningEffort('medium');
  document.dispatchEvent(new CustomEvent('sangam:mode-changed', { detail: { mode } }));
  renderModeButton();
}

function renderModeButton() {
  const btn = document.getElementById('modeBtn');
  const m = MODES.find((x) => x.id === currentMode);
  if (btn && m) {
    btn.innerHTML = `<i class="fa-solid ${m.icon}"></i><span>${m.label}</span><i class="fa-solid fa-chevron-down"></i>`;
    btn.dataset.mode = currentMode;
  }
}

const TOOL_DEFS = [
  { id: 'web_search',    label: 'Web search',    icon: 'fa-globe',             desc: 'Search the web for current info' },
  { id: 'memory_recall', label: 'Memory recall', icon: 'fa-brain',             desc: 'Recall from your memories' },
  { id: 'image_gen',     label: 'Image gen',     icon: 'fa-image',              desc: 'Generate images' },
  { id: 'voice_reply',   label: 'Voice reply',   icon: 'fa-volume-high',       desc: 'Speak the response aloud' },
  { id: 'documents',     label: 'Documents',     icon: 'fa-file-lines',        desc: 'Use attached documents' },
  { id: 'mcp_tools',     label: 'MCP tools',     icon: 'fa-plug',              desc: 'Use MCP server tools' },
  { id: 'code_tools',    label: 'Code tools',    icon: 'fa-code',              desc: 'File + shell tools' },
];

let enabledTools = new Set(['web_search', 'memory_recall', 'documents']);

export function getEnabledTools() { return [...enabledTools]; }
export function isToolEnabled(id) { return enabledTools.has(id); }
export function setToolEnabled(id, on) {
  if (on) enabledTools.add(id); else enabledTools.delete(id);
  document.dispatchEvent(new CustomEvent('sangam:tools-changed', { detail: { tools: [...enabledTools] } }));
  renderToolsButton();
}

function renderToolsButton() {
  const btn = document.getElementById('toolsBtn');
  if (btn) {
    const n = enabledTools.size;
    btn.innerHTML = `<i class="fa-solid fa-wrench"></i><span>Tools${n ? ` · ${n}` : ''}</span><i class="fa-solid fa-chevron-down"></i>`;
  }
}

function closeAllPopovers() {
  document.querySelectorAll('.composer-popover').forEach((p) => p.classList.add('hidden'));
}

export function initPopovers() {
  renderModeButton();
  renderToolsButton();

  // Mode popover
  const modeBtn = document.getElementById('modeBtn');
  const modePop = document.getElementById('modePopover');
  modeBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    const wasHidden = modePop.classList.contains('hidden');
    closeAllPopovers();
    if (wasHidden) {
      modePop.innerHTML = MODES.map((m) => `
        <button class="popover-option${m.id === currentMode ? ' selected' : ''}" data-mode="${m.id}">
          <i class="fa-solid ${m.icon}"></i>
          <span><strong>${m.label}</strong><small>${m.desc}</small></span>
          ${m.id === currentMode ? '<i class="fa-solid fa-check"></i>' : ''}
        </button>`).join('');
      modePop.classList.remove('hidden');
      modePop.querySelectorAll('[data-mode]').forEach((b) => {
        b.addEventListener('click', () => { setMode(b.dataset.mode); closeAllPopovers(); });
      });
    }
  });

  // Tools popover
  const toolsBtn = document.getElementById('toolsBtn');
  const toolsPop = document.getElementById('toolsPopover');
  toolsBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    const wasHidden = toolsPop.classList.contains('hidden');
    closeAllPopovers();
    if (wasHidden) {
      toolsPop.innerHTML = TOOL_DEFS.map((t) => `
        <label class="popover-check">
          <input type="checkbox" data-tool="${t.id}"${enabledTools.has(t.id) ? ' checked' : ''}>
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
        <div class="tune-row"><label>Temperature <span id="tuneTempVal"></span></label>
          <input type="range" id="tuneTemp" min="0" max="2" step="0.1"></div>
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
