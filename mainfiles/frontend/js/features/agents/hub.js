/**
 * Agent Hub — built-in catalog + custom agents CRUD + runs (Sangam-native, Phase 3).
 *
 * Exports renderAgentHub(bodyEl). Parent wires it as a tab renderer.
 */
import { apiFetch } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
import { appendStep, clearLog } from '../../shared/runlog.js';

console.log('[Module] hub.js loaded');

// Built-in agents catalog (static)
const BUILTINS = [
  { id: 'researcher', name: 'Researcher', icon: 'fa-magnifying-glass',
    desc: 'Web research with cited answers.', tools: ['web_search'] },
  { id: 'coder', name: 'Coder', icon: 'fa-code',
    desc: 'Writes and edits code, runs commands.', tools: ['list_files', 'read_file', 'write_file', 'edit_file', 'run_bash', 'execute_code', 'code_map'] },
  { id: 'writer', name: 'Writer', icon: 'fa-pen',
    desc: 'Drafts and refines prose. No tools, pure language.', tools: [] },
  { id: 'analyst', name: 'Analyst', icon: 'fa-chart-line',
    desc: 'Research + code for data analysis.', tools: ['web_search', 'execute_code', 'read_file', 'list_files'] },
];

const ALL_TOOLS = ['web_search', 'read_file', 'list_files', 'write_file', 'edit_file',
  'run_bash', 'execute_code', 'code_map', 'generate_image'];

let modelsCache = null;

async function getModels() {
  if (modelsCache) return modelsCache;
  try {
    const data = await (await apiFetch('/models')).json();
    modelsCache = data.models || data || [];
  } catch {
    modelsCache = [];
  }
  return modelsCache;
}

export async function renderAgentHub(bodyEl) {
  bodyEl.innerHTML = `
    <div class="agent-hub">
      <div class="hub-header">
        <button class="btn-primary btn-sm" id="hubNew"><i class="fa-solid fa-plus"></i> New agent</button>
      </div>
      <div id="hubFormWrap"></div>
      <h4 class="hub-section-title">Built-in agents</h4>
      <div class="hub-grid" id="hubBuiltins"></div>
      <h4 class="hub-section-title">My agents</h4>
      <div class="hub-grid" id="hubMine"><p class="settings-hint">Loading…</p></div>
      <div id="hubRunWrap"></div>
    </div>`;

  // Built-ins
  const bi = bodyEl.querySelector('#hubBuiltins');
  bi.innerHTML = BUILTINS.map((b) => `
    <div class="hub-card">
      <div class="hub-card-head"><i class="fa-solid ${b.icon}"></i><strong>${escapeHtml(b.name)}</strong></div>
      <p>${escapeHtml(b.desc)}</p>
      <div class="hub-tools">${b.tools.map((t) => `<code>${escapeHtml(t)}</code>`).join(' ') || '<span class="settings-hint">no tools</span>'}</div>
      <button class="btn-secondary btn-sm" data-builtin="${b.id}"><i class="fa-solid fa-play"></i> Run</button>
    </div>`).join('');
  bi.querySelectorAll('[data-builtin]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const b = BUILTINS.find((x) => x.id === btn.dataset.builtin);
      openRunPanel(bodyEl, { name: b.name, builtin: b });
    });
  });

  bodyEl.querySelector('#hubNew')?.addEventListener('click', () => openForm(bodyEl, null));
  await loadMine(bodyEl);
}

async function loadMine(bodyEl) {
  const wrap = bodyEl.querySelector('#hubMine');
  try {
    const agents = await (await apiFetch('/agents')).json();
    if (!agents.length) {
      wrap.innerHTML = '<p class="settings-hint">No custom agents yet. Create one to get started.</p>';
      return;
    }
    wrap.innerHTML = agents.map((a) => `
      <div class="hub-card" data-id="${escapeHtml(a.id)}">
        <div class="hub-card-head"><i class="fa-solid fa-robot"></i><strong>${escapeHtml(a.name)}</strong></div>
        <p>${escapeHtml(a.description || 'No description.')}</p>
        <div class="hub-tools">${(a.tool_names || []).map((t) => `<code>${escapeHtml(t)}</code>`).join(' ') || '<span class="settings-hint">no tools</span>'}</div>
        <div class="hub-actions">
          <button class="btn-primary btn-sm" data-act="run"><i class="fa-solid fa-play"></i> Run</button>
          <button class="btn-secondary btn-sm" data-act="edit"><i class="fa-solid fa-pen"></i> Edit</button>
          <button class="btn-secondary btn-sm hub-danger" data-act="del"><i class="fa-solid fa-trash"></i></button>
        </div>
      </div>`).join('');
    wrap.querySelectorAll('.hub-card').forEach((card) => {
      const id = card.dataset.id;
      card.querySelector('[data-act="run"]')?.addEventListener('click', async () => {
        const agent = agents.find((x) => x.id === id);
        openRunPanel(bodyEl, { name: agent.name, agentId: id });
      });
      card.querySelector('[data-act="edit"]')?.addEventListener('click', async () => {
        const agent = await (await apiFetch(`/agents/${id}`)).json();
        openForm(bodyEl, agent);
      });
      card.querySelector('[data-act="del"]')?.addEventListener('click', async () => {
        if (!confirm(`Delete agent "${card.querySelector('strong').textContent}"?`)) return;
        try {
          await apiFetch(`/agents/${id}`, { method: 'DELETE' });
          showToast({ type: 'success', title: 'Agent deleted' });
          await loadMine(bodyEl);
        } catch (e) {
          showToast({ type: 'error', title: 'Delete failed', message: e?.message });
        }
      });
    });
  } catch (e) {
    wrap.innerHTML = `<p class="settings-hint">Could not load agents: ${escapeHtml(e?.message || e)}</p>`;
  }
}

async function openForm(bodyEl, agent) {
  const wrap = bodyEl.querySelector('#hubFormWrap');
  const models = await getModels();
  const isEdit = !!agent;
  wrap.innerHTML = `
    <form class="hub-form" id="hubForm">
      <h4>${isEdit ? 'Edit agent' : 'New agent'}</h4>
      <label>Name<input type="text" name="name" required maxlength="100" value="${escapeHtml(agent?.name || '')}" class="provider-key-input"></label>
      <label>Description<input type="text" name="description" maxlength="500" value="${escapeHtml(agent?.description || '')}" class="provider-key-input"></label>
      <label>System prompt<textarea name="system_prompt" rows="4" class="provider-key-input" placeholder="You are a helpful assistant…">${escapeHtml(agent?.system_prompt || '')}</textarea></label>
      <label>Model<select name="model_id" class="provider-key-input">
        <option value="">Default model</option>
        ${models.map((m) => `<option value="${escapeHtml(m.id)}"${agent?.model_id === m.id ? ' selected' : ''}>${escapeHtml(m.name || m.id)}</option>`).join('')}
      </select></label>
      <fieldset class="hub-tools-field"><legend>Tools</legend>
        ${ALL_TOOLS.map((t) => `
          <label class="popover-check"><input type="checkbox" name="tool" value="${t}"${(agent?.tool_names || []).includes(t) ? ' checked' : ''}> <span>${escapeHtml(t)}</span></label>`).join('')}
      </fieldset>
      <label>Max steps<input type="number" name="max_steps" min="1" max="25" value="${agent?.max_steps || 8}" class="provider-key-input"></label>
      <div class="hub-form-actions">
        <button type="submit" class="btn-primary btn-sm">${isEdit ? 'Save' : 'Create'}</button>
        <button type="button" class="btn-secondary btn-sm" id="hubFormCancel">Cancel</button>
      </div>
    </form>`;
  wrap.querySelector('#hubFormCancel')?.addEventListener('click', () => { wrap.innerHTML = ''; });
  wrap.querySelector('#hubForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const payload = {
      name: fd.get('name'),
      description: fd.get('description') || null,
      system_prompt: fd.get('system_prompt') || null,
      model_id: fd.get('model_id') || null,
      tool_names: fd.getAll('tool'),
      max_steps: parseInt(fd.get('max_steps'), 10) || 8,
    };
    try {
      if (isEdit) {
        await apiFetch(`/agents/${agent.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        showToast({ type: 'success', title: 'Agent updated' });
      } else {
        await apiFetch('/agents', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        showToast({ type: 'success', title: 'Agent created' });
      }
      wrap.innerHTML = '';
      await loadMine(bodyEl);
    } catch (err) {
      showToast({ type: 'error', title: 'Save failed', message: err?.message });
    }
  });
  wrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function openRunPanel(bodyEl, target) {
  const wrap = bodyEl.querySelector('#hubRunWrap');
  wrap.innerHTML = `
    <div class="hub-run">
      <h4><i class="fa-solid fa-play"></i> Run: ${escapeHtml(target.name)}</h4>
      <div class="hub-run-input">
        <input type="text" id="hubTask" class="provider-key-input" placeholder="Describe the task…" aria-label="Task">
        <button class="btn-primary btn-sm" id="hubRunBtn">Run</button>
        <button class="btn-secondary btn-sm hidden" id="hubStopBtn"><i class="fa-solid fa-stop"></i> Stop</button>
      </div>
      <div class="hub-log" id="hubLog"></div>
    </div>`;
  const logEl = wrap.querySelector('#hubLog');
  const taskEl = wrap.querySelector('#hubTask');
  const runBtn = wrap.querySelector('#hubRunBtn');
  const stopBtn = wrap.querySelector('#hubStopBtn');
  let abort = null;

  runBtn.addEventListener('click', async () => {
    const task = taskEl.value.trim();
    if (!task) { showToast({ type: 'info', message: 'Describe the task first.' }); return; }
    runBtn.classList.add('hidden');
    stopBtn.classList.remove('hidden');
    clearLog(logEl);
    abort = new AbortController();
    try {
      let url, body;
      if (target.agentId) {
        url = `/agents/${target.agentId}/run`;
        body = { task };
      } else {
        // Built-in: map to the generic agent endpoint with the builtin's tools
        url = '/agent/run';
        body = { message: task, tools: target.builtin.tools, max_steps: 8 };
      }
      const res = await apiFetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: abort.signal,
      });
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
          } catch { /* partial chunk */ }
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
  stopBtn.addEventListener('click', () => abort?.abort());
  taskEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); runBtn.click(); }
  });
  wrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  taskEl.focus();
}

// ---------------------------------------------------------------------------
// Merged Agents page (Phase 8 B7 + D2).
//
// Sub-views: Agents (hub) | Teams | Compare | Runs | Approvals.
// Teams and Compare were separate tabs; Runs (run history, D2) is new;
// Approvals shows the approval policy (approvals happen inline in runs).
// ---------------------------------------------------------------------------

const AGENT_SUBVIEWS = [
  { id: 'agents',    label: 'Agents',    icon: 'fa-robot' },
  { id: 'teams',     label: 'Teams',     icon: 'fa-users' },
  { id: 'compare',   label: 'Compare',   icon: 'fa-scale-balanced' },
  { id: 'runs',      label: 'Runs',      icon: 'fa-clock-rotate-left' },
  { id: 'automations', label: 'Automations', icon: 'fa-clock' },
  { id: 'approvals', label: 'Approvals', icon: 'fa-shield-halved' },
];

/** Merged Agents page — the rail 'Agents' entry renders this. */
export async function renderAgentsPage(bodyEl) {
  bodyEl.innerHTML = `
    <div class="agents-page">
      <div class="library-tabs" role="tablist" aria-label="Agents sections">
        ${AGENT_SUBVIEWS.map((t, i) => `
          <button class="library-tab${i === 0 ? ' active' : ''}" role="tab"
            data-agentsub="${t.id}" aria-selected="${i === 0}">
            <i class="fa-solid ${t.icon}"></i> ${t.label}
          </button>`).join('')}
      </div>
      <div class="agents-subbody" id="agentsSubBody"></div>
    </div>`;
  const subBody = bodyEl.querySelector('#agentsSubBody');
  const show = (id) => {
    bodyEl.querySelectorAll('[data-agentsub]').forEach((b) => {
      const on = b.dataset.agentsub === id;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', String(on));
    });
    renderAgentSubview(subBody, id);
  };
  bodyEl.querySelectorAll('[data-agentsub]').forEach((b) => {
    b.addEventListener('click', () => show(b.dataset.agentsub));
  });
  await renderAgentSubview(subBody, 'agents');
}

async function renderAgentSubview(container, id) {
  container.innerHTML = '<p class="settings-hint">Loading…</p>';
  try {
    if (id === 'agents') {
      await renderAgentHub(container);
    } else if (id === 'teams') {
      const { renderTeamsTab } = await import('../teams/teams.js');
      await renderTeamsTab(container);
    } else if (id === 'compare') {
      const { renderCompareTab } = await import('../compare/compare.js');
      await renderCompareTab(container);
    } else if (id === 'runs') {
      await renderRunsHistory(container);
    } else if (id === 'automations') {
      const { renderAutomations } = await import('../automations/ui.js');
      await renderAutomations(container);
    } else if (id === 'approvals') {
      renderApprovalsView(container);
    }
  } catch (err) {
    container.innerHTML = `<p class="team-error">Could not load: ${escapeHtml(err?.message || String(err))}</p>`;
  }
}

/** D2: run history from GET /runs. */
async function renderRunsHistory(container) {
  let runs = [];
  try {
    const data = await (await apiFetch('/runs?limit=50')).json();
    runs = data.runs || [];
  } catch (err) {
    container.innerHTML = `<p class="settings-hint">Could not load runs: ${escapeHtml(err?.message || String(err))}</p>`;
    return;
  }
  if (!runs.length) {
    container.innerHTML = '<p class="settings-hint">No agent runs yet. Runs from the Agents, Teams, and Code pages are recorded here.</p>';
    return;
  }
  const statusIcon = (s) => ({
    done: 'fa-circle-check', running: 'fa-circle-play', failed: 'fa-circle-exclamation',
  }[s] || 'fa-circle');
  container.innerHTML = `
    <div class="runs-list">
      ${runs.map((r) => `
        <div class="run-row">
          <i class="fa-solid ${statusIcon(r.status)}"></i>
          <div class="run-main">
            <strong>${escapeHtml(r.title || r.kind || 'Run')}</strong>
            <span class="settings-hint">${escapeHtml(r.kind || '')} · ${escapeHtml(r.model || '')} · ${r.tokens ? `${r.tokens} tok` : ''}${r.cost_usd ? ` · $${Number(r.cost_usd).toFixed(3)}` : ''}</span>
          </div>
          <span class="settings-hint">${r.created_at ? new Date(r.created_at).toLocaleString() : ''}</span>
          ${r.error ? `<span class="run-error" title="${escapeHtml(r.error)}"><i class="fa-solid fa-triangle-exclamation"></i></span>` : ''}
        </div>`).join('')}
    </div>`;
}

/** Approvals: policy overview (approvals happen inline during runs). */
function renderApprovalsView(container) {
  container.innerHTML = `
    <div class="sp-custom-section">
      <h3 class="sp-section-title"><i class="fa-solid fa-shield-halved"></i> Approval policy</h3>
      <p class="settings-hint">When an agent wants to use a gated tool, it pauses and asks
        you to approve inline in the run. Configure which tools need approval in
        Settings → Agents &amp; Safety.</p>
      <div class="sp-section-body" data-approval-policy><p class="settings-hint">Loading…</p></div>
    </div>`;
  const body = container.querySelector('[data-approval-policy]');
  import('../../shared/settings_store.js').then(({ getSetting }) => {
    const req = getSetting('requireApproval') || [];
    body.innerHTML = req.length
      ? `<ul class="lib-risks">${req.map((t) => `<li><i class="fa-solid fa-check"></i> ${escapeHtml(t)}</li>`).join('')}</ul>`
      : '<p class="settings-hint">No tools require approval right now.</p>';
  }).catch(() => {
    body.innerHTML = '<p class="settings-hint">Could not load policy.</p>';
  });
}
