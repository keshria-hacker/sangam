/**
 * RunLog — shared live execution log component (Sangam-native).
 *
 * Used by Code Agent, Design Studio, Agent mode, and (later) Teams/Learn.
 * Renders thought / tool_call / tool_result / done / error steps.
 * One implementation, no copy-paste.
 */
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] runlog.js loaded');

/**
 * Append a step to a log container. Returns the created element.
 * step: { kind, content, tool }
 */
export function appendStep(logEl, step) {
  const div = document.createElement('div');
  div.className = `rl-step rl-${step.kind}`;
  const text = step.content || '';
  if (step.kind === 'thought') {
    if (!text || text === 'Agent starting…' || text === 'Starting code agent…') return div;
    div.innerHTML = `<div class="rl-thought">${escapeHtml(text).replace(/\n/g, '<br>')}</div>`;
  } else if (step.kind === 'tool_call') {
    div.innerHTML = `<div class="rl-tool"><i class="fa-solid fa-wrench"></i> <code>${escapeHtml(step.tool || '')}</code>`
      + `<span class="rl-args">${escapeHtml(text.slice(0, 160))}</span></div>`;
  } else if (step.kind === 'tool_result') {
    const ok = !text.includes('"error"');
    div.innerHTML = `<details class="rl-result ${ok ? '' : 'rl-error'}">`
      + `<summary>${ok ? 'Result' : 'Error'} <span class="rl-tool-name">${escapeHtml(step.tool || '')}</span></summary>`
      + `<pre>${escapeHtml(text.slice(0, 3000))}</pre></details>`;
  } else if (step.kind === 'done' || step.kind === 'answer') {
    div.innerHTML = `<div class="rl-done"><i class="fa-solid fa-circle-check"></i> ${escapeHtml(text).replace(/\n/g, '<br>')}</div>`;
  } else if (step.kind === 'error') {
    div.innerHTML = `<div class="rl-error-msg"><i class="fa-solid fa-triangle-exclamation"></i> ${escapeHtml(text)}</div>`;
  }
  if (div.innerHTML) {
    logEl.appendChild(div);
    logEl.scrollTop = logEl.scrollHeight;
  }
  return div;
}

/** Clear a log container. */
export function clearLog(logEl) {
  logEl.innerHTML = '';
}
