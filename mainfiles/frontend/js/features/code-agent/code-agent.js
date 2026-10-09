/**
 * Code Agent tab — autonomous coding agent UI (Sangam-native).
 * Task input + live execution log (thoughts, tool calls, results).
 */
import { apiFetch } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] code-agent.js loaded');

function stepNode(step) {
  const div = document.createElement('div');
  div.className = `ca-step ca-${step.kind}`;
  if (step.kind === 'thought') {
    div.innerHTML = `<div class="ca-thought">${escapeHtml(step.content).replace(/\n/g, '<br>')}</div>`;
  } else if (step.kind === 'tool_call') {
    div.innerHTML = `<div class="ca-tool"><i class="fa-solid fa-wrench"></i> <code>${escapeHtml(step.tool || '')}</code></div>`;
  } else if (step.kind === 'tool_result') {
    const ok = !step.content.includes('"error"');
    div.innerHTML = `<details class="ca-result ${ok ? '' : 'ca-error'}">
      <summary>${ok ? 'Result' : 'Error'} <span class="ca-tool-name">${escapeHtml(step.tool || '')}</span></summary>
      <pre>${escapeHtml(step.content.slice(0, 3000))}</pre>
    </details>`;
  } else if (step.kind === 'done') {
    div.innerHTML = `<div class="ca-done"><i class="fa-solid fa-circle-check"></i> ${escapeHtml(step.content).replace(/\n/g, '<br>')}</div>`;
  } else if (step.kind === 'error') {
    div.innerHTML = `<div class="ca-error-msg"><i class="fa-solid fa-triangle-exclamation"></i> ${escapeHtml(step.content)}</div>`;
  }
  return div;
}

/**
 * Render the Code Agent into a tab body.
 */
export function renderCodeAgentTab(bodyEl) {
  bodyEl.innerHTML = `
    <div class="code-agent">
      <div class="ca-input-row">
        <textarea id="caTask" rows="3" placeholder="Describe the coding task — e.g. 'Add input validation to the signup form and write a test'…" aria-label="Coding task"></textarea>
        <div class="ca-controls">
          <label class="ca-iter">Max steps
            <select id="caIters" class="provider-key-input">
              <option value="6">6</option>
              <option value="12" selected>12</option>
              <option value="20">20</option>
            </select>
          </label>
          <button class="btn-primary" id="caRun" type="button"><i class="fa-solid fa-play"></i> Run agent</button>
          <button class="btn-secondary hidden" id="caStop" type="button"><i class="fa-solid fa-stop"></i> Stop</button>
        </div>
      </div>
      <div class="ca-log" id="caLog">
        <div class="no-results">The agent will inspect your workspace, edit files, and run commands here. Nothing runs until you press Run.</div>
      </div>
    </div>`;

  const taskEl = bodyEl.querySelector('#caTask');
  const runBtn = bodyEl.querySelector('#caRun');
  const stopBtn = bodyEl.querySelector('#caStop');
  const logEl = bodyEl.querySelector('#caLog');
  let abort = null;

  function scrollLog() { logEl.scrollTop = logEl.scrollHeight; }

  runBtn.addEventListener('click', async () => {
    const task = taskEl.value.trim();
    if (!task) { showToast({ type: 'info', message: 'Describe the task first.' }); return; }
    const maxIterations = parseInt(bodyEl.querySelector('#caIters').value, 10) || 12;
    runBtn.classList.add('hidden');
    stopBtn.classList.remove('hidden');
    logEl.innerHTML = '';
    abort = new AbortController();

    try {
      const res = await apiFetch('/code-agent/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task, max_iterations: maxIterations }),
        signal: abort.signal,
      });
      if (!res.ok && res.status !== 200) throw new Error(`HTTP ${res.status}`);
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop();
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith('data:')) continue;
          try {
            const step = JSON.parse(line.slice(5).trim());
            if (step.kind === 'end') continue;
            logEl.appendChild(stepNode(step));
            scrollLog();
          } catch { /* partial */ }
        }
      }
    } catch (err) {
      if (err?.name !== 'AbortError') {
        logEl.appendChild(stepNode({ kind: 'error', content: String(err?.message || err) }));
        scrollLog();
      }
    } finally {
      runBtn.classList.remove('hidden');
      stopBtn.classList.add('hidden');
      abort = null;
    }
  });

  stopBtn.addEventListener('click', () => { abort?.abort(); });
  setTimeout(() => taskEl.focus(), 0);
}
