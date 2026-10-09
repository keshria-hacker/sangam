/**
 * Agent teams UI — pick a team, describe the task, watch specialists work.
 *
 * Shown only when the backend `multi_agent` feature flag is on. Team runs
 * are synchronous: the backend fans out to specialists concurrently and
 * returns the coordinator's synthesis plus per-specialist outputs.
 */

import { apiFetch, apiPost } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
import { renderMarkdown } from '../../shared/markdown.js';
console.log('[Module] teams.js loaded');

let teamsEnabled = false;
let teams = [];

export function isTeamsEnabled() {
  return teamsEnabled;
}

export async function initTeams() {
  const btn = document.getElementById('teamsBtn');
  if (btn && !btn.dataset.wired) {
    btn.dataset.wired = '1';
    btn.addEventListener('click', async () => {
      const { openToolTab } = await import('../tabs/tabs.js');
      openToolTab('teams');
    });
  }
  try {
    const data = await (await apiFetch('/features')).json();
    teamsEnabled = !!(data && data.features && data.features.multi_agent);
  } catch {
    teamsEnabled = false;
  }
  if (!teamsEnabled) return false;
  window.__sangamTeams = true;
  btn?.classList.remove('hidden');
  return true;
}

/**
 * Render the Agent teams UI into a tab body (replaces the old modal).
 */
export async function renderTeamsTab(bodyEl) {
  bodyEl.innerHTML = `
    <div class="teams-tab">
      <div class="teams-controls">
        <select id="teamsSelect" class="provider-key-input" aria-label="Team"></select>
        <textarea id="teamsTask" rows="3" placeholder="Describe the task for the team…" aria-label="Team task"></textarea>
        <button class="btn-primary" id="teamsRun" type="button">Run team</button>
      </div>
      <div class="teams-results hidden" id="teamsResults"></div>
    </div>`;
  bodyEl.querySelector('#teamsRun').addEventListener('click', () => runTeam(bodyEl));
  const select = bodyEl.querySelector('#teamsSelect');
  if (!teams.length) {
    try {
      teams = await (await apiFetch('/teams')).json();
    } catch {
      teams = [];
    }
  }
  select.innerHTML = teams.length
    ? teams.map((t) => `<option value="${escapeHtml(t.id)}">${escapeHtml(t.name)} — ${escapeHtml(t.description.slice(0, 80))}</option>`).join('')
    : '<option value="">No teams available</option>';
  setTimeout(() => bodyEl.querySelector('#teamsTask')?.focus(), 0);
}

// Back-compat: old modal entry point now opens the tab
export async function openTeamsModal() {
  const { openToolTab } = await import('../tabs/tabs.js');
  openToolTab('teams');
}

async function runTeam(container) {
  const root = container || document;
  const teamId = root.querySelector('#teamsSelect').value;
  const task = root.querySelector('#teamsTask').value.trim();
  const resultsEl = root.querySelector('#teamsResults');
  const runBtn = root.querySelector('#teamsRun');
  if (!teamId || !task) {
    showToast({ type: 'info', title: 'Pick a team and describe the task' });
    return;
  }
  runBtn.disabled = true;
  resultsEl.classList.remove('hidden');
  resultsEl.innerHTML = '<div class="teams-running"><i class="fa-solid fa-circle-notch fa-spin"></i> Specialists working in parallel…</div>';
  try {
    const result = await (await apiPost('/teams/run', { team_id: teamId, task })).json();
    const specialists = (result.specialists || []).map((s) => `
      <details class="team-specialist">
        <summary><strong>${escapeHtml(s.role)}</strong>
          <span class="team-meta">${s.error ? 'failed' : `${s.elapsed_s}s`}</span></summary>
        <div class="team-output">${s.error ? `<p class="team-error">${escapeHtml(s.error)}</p>` : renderMarkdown(s.output || '')}</div>
      </details>`).join('');
    resultsEl.innerHTML = `
      <div class="team-synthesis"><h4>Synthesis</h4>${renderMarkdown(result.synthesis || '_No synthesis produced._')}</div>
      <div class="team-specialists"><h4>Specialists (${result.elapsed_s}s total)</h4>${specialists}</div>`;
  } catch (err) {
    resultsEl.innerHTML = `<p class="team-error">Team run failed: ${escapeHtml(err?.message || String(err))}</p>`;
  } finally {
    runBtn.disabled = false;
  }
}
