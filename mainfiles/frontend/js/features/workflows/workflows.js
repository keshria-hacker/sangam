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
        <h3>Canvas</h3>
        <div id="wfCanvas"><details class="advanced-section"><summary>How workflows work</summary><p class="settings-hint">Open a workflow's canvas from its row above to drag nodes, connect them, and edit configs — cycles are rejected on save, and the latest run colours each node by its result.</p></details></div>
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
      box.innerHTML = '<p class="settings-hint">No workflows yet. Start from a ready-made template, or create one above.</p><button class="btn-primary btn-sm" id="wfStartTemplate" type="button">Start from a template</button>';
      box.querySelector('#wfStartTemplate')?.addEventListener('click', () => {
        import('../tabs/tabs.js').then((m) => m.showToolSection('work', 'devqa'));
      });
      return;
    }
    box.innerHTML = items.map((w) => `
      <div class="kn-mem" data-id="${escapeHtml(w.id)}">
        <span class="kn-mem-content"><strong>${escapeHtml(w.name)}</strong> · trigger ${escapeHtml(w.trigger)}</span>
        <input type="text" class="provider-key-input wf-run-input" placeholder='Run input JSON, e.g. {"name": "Ada"}' aria-label="Run input JSON" style="flex:1">
        <button class="btn-secondary wf-run-btn">Run</button>
        <button class="btn-secondary wf-runs-btn">Runs</button>
        <button class="btn-secondary wf-canvas-btn">Canvas</button>
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
    box.querySelectorAll('.wf-canvas-btn').forEach((btn) => {
      btn.addEventListener('click', () => openCanvas(bodyEl, btn.closest('.kn-mem').dataset.id));
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

// ---------------------------------------------------------------------------
// Batch 3: visual canvas. This is NOT decoration over the JSON editor: it
// edits the same definition (nodes carry x/y, which the engine ignores),
// validates through the same PUT endpoint (cycles are a 422, shown
// inline), and colours nodes from the latest run's node_results, so a
// failed node (dead letter) is visible on the canvas itself.
// ---------------------------------------------------------------------------

const CANVAS_NODE_TYPES = {
  text: { template: 'Hello {{input.name}}' },
  transform: { op: 'upper' },
  retrieve: { query: '{{input.q}}', top_k: 5 },
  memory_save: { content: '{{input.text}}', kind: 'semantic' },
  http_fetch: { url: 'https://example.com' },
  llm: { prompt: '{{input.q}}' },
  agent: { team: 'research', task: '{{input.task}}' },
  tool: { tool: 'web_search', args: { query: '{{input.q}}' } },
  code: { expression: 'len(input) + 1' },
  condition: { left: '{{input.n}}', op: '>', right: '5' },
  loop: { items: '["a", "b"]', item_template: 'got {{item}}' },
  crawl: { url: 'https://example.com', max_pages: 5, max_depth: 1 },
  extract: { pattern: '(?P<word>[a-z]+)' },
  prompt_transform: { system: 'You are helpful.', user: '{{input.q}}' },
};

async function openCanvas(bodyEl, workflowId) {
  const box = bodyEl.querySelector('#wfCanvas');
  box.innerHTML = '<p class="settings-hint">Loading canvas…</p>';
  let wf;
  try {
    wf = await (await apiFetch(`/workflows/${encodeURIComponent(workflowId)}`)).json();
  } catch {
    box.innerHTML = '<p class="settings-hint">Could not load workflow.</p>';
    return;
  }
  const def = wf.definition || { nodes: [], edges: [] };
  def.nodes = def.nodes || [];
  def.edges = def.edges || [];
  def.nodes.forEach((n, i) => {
    if (typeof n.x !== 'number') n.x = 20 + (i % 3) * 220;
    if (typeof n.y !== 'number') n.y = 20 + Math.floor(i / 3) * 110;
  });
  let selectedId = def.nodes[0]?.id || null;
  let lastResults = null;

  function render() {
    box.innerHTML = `
      <div class="wf-canvas-head">
        <strong>${escapeHtml(wf.name)}</strong> <span class="settings-hint">v${wf.version || 1} · drag nodes to move them; click one to edit it.</span>
        <div class="kn-mem-controls">
          <select id="wfCanvasAddType" class="provider-key-input" aria-label="Node type to add">
            ${Object.keys(CANVAS_NODE_TYPES).map((t) => `<option value="${t}">${t}</option>`).join('')}
          </select>
          <button class="btn-secondary" id="wfCanvasAddBtn">Add node</button>
          <button class="btn-primary" id="wfCanvasSaveBtn">Save canvas</button>
          <button class="btn-secondary" id="wfCanvasRunBtn">Run</button>
        </div>
        <p class="settings-hint" id="wfCanvasStatus"></p>
      </div>
      <div class="wf-canvas" id="wfCanvasArea">
        <svg id="wfCanvasEdges" class="wf-canvas-edges"></svg>
        ${def.nodes.map((n) => {
          const st = lastResults?.[n.id]?.status || '';
          return `<div class="wf-node wf-node-${st}" data-node="${escapeHtml(n.id)}"
            style="left:${n.x}px;top:${n.y}px" role="button" tabindex="0" aria-label="Node ${escapeHtml(n.id)}">
            <strong>${escapeHtml(n.id)}</strong><span>${escapeHtml(n.type)}</span>
            ${st ? `<span class="wf-node-status">${escapeHtml(st)}</span>` : ''}
          </div>`;
        }).join('')}
      </div>
      <div class="wf-canvas-editor" id="wfCanvasEditor"></div>`;
    drawEdges(box);
    wireCanvas(bodyEl, box, wf, def, () => selectedId, (id) => { selectedId = id; renderEditor(); });
    renderEditor();
  }

  function drawEdges(scope) {
    const svg = scope.querySelector('#wfCanvasEdges');
    if (!svg) return;
    const area = scope.querySelector('#wfCanvasArea');
    const w = area.clientWidth || 700;
    const h = area.clientHeight || 420;
    svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
    svg.innerHTML = def.edges.map((e) => {
      const a = def.nodes.find((n) => n.id === e.from);
      const b = def.nodes.find((n) => n.id === e.to);
      if (!a || !b) return '';
      return `<line x1="${a.x + 70}" y1="${a.y + 28}" x2="${b.x + 70}" y2="${b.y + 28}" class="wf-edge" />`;
    }).join('');
  }

  function renderEditor() {
    const ed = box.querySelector('#wfCanvasEditor');
    if (!ed) return;
    const node = def.nodes.find((n) => n.id === selectedId);
    if (!node) { ed.innerHTML = '<p class="settings-hint">Select a node to edit it.</p>'; return; }
    const last = lastResults?.[node.id];
    ed.innerHTML = `
      <h4>Node: ${escapeHtml(node.id)}</h4>
      <div class="kn-mem-controls">
        <label>Type <select id="wfEdType" class="provider-key-input">
          ${Object.keys(CANVAS_NODE_TYPES).map((t) => `<option value="${t}"${t === node.type ? ' selected' : ''}>${t}</option>`).join('')}
        </select></label>
        <label>Run only if <input type="text" id="wfEdRunIf" class="provider-key-input" placeholder="{{nodes.check.branch}}" value="${escapeHtml(node.run_if || '')}"></label>
        <button class="btn-secondary" id="wfEdDelete">Delete node</button>
      </div>
      <label>Config (JSON)</label>
      <textarea id="wfEdConfig" class="provider-key-input" rows="6" style="width:100%;font-family:monospace">${escapeHtml(JSON.stringify(node.config || {}, null, 2))}</textarea>
      ${last ? `<p class="settings-hint">Last run: ${escapeHtml(last.status)}${last.error ? ` — ${escapeHtml(last.error.slice(0, 200))}` : ''}</p>` : ''}
      <div class="kn-mem-controls">
        <label>Edge from <select id="wfEdFrom" class="provider-key-input">${def.nodes.map((n) => `<option value="${escapeHtml(n.id)}">${escapeHtml(n.id)}</option>`).join('')}</select></label>
        <label>to <select id="wfEdTo" class="provider-key-input">${def.nodes.map((n) => `<option value="${escapeHtml(n.id)}">${escapeHtml(n.id)}</option>`).join('')}</select></label>
        <button class="btn-secondary" id="wfEdAddEdge">Add edge</button>
      </div>
      <div>${def.edges.map((e) => `<span class="lib-kind">${escapeHtml(e.from)} → ${escapeHtml(e.to)} <button class="icon-btn wf-edge-del" data-from="${escapeHtml(e.from)}" data-to="${escapeHtml(e.to)}" aria-label="Delete edge">×</button></span> `).join('') || '<p class="settings-hint">No edges yet.</p>'}</div>`;
    ed.querySelector('#wfEdType').addEventListener('change', (e) => {
      node.type = e.target.value;
      node.config = { ...(CANVAS_NODE_TYPES[node.type] || {}) };
      render();
    });
    ed.querySelector('#wfEdRunIf').addEventListener('change', (e) => {
      node.run_if = e.target.value.trim() || undefined;
      if (!node.run_if) delete node.run_if;
    });
    ed.querySelector('#wfEdConfig').addEventListener('change', (e) => {
      try { node.config = JSON.parse(e.target.value); }
      catch { showToast({ type: 'error', title: 'Config is not valid JSON' }); }
    });
    ed.querySelector('#wfEdDelete').addEventListener('click', () => {
      def.nodes = def.nodes.filter((n) => n.id !== node.id);
      def.edges = def.edges.filter((e) => e.from !== node.id && e.to !== node.id);
      selectedId = def.nodes[0]?.id || null;
      render();
    });
    ed.querySelector('#wfEdAddEdge').addEventListener('click', () => {
      const from = ed.querySelector('#wfEdFrom').value;
      const to = ed.querySelector('#wfEdTo').value;
      if (from === to) { showToast({ type: 'error', title: 'A node cannot connect to itself' }); return; }
      if (!def.edges.some((e) => e.from === from && e.to === to)) def.edges.push({ from, to });
      render();
    });
    ed.querySelectorAll('.wf-edge-del').forEach((btn) => {
      btn.addEventListener('click', () => {
        def.edges = def.edges.filter((e) => !(e.from === btn.dataset.from && e.to === btn.dataset.to));
        render();
      });
    });
  }

  function wireCanvas(bodyElScope, scope, wfObj, defObj, getSelected, setSelected) {
    scope.querySelector('#wfCanvasAddBtn').addEventListener('click', () => {
      const type = scope.querySelector('#wfCanvasAddType').value;
      let base = type;
      let i = 1;
      while (defObj.nodes.some((n) => n.id === base)) base = `${type}${++i}`;
      defObj.nodes.push({ id: base, type, config: { ...(CANVAS_NODE_TYPES[type] || {}) },
                          x: 20 + (defObj.nodes.length % 3) * 220, y: 20 + Math.floor(defObj.nodes.length / 3) * 110 });
      setSelected(base);
      render();
    });
    scope.querySelector('#wfCanvasSaveBtn').addEventListener('click', async () => {
      const status = scope.querySelector('#wfCanvasStatus');
      try {
        const res = await apiFetch(`/workflows/${encodeURIComponent(workflowId)}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: wfObj.name, definition: defObj, trigger: wfObj.trigger || 'manual', enabled: wfObj.enabled !== false }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        wfObj.version = data.version;
        status.textContent = `Saved (v${data.version}).`;
        showToast({ type: 'success', title: 'Workflow saved' });
        loadWorkflows(bodyElScope);
      } catch (err) {
        status.textContent = `Save failed: ${err?.message || String(err)}`;
      }
    });
    scope.querySelector('#wfCanvasRunBtn').addEventListener('click', async () => {
      const status = scope.querySelector('#wfCanvasStatus');
      try {
        const res = await apiFetch(`/workflows/${encodeURIComponent(workflowId)}/run`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ input: {} }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
        lastResults = data.node_results || null;
        status.textContent = `Run ${data.status}.`;
        render();
        loadRuns(bodyElScope, workflowId);
      } catch (err) {
        status.textContent = `Run failed: ${err?.message || String(err)}`;
      }
    });
    scope.querySelectorAll('[data-node]').forEach((el) => {
      el.addEventListener('click', () => { setSelected(el.dataset.node); render(); });
      el.addEventListener('pointerdown', (e) => {
        const node = defObj.nodes.find((n) => n.id === el.dataset.node);
        if (!node) return;
        const startX = e.clientX - node.x;
        const startY = e.clientY - node.y;
        const move = (ev) => {
          node.x = Math.max(0, ev.clientX - startX);
          node.y = Math.max(0, ev.clientY - startY);
          el.style.left = `${node.x}px`;
          el.style.top = `${node.y}px`;
          drawEdges(scope);
        };
        const up = () => {
          document.removeEventListener('pointermove', move);
          document.removeEventListener('pointerup', up);
        };
        document.addEventListener('pointermove', move);
        document.addEventListener('pointerup', up);
      });
    });
  }

  render();
}
