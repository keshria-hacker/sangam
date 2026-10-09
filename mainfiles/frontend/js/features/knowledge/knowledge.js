/**
 * Knowledge tab — Phase 2 stub. Full knowledge graph in Phase 3.
 * For now: memory browser + code map explorer links.
 */
import { apiFetch } from '../../shared/http.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] knowledge.js loaded');

export async function renderKnowledgeTab(bodyEl) {
  bodyEl.innerHTML = `
    <div class="knowledge-stub">
      <h3><i class="fa-solid fa-brain"></i> Knowledge</h3>
      <p class="settings-hint">The full knowledge graph arrives in Phase 3. For now:</p>
      <div class="knowledge-links">
        <button class="btn-secondary" id="knMemories"><i class="fa-solid fa-database"></i> Browse memories</button>
        <button class="btn-secondary" id="knCodemap"><i class="fa-solid fa-diagram-project"></i> Explore code map</button>
      </div>
      <div id="knResults" class="knowledge-results"></div>
    </div>`;

  bodyEl.querySelector('#knMemories')?.addEventListener('click', async () => {
    const res = bodyEl.querySelector('#knResults');
    res.innerHTML = '<p class="settings-hint">Loading…</p>';
    try {
      const data = await (await apiFetch('/memory/list?limit=20')).json();
      const items = data.memories || data.items || [];
      res.innerHTML = items.length
        ? `<ul class="memory-list">${items.map((m) => `<li><strong>${escapeHtml(m.kind || '')}</strong> ${escapeHtml((m.content || '').slice(0, 120))}</li>`).join('')}</ul>`
        : '<p class="settings-hint">No memories yet.</p>';
    } catch {
      res.innerHTML = '<p class="settings-hint">Could not load memories.</p>';
    }
  });

  bodyEl.querySelector('#knCodemap')?.addEventListener('click', async () => {
    const { openToolTab } = await import('../tabs/tabs.js');
    openToolTab('code'); // code map lives in the Code agent tab for now
  });
}
