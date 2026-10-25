/**
 * Task board — A4 agent runtime UI (destination-agnostic feature module).
 *
 * The coordinator's shell mounts this under Agents; this module itself
 * knows nothing about tabs or the sidebar. Exports renderTaskBoard(bodyEl).
 *
 * Sections: task list, task detail (steps completed/failed/skipped with
 * budget gauges), approval queue (approve/deny with reason), run history
 * (via the Runs store, kind=agent-task), audit trail, notifications.
 * Every action here calls a real API route; a button that cannot work
 * (e.g. run on a completed task) is refused by the server with 409 and
 * the error is shown, never silently swallowed.
 */
import { apiFetch } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] taskboard.js loaded');

let currentTaskId = null;

function pct(gauge, key) {
  const v = gauge ? gauge[key] : null;
  return v === null || v === undefined ? null : v;
}

function budgetHtml(task) {
  const g = task.budget || {};
  const tok = pct(g, 'token_pct');
  const cost = pct(g, 'cost_pct');
  const tokLine = tok === null
    ? `<span class="settings-hint">tokens ${escapeHtml(String(g.tokens_used ?? 0))} (no token budget)</span>`
    : `<label>Tokens <progress max="100" value="${tok}"></progress> ${tok}% (${escapeHtml(String(g.tokens_used))}/${escapeHtml(String(g.token_budget))})</label>`;
  const costLine = cost === null
    ? `<span class="settings-hint">cost $${escapeHtml(String(g.cost_used ?? 0))} (no cost budget)</span>`
    : `<label>Cost <progress max="100" value="${cost}"></progress> ${cost}% ($${escapeHtml(String(g.cost_used))}/$${escapeHtml(String(g.cost_budget_usd))})</label>`;
  const flags = [
    task.budget_exceeded ? '<strong class="tb-danger">budget exceeded</strong>' : '',
    task.circuit_tripped ? `<strong class="tb-danger">circuit tripped: ${escapeHtml(task.circuit_reason || '')}</strong>` : '',
    g.usage_known === false ? '<span class="settings-hint">usage unknown for some steps (never estimated)</span>' : '',
  ].filter(Boolean).join(' ');
  return `<div class="tb-budget">${tokLine}<br>${costLine} ${flags}</div>`;
}

function stepBadge(status) {
  return `<span class="tb-badge tb-${escapeHtml(status)}">${escapeHtml(status)}</span>`;
}

function stepsHtml(task) {
  const steps = task.steps || [];
  if (!steps.length) return '<p class="settings-hint">No steps.</p>';
  const counts = {};
  for (const s of steps) counts[s.status] = (counts[s.status] || 0) + 1;
  const summary = ['completed', 'failed', 'skipped', 'pending', 'waiting_approval']
    .filter((k) => counts[k]).map((k) => `${counts[k]} ${k}`).join(' · ');
  return `<p class="settings-hint">${escapeHtml(summary)}</p>
    <table class="tb-table"><thead><tr><th>Step</th><th>Kind</th><th>Status</th><th>Result / error</th></tr></thead>
    <tbody>${steps.map((s) => `<tr>
      <td><strong>${escapeHtml(s.name)}</strong>${s.tool ? ` <code>${escapeHtml(s.tool)}</code>` : ''}</td>
      <td>${escapeHtml(s.kind)}</td>
      <td>${stepBadge(s.status)}</td>
      <td>${s.error ? `<span class="tb-danger">${escapeHtml(s.error)}</span>`
        : escapeHtml(typeof s.result === 'string' ? s.result.slice(0, 200)
          : (s.result === null || s.result === undefined ? '' : JSON.stringify(s.result).slice(0, 200)))}</td>
    </tr>`).join('')}</tbody></table>`;
}

async function api(path, options) {
  const res = await apiFetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

export async function renderTaskBoard(bodyEl) {
  bodyEl.innerHTML = `
    <div class="task-board">
      <div class="tb-actions">
        <button class="btn-primary btn-sm" id="tbNew">New task</button>
        <button class="btn-secondary btn-sm" id="tbTick">Run due tasks now</button>
        <button class="btn-secondary btn-sm" id="tbRefresh">Refresh</button>
      </div>
      <div id="tbFormWrap"></div>
      <h4 class="hub-section-title">Tasks</h4>
      <div id="tbList"><p class="settings-hint">Loading…</p></div>
      <h4 class="hub-section-title">Task detail</h4>
      <div id="tbDetail"><p class="settings-hint">Select a task to see its steps, budget, audit trail, and run history.</p></div>
      <h4 class="hub-section-title">Approval queue</h4>
      <div id="tbApprovals"><p class="settings-hint">Loading…</p></div>
      <h4 class="hub-section-title">Notifications</h4>
      <div id="tbNotifications"><p class="settings-hint">Loading…</p></div>
    </div>`;

  bodyEl.querySelector('#tbNew')?.addEventListener('click', () => openForm(bodyEl));
  bodyEl.querySelector('#tbRefresh')?.addEventListener('click', () => refreshAll(bodyEl));
  bodyEl.querySelector('#tbTick')?.addEventListener('click', async () => {
    try {
      const out = await api('/agent-tasks/scheduler/tick', { method: 'POST' });
      showToast({ type: 'success', title: 'Scheduler tick done',
        message: `${out.agent_tasks.length} task(s), ${out.workflows.length} workflow(s) due.` });
      await refreshAll(bodyEl);
    } catch (e) { showToast({ type: 'error', title: 'Tick failed', message: e?.message }); }
  });
  await refreshAll(bodyEl);
}

async function refreshAll(bodyEl) {
  await Promise.all([loadTasks(bodyEl), loadApprovals(bodyEl), loadNotifications(bodyEl)]);
  if (currentTaskId) await loadDetail(bodyEl, currentTaskId);
}

async function loadTasks(bodyEl) {
  const wrap = bodyEl.querySelector('#tbList');
  try {
    const data = await api('/agent-tasks');
    const tasks = data.tasks || [];
    if (!tasks.length) {
      wrap.innerHTML = '<p class="settings-hint">No tasks yet. Create one to get started.</p>';
      return;
    }
    wrap.innerHTML = tasks.map((t) => `
      <div class="hub-card" data-id="${escapeHtml(t.id)}">
        <div class="hub-card-head"><i class="fa-solid fa-list-check"></i><strong>${escapeHtml(t.title)}</strong></div>
        <p>${stepBadge(t.status)} · policy ${escapeHtml(t.approval_policy)} · trigger ${escapeHtml(t.trigger)}</p>
        ${budgetHtml(t)}
        <div class="hub-actions">
          <button class="btn-primary btn-sm" data-act="open">Open</button>
          <button class="btn-secondary btn-sm" data-act="run">Run / resume</button>
          <button class="btn-secondary btn-sm" data-act="pause">Pause</button>
          <button class="btn-secondary btn-sm hub-danger" data-act="cancel">Cancel</button>
        </div>
      </div>`).join('');
    wrap.querySelectorAll('.hub-card').forEach((card) => {
      const id = card.dataset.id;
      card.querySelector('[data-act="open"]')?.addEventListener('click', async () => {
        currentTaskId = id; await loadDetail(bodyEl, id);
      });
      card.querySelector('[data-act="run"]')?.addEventListener('click', async () => {
        try {
          const out = await api(`/agent-tasks/${id}/run`, { method: 'POST', body: JSON.stringify({}) });
          showToast({ type: 'success', title: `Task ${out.status}`,
            message: `${out.summary.completed} completed, ${out.summary.skipped} skipped, ${out.summary.failed} failed.` });
          currentTaskId = id; await refreshAll(bodyEl);
        } catch (e) { showToast({ type: 'error', title: 'Run failed', message: e?.message }); }
      });
      card.querySelector('[data-act="pause"]')?.addEventListener('click', async () => {
        try { await api(`/agent-tasks/${id}/pause`, { method: 'POST' }); await refreshAll(bodyEl); }
        catch (e) { showToast({ type: 'error', title: 'Pause failed', message: e?.message }); }
      });
      card.querySelector('[data-act="cancel"]')?.addEventListener('click', async () => {
        if (!confirm('Cancel this task?')) return;
        try { await api(`/agent-tasks/${id}/cancel`, { method: 'POST' }); await refreshAll(bodyEl); }
        catch (e) { showToast({ type: 'error', title: 'Cancel failed', message: e?.message }); }
      });
    });
  } catch (e) {
    wrap.innerHTML = `<p class="settings-hint">Could not load tasks: ${escapeHtml(e?.message || e)}</p>`;
  }
}

async function loadDetail(bodyEl, taskId) {
  const wrap = bodyEl.querySelector('#tbDetail');
  try {
    const task = await api(`/agent-tasks/${taskId}`);
    const audit = await api(`/agent-tasks/${taskId}/audit`);
    const runs = await api('/runs?kind=agent-task&limit=50').catch(() => ({ runs: [] }));
    const mine = (runs.runs || []).filter((r) => (r.title || '').includes(taskId));
    wrap.innerHTML = `
      <div class="hub-card">
        <div class="hub-card-head"><strong>${escapeHtml(task.title)}</strong> ${stepBadge(task.status)}</div>
        ${budgetHtml(task)}
        ${stepsHtml(task)}
        <h5>Audit trail</h5>
        ${(audit.audit || []).length ? `<ul class="tb-audit">${(audit.audit || []).map((a) =>
          `<li><code>${escapeHtml(a.action)}</code> ${escapeHtml(a.detail)}</li>`).join('')}</ul>`
          : '<p class="settings-hint">No audit events yet.</p>'}
        <h5>Run history (Runs store)</h5>
        ${mine.length ? `<ul>${mine.map((r) => `<li>${escapeHtml(r.status)} · ${r.tokens} tokens · $${r.cost_usd}</li>`).join('')}</ul>`
          : '<p class="settings-hint">No completed runs mirrored yet — history appears when a task finishes or fails.</p>'}
        <div class="hub-actions">
          <button class="btn-primary btn-sm" id="tbDetailRun">Run / resume</button>
          <button class="btn-secondary btn-sm" id="tbDetailAudit">Refresh audit</button>
        </div>
      </div>`;
    wrap.querySelector('#tbDetailRun')?.addEventListener('click', async () => {
      try {
        const out = await api(`/agent-tasks/${taskId}/run`, { method: 'POST', body: JSON.stringify({}) });
        showToast({ type: 'success', title: `Task ${out.status}` });
        await refreshAll(bodyEl);
      } catch (e) { showToast({ type: 'error', title: 'Run failed', message: e?.message }); }
    });
    wrap.querySelector('#tbDetailAudit')?.addEventListener('click', () => loadDetail(bodyEl, taskId));
  } catch (e) {
    wrap.innerHTML = `<p class="settings-hint">Could not load task: ${escapeHtml(e?.message || e)}</p>`;
  }
}

async function loadApprovals(bodyEl) {
  const wrap = bodyEl.querySelector('#tbApprovals');
  try {
    const data = await api('/agent-approvals');
    const rows = data.approvals || [];
    if (!rows.length) {
      wrap.innerHTML = '<p class="settings-hint">No pending approvals.</p>';
      return;
    }
    wrap.innerHTML = rows.map((a) => `
      <div class="hub-card" data-id="${escapeHtml(a.id)}" data-task="${escapeHtml(a.task_id)}">
        <div class="hub-card-head"><strong>${escapeHtml(a.tool)}</strong> <span class="settings-hint">task ${escapeHtml(a.task_id)}</span></div>
        <p><code>${escapeHtml(JSON.stringify(a.args || {}).slice(0, 300))}</code></p>
        <div class="hub-actions">
          <button class="btn-primary btn-sm" data-act="approve">Approve</button>
          <button class="btn-secondary btn-sm hub-danger" data-act="deny">Deny</button>
        </div>
      </div>`).join('');
    wrap.querySelectorAll('.hub-card').forEach((card) => {
      const id = card.dataset.id; const taskId = card.dataset.task;
      card.querySelector('[data-act="approve"]')?.addEventListener('click', async () => {
        try {
          await api(`/agent-tasks/${taskId}/approvals/${id}/decide`,
            { method: 'POST', body: JSON.stringify({ approved: true, reason: '' }) });
          showToast({ type: 'success', title: 'Approved' });
          currentTaskId = taskId; await refreshAll(bodyEl);
        } catch (e) { showToast({ type: 'error', title: 'Decision failed', message: e?.message }); }
      });
      card.querySelector('[data-act="deny"]')?.addEventListener('click', async () => {
        const reason = prompt('Reason for denying (shown in the audit trail):', '') || '';
        try {
          await api(`/agent-tasks/${taskId}/approvals/${id}/decide`,
            { method: 'POST', body: JSON.stringify({ approved: false, reason }) });
          showToast({ type: 'success', title: 'Denied' });
          currentTaskId = taskId; await refreshAll(bodyEl);
        } catch (e) { showToast({ type: 'error', title: 'Decision failed', message: e?.message }); }
      });
    });
  } catch (e) {
    wrap.innerHTML = `<p class="settings-hint">Could not load approvals: ${escapeHtml(e?.message || e)}</p>`;
  }
}

async function loadNotifications(bodyEl) {
  const wrap = bodyEl.querySelector('#tbNotifications');
  try {
    const data = await api('/agent-notifications?unread_only=false');
    const rows = data.notifications || [];
    if (!rows.length) {
      wrap.innerHTML = '<p class="settings-hint">No notifications yet.</p>';
      return;
    }
    wrap.innerHTML = `<ul class="tb-audit">${rows.slice(0, 20).map((n) =>
      `<li><code>${escapeHtml(n.kind)}</code> ${escapeHtml(n.message)}
       ${n.read ? '' : `<button class="btn-secondary btn-sm" data-read="${escapeHtml(n.id)}">Mark read</button>`}</li>`).join('')}</ul>`;
    wrap.querySelectorAll('[data-read]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try { await api(`/agent-notifications/${btn.dataset.read}/read`, { method: 'POST' }); await loadNotifications(bodyEl); }
        catch (e) { showToast({ type: 'error', title: 'Mark-read failed', message: e?.message }); }
      });
    });
  } catch (e) {
    wrap.innerHTML = `<p class="settings-hint">Could not load notifications: ${escapeHtml(e?.message || e)}</p>`;
  }
}

function openForm(bodyEl) {
  const wrap = bodyEl.querySelector('#tbFormWrap');
  wrap.innerHTML = `
    <form class="tb-form" id="tbForm">
      <label>Title <input name="title" required maxlength="200" placeholder="e.g. Nightly inbox triage"></label>
      <label>Approval policy
        <select name="policy">
          <option value="default">default — sensitive tools ask</option>
          <option value="once">once — approve a tool once per task</option>
          <option value="always">always — every sensitive call asks</option>
          <option value="deny">deny — sensitive actions refused</option>
        </select></label>
      <label>Token budget (0 = unlimited) <input name="token_budget" type="number" min="0" value="0"></label>
      <label>Cost budget USD (0 = unlimited) <input name="cost_budget" type="number" min="0" step="0.01" value="0"></label>
      <label>Trigger
        <select name="trigger">
          <option value="manual">manual</option><option value="hourly">hourly</option>
          <option value="daily">daily</option><option value="weekly">weekly</option>
          <option value="event">event</option><option value="webhook">webhook</option>
        </select></label>
      <label>Steps (JSON array — each step: {"name", "kind", "tool"?, "args"?, "depends_on"?})
        <textarea name="steps" rows="5" required placeholder='[{"name": "say", "kind": "echo", "args": {"text": "hello"}}]'></textarea></label>
      <button class="btn-primary btn-sm" type="submit">Create task</button>
    </form>`;
  wrap.querySelector('#tbForm')?.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const fd = new FormData(ev.target);
    let steps;
    try { steps = JSON.parse(fd.get('steps')); }
    catch { showToast({ type: 'error', title: 'Steps must be valid JSON' }); return; }
    try {
      const task = await api('/agent-tasks', { method: 'POST', body: JSON.stringify({
        title: fd.get('title'), approval_policy: fd.get('policy'),
        token_budget: Number(fd.get('token_budget') || 0),
        cost_budget_usd: Number(fd.get('cost_budget') || 0),
        trigger: fd.get('trigger'), steps }) });
      showToast({ type: 'success', title: 'Task created' });
      wrap.innerHTML = '';
      currentTaskId = task.id; await refreshAll(bodyEl);
    } catch (e) { showToast({ type: 'error', title: 'Create failed', message: e?.message }); }
  });
}
