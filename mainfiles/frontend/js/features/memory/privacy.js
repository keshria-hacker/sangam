/**
 * Memory privacy dashboard — A3 (perfect-flow §5 Cluster C privacy).
 *
 * Destination-agnostic: the coordinator's shell agent mounts this under
 * Settings → Memory & Knowledge (and/or Knowledge). Shows exactly what
 * is stored, per-memory delete, retention preview + bulk forget, and
 * the separation between conversation context (chat messages, deleted
 * with their chat) and persistent memory (deleted only here). All data
 * comes from /memory/dashboard, /memory/{id} and /memory/forget —
 * nothing is invented, and retention is a visible control, not a
 * hidden .env knob.
 */
import { apiDelete, apiFetch, apiGet, apiPost } from '../../shared/http.js';
import { escapeHtml } from '../../shared/utils.js';
import { showError, showSuccess } from '../../shared/toast.js';

console.log('[Module] privacy.js loaded');

export async function renderMemoryDashboard(containerEl) {
  containerEl.innerHTML = `
    <div class="memory-dashboard">
      <h3>Memory privacy dashboard</h3>
      <p class="settings-hint">Everything Sangam remembers about you, in one place. Delete any single memory, or forget memories older than a number of days. Deleting a chat does <em>not</em> delete memories taken from it — this dashboard is where those go away.</p>
      <div id="mdSummary"></div>
      <form id="mdRetention" class="pj-form">
        <label>Forget memories older than
          <input type="number" id="mdDays" min="1" value="90"> days
        </label>
        <button type="button" class="btn-secondary" id="mdPreview">Preview</button>
        <label><input type="checkbox" id="mdConfirm"> I understand this cannot be undone</label>
        <button type="submit" class="btn-primary">Forget older memories</button>
        <span id="mdPreviewOut" class="settings-hint"></span>
      </form>
      <div class="pj-form">
        <button type="button" class="btn-secondary" id="mdExport">Export all memories (JSON)</button>
      </div>
      <div id="mdList"></div>
    </div>`;
  containerEl.querySelector('#mdPreview').addEventListener('click', async () => {
    const days = containerEl.querySelector('#mdDays').value;
    try {
      const data = await (await apiGet(`/memory/dashboard?older_than_days=${encodeURIComponent(days)}`)).json();
      const preview = data.retention_preview || {};
      containerEl.querySelector('#mdPreviewOut').textContent =
        `Would forget ${preview.would_forget ?? '?'} of ${data.total_memories ?? '?'} memories.`;
    } catch (err) { showError(err.message || 'Preview failed'); }
  });
  containerEl.querySelector('#mdRetention').addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!containerEl.querySelector('#mdConfirm').checked) {
      showError('Tick the confirmation box first — bulk forget cannot be undone.');
      return;
    }
    try {
      const data = await (await apiPost('/memory/forget', {
        older_than_days: parseInt(containerEl.querySelector('#mdDays').value, 10),
        confirm: true,
      })).json();
      showSuccess(`Forgot ${data.deleted} memories`);
      await loadDashboard(containerEl);
    } catch (err) { showError(err.message || 'Bulk forget failed'); }
  });
  containerEl.querySelector('#mdExport').addEventListener('click', async () => {
    try {
      const res = await apiFetch('/memory/export');
      const blob = new Blob([JSON.stringify(await res.json(), null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'sangam-memories.json'; a.click();
      URL.revokeObjectURL(url);
    } catch (err) { showError(err.message || 'Export failed'); }
  });
  await loadDashboard(containerEl);
}

async function loadDashboard(containerEl) {
  const summaryEl = containerEl.querySelector('#mdSummary');
  const listEl = containerEl.querySelector('#mdList');
  try {
    const data = await (await apiGet('/memory/dashboard')).json();
    const sep = data.separation || {};
    const conv = sep.conversation_context || {};
    const pers = sep.persistent_memory || {};
    summaryEl.innerHTML = `
      <p><strong>${data.total_memories ?? 0}</strong> persistent memories ·
      <strong>${conv.chat_count ?? 0}</strong> chats ·
      <strong>${conv.message_count ?? 0}</strong> chat messages (conversation context)</p>
      <p class="settings-hint">Conversation context: ${escapeHtml(conv.stored_as || '')} — deleted when ${escapeHtml(conv.deleted_when || '')}.
      Persistent memory: ${escapeHtml(pers.stored_as || '')} — deleted ${escapeHtml(pers.deleted_when || '')}.</p>
      <p class="settings-hint">${escapeHtml(pers.note || '')}</p>`;
    const memories = data.memories || [];
    if (!memories.length) {
      listEl.innerHTML = '<p class="settings-hint">No persistent memories stored.</p>';
      return;
    }
    listEl.innerHTML = `<ul>${memories.map((m) => `<li>
      <p>${escapeHtml(m.content || '')}</p>
      <small>${escapeHtml(m.kind || '')} · importance ${m.importance ?? ''} · ${escapeHtml(m.room || '')}/${escapeHtml(m.drawer || '')} · ${escapeHtml(m.created_at || '')}</small>
      <button class="btn-secondary md-del" data-id="${escapeHtml(m.id)}">Delete</button></li>`).join('')}</ul>`;
    listEl.querySelectorAll('.md-del').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try {
          await apiDelete(`/memory/${btn.dataset.id}`);
          showSuccess('Memory deleted');
          await loadDashboard(containerEl);
        } catch (err) { showError(err.message || 'Could not delete memory'); }
      });
    });
  } catch (err) {
    summaryEl.innerHTML = `<p class="settings-hint">Could not load dashboard: ${escapeHtml(err.message || '')}</p>`;
  }
}
