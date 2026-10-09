/**
 * Code Agent tab — autonomous coding agent UI (Sangam-native).
 * Task input + live execution log (thoughts, tool calls, results).
 */
import { apiFetch } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { appendStep, clearLog } from '../../shared/runlog.js';

console.log('[Module] code-agent.js loaded');

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
          <label class="ca-tdd"><input type="checkbox" id="caTdd"> TDD mode</label>
          <button class="btn-primary" id="caRun" type="button"><i class="fa-solid fa-play"></i> Run agent</button>
          <button class="btn-secondary hidden" id="caStop" type="button"><i class="fa-solid fa-stop"></i> Stop</button>
        </div>
      </div>
      <div class="ca-log" id="caLog">
        <div class="no-results">The agent will inspect your workspace, edit files, and run commands here. Nothing runs until you press Run.</div>
      </div>
      <details class="ca-explore">
        <summary><i class="fa-solid fa-diagram-project"></i> Explore code map</summary>
        <div class="ca-explore-row">
          <select id="caMapQuery" class="provider-key-input">
            <option value="explain">What calls / uses…</option>
            <option value="path">How do A and B connect…</option>
          </select>
          <input type="text" id="caMapTarget" class="provider-key-input" placeholder="symbol name, or 'A -> B'">
          <button class="btn-secondary btn-sm" id="caMapGo" type="button">Ask</button>
        </div>
        <pre class="ca-map-out hidden" id="caMapOut"></pre>
      </details>
    </div>`;

  const taskEl = bodyEl.querySelector('#caTask');
  const runBtn = bodyEl.querySelector('#caRun');
  const stopBtn = bodyEl.querySelector('#caStop');
  const logEl = bodyEl.querySelector('#caLog');
  let abort = null;

  runBtn.addEventListener('click', async () => {
    const task = taskEl.value.trim();
    if (!task) { showToast({ type: 'info', message: 'Describe the task first.' }); return; }
    const maxIterations = parseInt(bodyEl.querySelector('#caIters').value, 10) || 12;
    const tddMode = bodyEl.querySelector('#caTdd').checked;
    runBtn.classList.add('hidden');
    stopBtn.classList.remove('hidden');
    clearLog(logEl);
    abort = new AbortController();

    try {
      const res = await apiFetch('/code-agent/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task, max_iterations: maxIterations, tdd_mode: tddMode }),
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
            appendStep(logEl, step);
          } catch { /* partial */ }
        }
      }
    } catch (err) {
      if (err?.name !== 'AbortError') {
        appendStep(logEl, { kind: 'error', content: String(err?.message || err) });
      }
    } finally {
      runBtn.classList.remove('hidden');
      stopBtn.classList.add('hidden');
      abort = null;
    }
  });

  stopBtn.addEventListener('click', () => { abort?.abort(); });

  // Code map explorer
  bodyEl.querySelector('#caMapGo').addEventListener('click', async () => {
    const query = bodyEl.querySelector('#caMapQuery').value;
    const target = bodyEl.querySelector('#caMapTarget').value.trim();
    const out = bodyEl.querySelector('#caMapOut');
    if (!target) { showToast({ type: 'info', message: 'Enter a symbol name.' }); return; }
    out.classList.remove('hidden');
    out.textContent = 'Analyzing…';
    try {
      const res = await apiFetch('/code-agent/code-map', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, target }),
      });
      const data = await res.json();
      out.textContent = JSON.stringify(data, null, 2).slice(0, 4000);
    } catch (err) {
      out.textContent = 'Error: ' + (err?.message || err);
    }
  });

  setTimeout(() => taskEl.focus(), 0);
}
