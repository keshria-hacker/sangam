/**
 * Code Agent tab — autonomous coding agent UI (Sangam-native).
 * Task input + live execution log (thoughts, tool calls, results).
 */
import { apiFetch } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
import { appendStep, clearLog } from '../../shared/runlog.js';

console.log('[Module] code-agent.js loaded');

/**
 * Render the Code Agent into a tab body.
 */
async function renderCodeAgentView(bodyEl) {
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
    const jobsMod = await import('../../core/jobs.js');
    const jobId = jobsMod.startJob({ kind: 'code-agent', title: task.slice(0, 60), abort: () => abort?.abort() });

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
        jobsMod.finishJob(jobId, 'failed', String(err?.message || err));
      } else {
        jobsMod.finishJob(jobId, 'done');
      }
    } finally {
      const job = jobsMod.getJobs().find((j) => j.id === jobId);
      if (job && job.status === 'running') jobsMod.finishJob(jobId, 'done');
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

// ---------------------------------------------------------------------------
// Merged Code page (Phase 8 B7 + D1).
//
// Sub-views: Code Agent | Spec Wizard.
// The spec wizard (POST /spec/build, POST /spec/to-task) had no frontend;
// it now lives here instead of a new tab.
// ---------------------------------------------------------------------------

const CODE_SUBVIEWS = [
  { id: 'agent', label: 'Code Agent',  icon: 'fa-code' },
  { id: 'spec',  label: 'Spec Wizard', icon: 'fa-list-check' },
];

/** Merged Code page — the rail 'Code' entry renders this. */
export async function renderCodePage(bodyEl) {
  bodyEl.innerHTML = `
    <div class="code-page">
      <div class="library-tabs" role="tablist" aria-label="Code sections">
        ${CODE_SUBVIEWS.map((t, i) => `
          <button class="library-tab${i === 0 ? ' active' : ''}" role="tab"
            data-codesub="${t.id}" aria-selected="${i === 0}">
            <i class="fa-solid ${t.icon}"></i> ${t.label}
          </button>`).join('')}
      </div>
      <div class="code-subbody" id="codeSubBody"></div>
    </div>`;
  const subBody = bodyEl.querySelector('#codeSubBody');
  const show = (id) => {
    bodyEl.querySelectorAll('[data-codesub]').forEach((b) => {
      const on = b.dataset.codesub === id;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', String(on));
    });
    if (id === 'agent') renderCodeAgentView(subBody);
    else renderSpecWizard(subBody);
  };
  bodyEl.querySelectorAll('[data-codesub]').forEach((b) => {
    b.addEventListener('click', () => show(b.dataset.codesub));
  });
  await renderCodeAgentView(subBody);
}

/** D1: spec wizard — build a spec doc, optionally convert to a Code Agent task. */
function renderSpecWizard(container) {
  container.innerHTML = `
    <div class="spec-wizard">
      <p class="settings-hint">Describe the feature; the wizard builds a structured spec you can hand to the Code Agent.</p>
      <div class="spec-form">
        <label>Title<input class="provider-key-input" data-spec="title" placeholder="Feature title"></label>
        <label>Problem<textarea class="provider-key-input" data-spec="problem" rows="3" placeholder="What problem does this solve?"></textarea></label>
        <label>Goals<textarea class="provider-key-input" data-spec="goals" rows="3" placeholder="Goals, one per line"></textarea></label>
        <label>Constraints<textarea class="provider-key-input" data-spec="constraints" rows="2" placeholder="Constraints, one per line"></textarea></label>
        <label>Plan<textarea class="provider-key-input" data-spec="plan" rows="3" placeholder="Plan steps, one per line"></textarea></label>
        <label>Tasks<textarea class="provider-key-input" data-spec="tasks" rows="3" placeholder="Tasks, one per line"></textarea></label>
      </div>
      <div style="display:flex;gap:8px;margin-top:12px">
        <button class="btn-primary btn-sm" type="button" data-spec-build>Build spec</button>
        <button class="btn-secondary btn-sm" type="button" data-spec-task>Build &amp; send to Code Agent</button>
      </div>
      <div class="spec-output" data-spec-output style="margin-top:12px"></div>
    </div>`;

  const vals = () => {
    const o = {};
    container.querySelectorAll('[data-spec]').forEach((el) => { o[el.dataset.spec] = el.value.trim(); });
    return o;
  };
  const out = container.querySelector('[data-spec-output]');

  container.querySelector('[data-spec-build]').addEventListener('click', async () => {
    const body = vals();
    if (!body.title) { showToast({ type: 'info', title: 'Give the spec a title' }); return; }
    out.innerHTML = '<p class="settings-hint">Building…</p>';
    try {
      const data = await (await apiFetch('/spec/build', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })).json();
      out.innerHTML = `<h4>Spec</h4><pre class="lib-skill-md">${escapeHtml(data.spec || '')}</pre>`;
    } catch (err) {
      out.innerHTML = `<p class="team-error">Build failed: ${escapeHtml(err?.message || String(err))}</p>`;
    }
  });

  container.querySelector('[data-spec-task]').addEventListener('click', async () => {
    const body = vals();
    if (!body.title) { showToast({ type: 'info', title: 'Give the spec a title' }); return; }
    out.innerHTML = '<p class="settings-hint">Building…</p>';
    try {
      const data = await (await apiFetch('/spec/to-task', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })).json();
      out.innerHTML = `<h4>Code Agent task</h4><pre class="lib-skill-md">${escapeHtml(data.task || '')}</pre>
        <button class="btn-primary btn-sm" type="button" data-spec-run style="margin-top:8px">Open in Code Agent</button>`;
      out.querySelector('[data-spec-run]').addEventListener('click', () => {
        container.closest('.code-page')?.querySelector('[data-codesub="agent"]')?.click();
        setTimeout(() => {
          const taskEl = container.closest('.code-page')?.querySelector('#caTask');
          if (taskEl) { taskEl.value = data.task || ''; taskEl.focus(); }
        }, 100);
      });
    } catch (err) {
      out.innerHTML = `<p class="team-error">Build failed: ${escapeHtml(err?.message || String(err))}</p>`;
    }
  });
}
