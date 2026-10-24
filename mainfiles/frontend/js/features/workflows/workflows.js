/**
 * Workflows tab — Phase 3 (all-in-one plan): visual DAG workflows.
 *
 * The builder here is deliberately a JSON definition editor, not a
 * drag-and-drop canvas: a canvas that cannot validate cycles or show
 * node results is decoration, and this tab must show real runs. The
 * definition format is documented inline (node types, edges) and the
 * example pre-fills a working two-node workflow. Runs show per-node
 * status, including the failed node (dead letter) on a failed run.
 */
import { apiFetch } from '../../shared/http.js';
import { escapeHtml } from '../../shared/utils.js';
import { showToast } from '../../shared/toast.js';

console.log('[Module] workflows.js loaded');

const EXAMPLE = JSON.stringify({
  nodes: [
    { id: 'greet', type: 'text', config: { template: 'Hello {{input.name}}' } },
    { id: 'shout', type: 'transform', config: { op: 'upper' } },
  ],
  edges: [{ from: 'greet', to: 'shout' }],
}, null, 2);

export async function renderWorkflowsTab(bodyEl) {
  bodyEl.innerHTML = `
    <div class="library">
      <h2>Workflows</h2>
      <p class="settings-hint">Typed DAG nodes: text, transform, retrieve, memory_save, http_fetch. No arbitrary code nodes. Runs are idempotent by key, replayable, and keep failed nodes as dead letters.</p>
      <section>
        <h3>Create workflow</h3>
        <div class="kn-mem-controls">
          <input type="text" id="wfName" class="provider-key-input" placeholder="Workflow name" aria-label="Workflow name" style="flex:1">
          <button class="btn-secondary" id="wfCreateBtn">Create</button>
        </div>
        <textarea id="wfDefinition" class="provider-key-input" rows="12" style="width:100%;margin-top:8px;font-family:monospace" aria-label="Workflow definition JSON">${escapeHtml(EXAMPLE)}</textarea>
        <div id="wfCreateStatus" class="settings-hint"></div>
      </section>
      <section>
        <h3>Your workflows</h3>
        <div id="wfList" class="kn-mem-list"></div>
      </section>
      <section>
        <h3>Workflow runs</h3>
        <div id="wfRuns" class="kn-mem-list"><p class="settings-hint">Select a workflow and run it to see runs here.</p></div>
      </section>
    </div>`;

  bodyEl.querySelector('#wfCreateBtn').addEventListener('click', async () => {
    const name = bodyEl.querySelector('#wfName').value.trim();
    const status = bodyEl.querySelector('#wfCreateStatus');
    let definition;
    try {
      definition = JSON.parse(bodyEl.querySelector('#wfDefinition').value);
    } catch {
      status.textContent = 'Definition is not valid JSON.';
      return;
    }
    if (!name) { status.textContent = 'Give the workflow a name.'; return; }
    try {
      const res = await apiFetch('/workflows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, definition, trigger: 'manual' }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      status.textContent = `Created. Webhook: ${data.webhook_url} (token shown once — copy it now).`;
      showToast({ type: 'success', title: 'Workflow created' });
      loadWorkflows(bodyEl);
    } catch (err) {
      status.textContent = `Create failed: ${err?.message || String(err)}`;
    }
  });

  loadWorkflows(bodyEl);
}

async function loadWorkflows(bodyEl) {
  const box = bodyEl.querySelector('#wfList');
  box.innerHTML = '<p class="settings-hint">Loading…</p>';
  try {
    const data = await (await apiFetch('/workflows')).json();
    const items = data.workflows || [];
    if (!items.length) {
      box.innerHTML = '<p class="settings-hint">No workflows yet. Create one above.</p>';
      return;
    }
    box.innerHTML = items.map((w) => `
      <div class="kn-mem" data-id="${escapeHtml(w.id)}">
        <span class="kn-mem-content"><strong>${escapeHtml(w.name)}</strong> · trigger ${escapeHtml(w.trigger)}</span>
        <input type="text" class="provider-key-input wf-run-input" placeholder='Run input JSON, e.g. {"name": "Ada"}' aria-label="Run input JSON" style="flex:1">
        <button class="btn-secondary wf-run-btn">Run</button>
        <button class="btn-secondary wf-runs-btn">Runs</button>
        <button class="icon-btn wf-del-btn" title="Delete workflow" aria-label="Delete workflow"><i class="fa-solid fa-trash"></i></button>
      </div>`).join('');
    box.querySelectorAll('.wf-run-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const row = btn.closest('.kn-mem');
        const id = row.dataset.id;
        let input = {};
        try {
          input = JSON.parse(row.querySelector('.wf-run-input').value || '{}');
        } catch {
          showToast({ type: 'error', title: 'Run input is not valid JSON' });
          return;
        }
        try {
          const res = await apiFetch(`/workflows/${encodeURIComponent(id)}/run`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ input }),
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
          showToast({ type: data.status === 'succeeded' ? 'success' : 'error', title: `Run ${data.status}` });
          loadRuns(bodyEl, id);
        } catch (err) {
          showToast({ type: 'error', title: 'Run failed', message: err?.message || String(err) });
        }
      });
    });
    box.querySelectorAll('.wf-runs-btn').forEach((btn) => {
      btn.addEventListener('click', () => loadRuns(bodyEl, btn.closest('.kn-mem').dataset.id));
    });
    box.querySelectorAll('.wf-del-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.closest('.kn-mem').dataset.id;
        if (!confirm('Delete this workflow and its runs?')) return;
        await apiFetch(`/workflows/${encodeURIComponent(id)}`, { method: 'DELETE' });
        loadWorkflows(bodyEl);
      });
    });
  } catch {
    box.innerHTML = '<p class="settings-hint">Could not load workflows.</p>';
  }
}

async function loadRuns(bodyEl, workflowId) {
  const box = bodyEl.querySelector('#wfRuns');
  box.innerHTML = '<p class="settings-hint">Loading runs…</p>';
  try {
    const data = await (await apiFetch(`/workflows/${encodeURIComponent(workflowId)}/runs`)).json();
    const runs = data.runs || [];
    if (!runs.length) {
      box.innerHTML = '<p class="settings-hint">No runs yet.</p>';
      return;
    }
    box.innerHTML = runs.map((r) => {
      const nodes = Object.entries(r.node_results || {}).map(([nid, nr]) =>
        `${escapeHtml(nid)}: ${escapeHtml(nr.status)}${nr.error ? ` — ${escapeHtml(nr.error.slice(0, 120))}` : ''}`).join('<br>');
      return `<div class="kn-mem">
        <span class="kn-mem-content"><strong>${escapeHtml(r.status)}</strong>${r.error ? ` — ${escapeHtml(r.error.slice(0, 120))}` : ''}<br>${nodes}</span>
        <button class="btn-secondary wf-replay-btn" data-run="${escapeHtml(r.id)}">Replay</button>
      </div>`;
    }).join('');
    box.querySelectorAll('.wf-replay-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        await apiFetch(`/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(btn.dataset.run)}/replay`, { method: 'POST' });
        loadRuns(bodyEl, workflowId);
      });
    });
  } catch {
    box.innerHTML = '<p class="settings-hint">Could not load runs.</p>';
  }
}
