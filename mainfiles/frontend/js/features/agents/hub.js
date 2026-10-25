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
      <div class="sp-custom-section" id="hubRuntime">
        <h3 class="sp-section-title"><i class="fa-solid fa-diagram-project"></i> Run mode &amp; task plan</h3>
        <p class="settings-hint">Pick how a run is shaped before you start it: a single agent,
          one fresh agent per task (tasks run in order, each reviewed before the next),
          a hive run that drains its inbox first, or a ticket flow with blocking edges.
          Previewing a plan below runs no agent and changes nothing — it only shows the order.</p>
        <label class="settings-hint">Run mode
          <select id="hubRunMode" class="provider-key-input">
            <option value="single">Single agent</option>
            <option value="subagent-per-task">Subagent per task (fresh context per task, review per task)</option>
            <option value="hive">Hive (drain inbox first, escalate only critical items)</option>
            <option value="flow">Ticket flow (blocking edges, ready-frontier order)</option>
          </select>
        </label>
        <label class="settings-hint">Tasks (one per line, use "A &gt; B" to mean B waits for A)
          <textarea id="hubFlowTasks" class="provider-key-input" rows="3" placeholder="Research&#10;Draft > Research&#10;Review > Draft"></textarea>
        </label>
        <button class="btn-secondary btn-sm" id="hubFlowPreview"><i class="fa-solid fa-list-check"></i> Preview plan</button>
        <div id="hubFlowResult"><p class="settings-hint">No plan previewed yet. Enter tasks and preview to see the run order.</p></div>
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
  bodyEl.querySelector('#hubFlowPreview')?.addEventListener('click', async () => {
    const result = bodyEl.querySelector('#hubFlowResult');
    const mode = bodyEl.querySelector('#hubRunMode')?.value || 'single';
    const lines = (bodyEl.querySelector('#hubFlowTasks')?.value || '')
      .split('\n').map((l) => l.trim()).filter(Boolean);
    if (!lines.length) {
      result.innerHTML = '<p class="settings-hint">Enter at least one task to preview a plan.</p>';
      return;
    }
    // "B > A" means B waits for A; plain lines have no dependencies.
    const tasks = [];
    const byTitle = new Map();
    lines.forEach((line, i) => {
      const parts = line.split('>').map((s) => s.trim()).filter(Boolean);
      const title = parts[0];
      const id = `t${i + 1}`;
      byTitle.set(title, id);
      tasks.push({ id, title, depends_on: [] });
    });
    lines.forEach((line, i) => {
      const parts = line.split('>').map((s) => s.trim()).filter(Boolean);
      parts.slice(1).forEach((dep) => {
        if (byTitle.has(dep)) tasks[i].depends_on.push(byTitle.get(dep));
      });
    });
    try {
      const data = await (await apiFetch('/agent/runtime/flow', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tasks }),
      })).json();
      const order = (data.execution_order || []).map((id) => {
        const t = tasks.find((x) => x.id === id);
        return t ? t.title : id;
      });
      result.innerHTML = `<p class="settings-hint">Mode: <strong>${escapeHtml(mode)}</strong> — run order:</p>
        <ol>${order.map((t) => `<li>${escapeHtml(t)}</li>`).join('')}</ol>
        <p class="settings-hint">Ready first: ${(data.frontier || []).map((id) => {
          const t = tasks.find((x) => x.id === id);
          return escapeHtml(t ? t.title : id);
        }).join(', ') || 'none'}</p>`;
    } catch (err) {
      result.innerHTML = `<p class="team-error">Could not preview plan: ${escapeHtml(err?.message || String(err))}</p>`;
    }
  });
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
        <div class="settings-hint">${escapeHtml(a.approval_policy || 'default')}${a.cost_budget ? ` · ${Number(a.cost_budget).toFixed(2)} USD budget` : ''}</div>
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
  const isEdit = !!agent;
  wrap.innerHTML = `
    <form class="hub-form" id="hubForm">
      <h4>${isEdit ? 'Edit agent' : 'New agent'}</h4>
      <label>Name<input type="text" name="name" required maxlength="100" value="${escapeHtml(agent?.name || '')}" class="provider-key-input"></label>
      <label>Description<input type="text" name="description" maxlength="500" value="${escapeHtml(agent?.description || '')}" class="provider-key-input"></label>
      <label>System prompt<textarea name="system_prompt" rows="4" class="provider-key-input" placeholder="You are a helpful assistant…">${escapeHtml(agent?.system_prompt || '')}</textarea></label>
      <label>Model<select name="model_id" class="provider-key-input">
        <option value="">Default model</option>
      </select></label>
      <fieldset class="hub-tools-field"><legend>Tools</legend>
        ${ALL_TOOLS.map((t) => `
          <label class="popover-check"><input type="checkbox" name="tool" value="${t}"${(agent?.tool_names || []).includes(t) ? ' checked' : ''}> <span>${escapeHtml(t)}</span></label>`).join('')}
      </fieldset>
      <label>Max steps<input type="number" name="max_steps" min="1" max="25" value="${agent?.max_steps || 8}" class="provider-key-input"></label>
      <label>Approval policy<select name="approval_policy" class="provider-key-input">
        <option value="default"${agent?.approval_policy === 'default' || !agent ? ' selected' : ''}>Default (ask before file writes / commands)</option>
        <option value="automatic"${agent?.approval_policy === 'automatic' ? ' selected' : ''}>Automatic (never ask)</option>
        <option value="always_ask"${agent?.approval_policy === 'always_ask' ? ' selected' : ''}>Always ask (approve every tool)</option>
      </select></label>
      <label>Cost budget (USD, 0 = no limit)<input type="number" name="cost_budget" min="0" max="100" step="0.01" value="${agent?.cost_budget || 0}" class="provider-key-input"></label>
      <div class="hub-form-actions">
        <button type="submit" class="btn-primary btn-sm">${isEdit ? 'Save' : 'Create'}</button>
        <button type="button" class="btn-secondary btn-sm" id="hubFormCancel">Cancel</button>
      </div>
    </form>`;
  // Fill the model list after the form is visible — discovery can be slow or
  // blocked, and the form must never wait on it to appear.
  const modelSelect = wrap.querySelector('select[name="model_id"]');
  getModels().then((models) => {
    if (!modelSelect?.isConnected || !models.length) return;
    const current = modelSelect.value || agent?.model_id || '';
    modelSelect.innerHTML = '<option value="">Default model</option>' + models.map((m) =>
      `<option value="${escapeHtml(m.id)}"${current === m.id ? ' selected' : ''}>${escapeHtml(m.name || m.id)}</option>`).join('');
  }).catch(() => { /* keep Default model only */ });

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
      approval_policy: fd.get('approval_policy') || 'default',
      cost_budget: parseFloat(fd.get('cost_budget')) || 0,
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

/** Approvals: policy overview + the async "Needs you" tray (Batch 10).

The tray is the coucou pattern on Sangam's approval backend: a risky
call waits here while its run continues with independent work, and it
can be approved from here or from a paired device — it no longer has
to block inside the chat stream. */
function renderApprovalsView(container) {
  container.innerHTML = `
    <div class="sp-custom-section">
      <h3 class="sp-section-title"><i class="fa-solid fa-shield-halved"></i> Approval policy</h3>
      <p class="settings-hint">When an agent wants to use a gated tool, it pauses and asks
        you to approve inline in the run. Configure which tools need approval in
        Settings → Agents &amp; Safety.</p>
      <div class="sp-section-body" data-approval-policy><p class="settings-hint">Loading…</p></div>
    </div>
    <div class="sp-custom-section">
      <h3 class="sp-section-title"><i class="fa-solid fa-bell"></i> Needs you</h3>
      <p class="settings-hint">Risky calls waiting for a decision. The run keeps working on
        independent tasks while these wait — approving here (or from a paired device)
        releases exactly one waiting call.</p>
      <div data-approval-tray><p class="settings-hint">Loading tray…</p></div>
      <button class="btn-secondary btn-sm" data-tray-refresh><i class="fa-solid fa-rotate"></i> Refresh tray</button>
    </div>`;
  const trayEl = container.querySelector('[data-approval-tray]');
  async function loadTray() {
    try {
      const data = await (await apiFetch('/agent/runtime/approvals/tray')).json();
      const items = (data.tray || []).filter((t) => t.status === 'pending');
      if (!items.length) {
        trayEl.innerHTML = '<p class="settings-hint">Nothing needs you right now. When an agent parks a risky call here, it appears with Approve / Deny buttons.</p>';
        return;
      }
      trayEl.innerHTML = items.map((t) => `
        <div class="run-row" data-tray-id="${escapeHtml(t.id)}">
          <div class="run-main"><strong>${escapeHtml(t.tool)}</strong>
            <span class="settings-hint">${escapeHtml(t.args_preview || '')}</span></div>
          <button class="btn-primary btn-sm" data-tray-decide="approve">Approve</button>
          <button class="btn-secondary btn-sm" data-tray-decide="deny">Deny</button>
        </div>`).join('');
      trayEl.querySelectorAll('[data-tray-id]').forEach((row) => {
        row.querySelectorAll('[data-tray-decide]').forEach((btn) => {
          btn.addEventListener('click', async () => {
            const approved = btn.dataset.trayDecide === 'approve';
            await apiFetch(`/agent/runtime/approvals/${encodeURIComponent(row.dataset.trayId)}/decide`, {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ approved, source: 'chat' }),
            });
            showToast({ type: 'success', title: approved ? 'Approved.' : 'Denied.' });
            await loadTray();
          });
        });
      });
    } catch (err) {
      trayEl.innerHTML = `<p class="team-error">Could not load tray: ${escapeHtml(err?.message || String(err))}</p>`;
    }
  }
  container.querySelector('[data-tray-refresh]')?.addEventListener('click', loadTray);
  loadTray();
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
