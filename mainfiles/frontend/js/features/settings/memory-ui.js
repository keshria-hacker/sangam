/**
 * Memory settings UI — browse, search, and curate long-term memories.
 *
 * Phase 8 B2: container-scoped (the legacy modal's global IDs are gone).
 * Renders into a host element passed by the caller.
 *
 * Talks to the memory++ API:
 *   GET    /api/memory?q=&limit=      search / list
 *   DELETE /api/memory/{id}           forget one memory
 *   GET    /api/memory/stats          counts by kind
 *   POST   /api/memory/consolidate    decay + prune pass
 */

import { apiFetch, apiDelete, apiPost } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
console.log('[Module] memory-ui.js loaded');

const KIND_LABEL = { episodic: 'episodic', semantic: 'semantic', procedural: 'procedural' };

/** Render the memory browser into `host`. Safe to call once per host. */
export function renderMemorySection(host) {
  if (!host || host.dataset.memWired) return;
  host.dataset.memWired = '1';
  host.innerHTML = `
    <div class="memory-stats" data-mem-stats></div>
    <div class="memory-controls" style="display:flex;gap:8px;margin:8px 0">
      <input class="provider-key-input" data-mem-search placeholder="Search memories…" aria-label="Search memories" style="flex:1">
      <button class="btn-secondary btn-sm" type="button" data-mem-tidy>Tidy up</button>
    </div>
    <div class="memory-list" data-mem-list></div>`;

  const stats = host.querySelector('[data-mem-stats]');
  const search = host.querySelector('[data-mem-search]');
  const list = host.querySelector('[data-mem-list]');
  const tidy = host.querySelector('[data-mem-tidy]');
  let searchTimer = null;

  async function renderList(query) {
    list.innerHTML = '<div class="memory-empty">Loading&hellip;</div>';
    try {
      const params = new URLSearchParams({ limit: '30' });
      if (query) params.set('q', query);
      const memories = await (await apiFetch(`/memory?${params.toString()}`)).json();
      if (!memories.length) {
        list.innerHTML = `<div class="memory-empty">${query ? 'No memories match.' : 'Nothing remembered yet. Sangam will remember facts, preferences, and corrections automatically.'}</div>`;
        return;
      }
      list.innerHTML = memories.map((m) => `
        <div class="memory-row" data-id="${escapeHtml(m.id)}">
          <span class="memory-kind ${escapeHtml(m.kind)}">${escapeHtml(m.kind)}</span>
          <span class="memory-text">${escapeHtml(m.content)}</span>
          <button class="memory-del" type="button" title="Forget this memory" aria-label="Forget this memory">&times;</button>
        </div>`).join('');
      list.querySelectorAll('.memory-del').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const row = btn.closest('.memory-row');
          const id = row?.dataset.id;
          if (!id) return;
          try {
            await apiDelete(`/memory/${encodeURIComponent(id)}`);
            row.remove();
            showToast({ type: 'success', title: 'Memory forgotten' });
            await refresh();
          } catch {
            showToast({ type: 'error', title: 'Could not delete memory' });
          }
        });
      });
    } catch {
      list.innerHTML = '<div class="memory-empty">Could not load memories.</div>';
    }
  }

  async function refresh() {
    try {
      const data = await (await apiFetch('/memory/stats')).json();
      const byKind = data.by_kind || {};
      stats.innerHTML =
        `<span class="memory-stat"><strong>${data.total || 0}</strong>memories</span>` +
        Object.entries(KIND_LABEL).map(([kind]) =>
          `<span class="memory-stat"><strong>${byKind[kind] || 0}</strong>${kind}</span>`
        ).join('');
    } catch {
      stats.innerHTML = '<span class="memory-stat">unavailable</span>';
    }
    await renderList(search.value.trim());
  }

  search.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => renderList(search.value.trim()), 250);
  });
  tidy.addEventListener('click', async () => {
    tidy.disabled = true;
    try {
      const result = await (await apiPost('/memory/consolidate', {})).json();
      showToast({ type: 'success', title: 'Memory tidied',
        message: `${result.pruned || 0} pruned, ${result.decayed || 0} decayed.` });
      await refresh();
    } catch {
      showToast({ type: 'error', title: 'Could not tidy memories' });
    } finally {
      tidy.disabled = false;
    }
  });

  refresh();
}

// Back-compat shims (no-ops now that the modal is gone).
export function initMemorySettings() {}
export async function refreshMemorySection() {}
