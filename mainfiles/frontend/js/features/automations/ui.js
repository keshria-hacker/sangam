/**
 * Automations — scheduled tasks + triggers (Sangam-native, Phase 5).
 *
 * Exports renderAutomations(bodyEl). Parent wires it as a tab renderer.
 *
 * Backend: POST /api/automations, GET /api/automations,
 *          PUT /api/automations/{id}, DELETE /api/automations/{id},
 *          POST /api/automations/{id}/run
 * Triggers: 'hourly' | 'daily' | 'weekly' | cron expression (5 fields).
 * Actions: 'agent' (config: {task, model}) | 'chat' (config: {message}).
 */
import { apiFetch } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] automations/ui.js loaded');

// The list endpoint does not return config, and there is no single-GET
// endpoint, so we keep a client-side cache of configs (populated on create)
// to prefill the edit form. localStorage so it survives reloads.
const CONFIG_CACHE_KEY = 'sangam:automation-configs';

function readConfigCache() {
  try {
    return JSON.parse(localStorage.getItem(CONFIG_CACHE_KEY) || '{}');
  } catch {
    return {};
  }
}

function writeConfigCache(id, config) {
  try {
    const cache = readConfigCache();
    cache[id] = config;
    localStorage.setItem(CONFIG_CACHE_KEY, JSON.stringify(cache));
  } catch { /* noop */ }
}

function dropConfigCache(id) {
  try {
    const cache = readConfigCache();
    delete cache[id];
    localStorage.setItem(CONFIG_CACHE_KEY, JSON.stringify(cache));
  } catch { /* noop */ }
}

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

function triggerLabel(trigger) {
  if (trigger === 'hourly') return 'Every hour';
  if (trigger === 'daily') return 'Every day';
  if (trigger === 'weekly') return 'Every week';
  return trigger; // cron expression
}

/** Humanize a next-run ISO timestamp relative to now. */
function humanizeNext(iso, enabled) {
  if (!enabled) return 'Paused';
  if (!iso) return 'Not scheduled';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return 'Not scheduled';
  const diff = t - Date.now();
  if (diff <= 0) return 'Due now';
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'In less than a minute';
  if (mins < 60) return `in ${mins} minute${mins === 1 ? '' : 's'}`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `in ${hours} hour${hours === 1 ? '' : 's'}`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'tomorrow';
  if (days < 7) return `in ${days} days`;
  const weeks = Math.floor(days / 7);
  if (weeks < 5) return `in ${weeks} week${weeks === 1 ? '' : 's'}`;
  const months = Math.floor(days / 30);
  return `in ${months} month${months === 1 ? '' : 's'}`;
}

/** Humanize a last-run ISO timestamp. */
function humanizeLast(iso) {
  if (!iso) return 'Never ran';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '—';
  const diff = Date.now() - t;
  if (diff < 0) return 'just now';
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} minute${mins === 1 ? '' : 's'} ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return 'yesterday';
  if (days < 30) return `${days} days ago`;
  const months = Math.floor(days / 30);
  return `${months} month${months === 1 ? '' : 's'} ago`;
}

export async function renderAutomations(bodyEl) {
  bodyEl.innerHTML = `
    <div class="agent-hub automations">
      <div class="hub-header">
        <h3><i class="fa-solid fa-clock"></i> Automations</h3>
        <button class="btn-primary btn-sm" id="autoNew"><i class="fa-solid fa-plus"></i> New automation</button>
      </div>
      <div id="autoFormWrap"></div>
      <div class="hub-grid" id="autoList"><p class="settings-hint">Loading…</p></div>
    </div>`;

  bodyEl.querySelector('#autoNew')?.addEventListener('click', () => openForm(bodyEl, null));
  await loadAutomations(bodyEl);
}

async function loadAutomations(bodyEl) {
  const wrap = bodyEl.querySelector('#autoList');
  try {
    const data = await (await apiFetch('/automations')).json();
    const autos = data.automations || [];
    if (!autos.length) {
      wrap.innerHTML = '<p class="settings-hint">No automations yet. Create one to run tasks on a schedule.</p>';
      return;
    }
    wrap.innerHTML = autos.map((a) => {
      const isCron = !['hourly', 'daily', 'weekly'].includes(a.trigger);
      return `
      <div class="hub-card${a.enabled ? '' : ' auto-disabled'}" data-id="${escapeHtml(a.id)}">
        <div class="hub-card-head">
          <i class="fa-solid ${a.action === 'agent' ? 'fa-robot' : 'fa-comment'}"></i>
          <strong>${escapeHtml(a.name)}</strong>
          <label class="switch auto-toggle" title="${a.enabled ? 'Disable' : 'Enable'}">
            <input type="checkbox" data-act="toggle"${a.enabled ? ' checked' : ''} aria-label="Enable automation">
            <span class="switch-track"><span class="switch-thumb"></span></span>
          </label>
        </div>
        <div class="hub-tools">
          <span class="auto-badge" title="${escapeHtml(triggerLabel(a.trigger))}"><i class="fa-solid fa-clock"></i> ${escapeHtml(isCron ? a.trigger : triggerLabel(a.trigger))}</span>
          <span class="auto-badge"><i class="fa-solid ${a.action === 'agent' ? 'fa-robot' : 'fa-comment'}"></i> ${escapeHtml(a.action)}</span>
        </div>
        <div class="auto-runs">
          <span title="Last run"><i class="fa-solid fa-history"></i> ${escapeHtml(humanizeLast(a.last_run))}</span>
          <span title="Next run"><i class="fa-solid fa-calendar-clock"></i> ${escapeHtml(humanizeNext(a.next_run, a.enabled))}</span>
        </div>
        <div class="hub-actions">
          <button class="btn-primary btn-sm" data-act="run"><i class="fa-solid fa-play"></i> Run now</button>
          <button class="btn-secondary btn-sm" data-act="edit"><i class="fa-solid fa-pen"></i> Edit</button>
          <button class="btn-secondary btn-sm hub-danger" data-act="del" aria-label="Delete"><i class="fa-solid fa-trash"></i></button>
        </div>
      </div>`;
    }).join('');

    wrap.querySelectorAll('.hub-card').forEach((card) => {
      const id = card.dataset.id;
      const auto = autos.find((x) => x.id === id);
      card.querySelector('[data-act="run"]')?.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        btn.disabled = true;
        try {
          await apiFetch(`/automations/${id}/run`, { method: 'POST' });
          showToast({ type: 'success', title: 'Automation started' });
          await loadAutomations(bodyEl); // refresh last/next run
        } catch (err) {
          showToast({ type: 'error', title: 'Run failed', message: err?.message });
        } finally {
          btn.disabled = false;
        }
      });
      card.querySelector('[data-act="toggle"]')?.addEventListener('change', async (e) => {
        const cache = readConfigCache();
        if (!(id in cache)) {
          // No cached config and no backend endpoint to fetch it — a blind
          // PUT would wipe the task/message. Open edit instead so the user
          // can see and re-enter it.
          e.target.checked = !e.target.checked; // revert the switch visually
          showToast({ type: 'info', title: 'Task not cached', message: 'Re-enter the task/message below, then save.' });
          openForm(bodyEl, { ...auto, config: {} });
          return;
        }
        try {
          const config = cache[id];
          await apiFetch(`/automations/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              name: auto.name,
              trigger: auto.trigger,
              action: auto.action,
              config,
              enabled: e.target.checked,
            }),
          });
          showToast({ type: 'success', title: e.target.checked ? 'Automation enabled' : 'Automation paused' });
          await loadAutomations(bodyEl);
        } catch (err) {
          showToast({ type: 'error', title: 'Toggle failed', message: err?.message });
          await loadAutomations(bodyEl); // revert on failure
        }
      });
      card.querySelector('[data-act="edit"]')?.addEventListener('click', () => {
        const cache = readConfigCache();
        openForm(bodyEl, { ...auto, config: cache[id] || {} });
      });
      card.querySelector('[data-act="del"]')?.addEventListener('click', async () => {
        if (!confirm(`Delete automation "${card.querySelector('strong').textContent}"?`)) return;
        try {
          await apiFetch(`/automations/${id}`, { method: 'DELETE' });
          dropConfigCache(id);
          showToast({ type: 'success', title: 'Automation deleted' });
          await loadAutomations(bodyEl);
        } catch (err) {
          showToast({ type: 'error', title: 'Delete failed', message: err?.message });
        }
      });
    });
  } catch (e) {
    wrap.innerHTML = `<p class="settings-hint">Could not load automations: ${escapeHtml(e?.message || e)}</p>`;
  }
}

async function openForm(bodyEl, auto) {
  const wrap = bodyEl.querySelector('#autoFormWrap');
  const models = await getModels();
  const isEdit = !!auto;
  const cfg = auto?.config || {};
  const trigger = auto?.trigger || 'daily';
  const isCron = !['hourly', 'daily', 'weekly'].includes(trigger);
  const action = auto?.action || 'agent';

  wrap.innerHTML = `
    <form class="hub-form" id="autoForm">
      <h4>${isEdit ? 'Edit automation' : 'New automation'}</h4>
      <label>Name<input type="text" name="name" required maxlength="200" value="${escapeHtml(auto?.name || '')}" class="provider-key-input" placeholder="e.g. Morning brief"></label>
      <label>Trigger
        <select name="trigger" id="autoTrigger" class="provider-key-input">
          <option value="hourly"${trigger === 'hourly' ? ' selected' : ''}>Hourly</option>
          <option value="daily"${trigger === 'daily' ? ' selected' : ''}>Daily</option>
          <option value="weekly"${trigger === 'weekly' ? ' selected' : ''}>Weekly</option>
          <option value="custom"${isCron ? ' selected' : ''}>Custom (cron)</option>
        </select>
      </label>
      <label id="autoCronWrap" class="${isCron ? '' : 'hidden'}">Cron expression
        <input type="text" name="cron" value="${escapeHtml(isCron ? trigger : '')}" class="provider-key-input" placeholder="0 9 * * *" aria-label="Cron expression">
        <small class="settings-hint">5 fields: minute hour day-of-month month day-of-week, e.g. <code>0 9 * * *</code> = every day at 09:00</small>
      </label>
      <label>Action
        <select name="action" id="autoAction" class="provider-key-input">
          <option value="agent"${action === 'agent' ? ' selected' : ''}>Agent (run a task)</option>
          <option value="chat"${action === 'chat' ? ' selected' : ''}>Chat (send a message)</option>
        </select>
      </label>
      <div id="autoAgentFields" class="${action === 'agent' ? '' : 'hidden'}">
        <label>Task<textarea name="task" rows="4" class="provider-key-input" placeholder="What should the agent do?">${escapeHtml(cfg.task || '')}</textarea></label>
        <label>Model<select name="model" class="provider-key-input">
          <option value="">Default model</option>
          ${models.map((m) => `<option value="${escapeHtml(m.id)}"${cfg.model === m.id ? ' selected' : ''}>${escapeHtml(m.name || m.id)}</option>`).join('')}
        </select></label>
      </div>
      <div id="autoChatFields" class="${action === 'chat' ? '' : 'hidden'}">
        <label>Message<textarea name="message" rows="4" class="provider-key-input" placeholder="The message to send…">${escapeHtml(cfg.message || '')}</textarea></label>
      </div>
      <label class="popover-check"><input type="checkbox" name="enabled"${auto?.enabled ?? true ? ' checked' : ''}> <span><strong>Enabled</strong><small>Run on schedule</small></span></label>
      ${isEdit && !Object.keys(cfg).length ? '<p class="settings-hint"><i class="fa-solid fa-circle-info"></i> Task/message was not cached for this automation — re-enter it above or it will be saved empty.</p>' : ''}
      <div class="hub-form-actions">
        <button type="submit" class="btn-primary btn-sm">${isEdit ? 'Save' : 'Create'}</button>
        <button type="button" class="btn-secondary btn-sm" id="autoFormCancel">Cancel</button>
      </div>
    </form>`;

  const form = wrap.querySelector('#autoForm');
  const triggerSel = wrap.querySelector('#autoTrigger');
  const cronWrap = wrap.querySelector('#autoCronWrap');
  const actionSel = wrap.querySelector('#autoAction');
  const agentFields = wrap.querySelector('#autoAgentFields');
  const chatFields = wrap.querySelector('#autoChatFields');

  triggerSel?.addEventListener('change', () => {
    cronWrap.classList.toggle('hidden', triggerSel.value !== 'custom');
  });
  actionSel?.addEventListener('change', () => {
    agentFields.classList.toggle('hidden', actionSel.value !== 'agent');
    chatFields.classList.toggle('hidden', actionSel.value !== 'chat');
  });
  wrap.querySelector('#autoFormCancel')?.addEventListener('click', () => { wrap.innerHTML = ''; });

  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const triggerChoice = fd.get('trigger');
    let triggerVal = triggerChoice;
    if (triggerChoice === 'custom') {
      triggerVal = (fd.get('cron') || '').trim();
      if (!triggerVal) {
        showToast({ type: 'error', title: 'Cron expression required' });
        return;
      }
    }
    const actionVal = fd.get('action');
    let config = {};
    if (actionVal === 'agent') {
      const task = (fd.get('task') || '').trim();
      if (!task) {
        showToast({ type: 'error', title: 'Task required for agent action' });
        return;
      }
      config = { task, model: fd.get('model') || null };
    } else {
      const message = (fd.get('message') || '').trim();
      if (!message) {
        showToast({ type: 'error', title: 'Message required for chat action' });
        return;
      }
      config = { message };
    }
    const payload = {
      name: fd.get('name'),
      trigger: triggerVal,
      action: actionVal,
      config,
      enabled: !!fd.get('enabled'),
    };
    try {
      let id = auto?.id;
      if (isEdit) {
        await apiFetch(`/automations/${id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        showToast({ type: 'success', title: 'Automation updated' });
      } else {
        const res = await (await apiFetch('/automations', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })).json();
        id = res.id;
        showToast({ type: 'success', title: 'Automation created' });
      }
      if (id) writeConfigCache(id, config);
      wrap.innerHTML = '';
      await loadAutomations(bodyEl);
    } catch (err) {
      showToast({ type: 'error', title: 'Save failed', message: err?.message });
    }
  });
  wrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}
