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
  try {
    const data = await (await apiFetch('/features')).json();
    teamsEnabled = !!(data && data.features && data.features.multi_agent);
  } catch {
    teamsEnabled = false;
  }
  if (!teamsEnabled) return false;
  window.__sangamTeams = true;
  const btn = document.getElementById('teamsBtn');
  if (btn) {
    btn.classList.remove('hidden');
    btn.addEventListener('click', openTeamsModal);
  }
  return true;
}

function ensureModal() {
  let overlay = document.getElementById('teamsOverlay');
  if (overlay) return overlay;
  overlay = document.createElement('div');
  overlay.id = 'teamsOverlay';
  overlay.className = 'modal-overlay hidden';
  overlay.innerHTML = `
    <div class="modal teams-modal" role="dialog" aria-modal="true" aria-labelledby="teamsModalTitle">
      <div class="modal-header">
        <h2 id="teamsModalTitle"><i class="fa-solid fa-users"></i> Agent teams</h2>
        <button class="icon-btn ghost" id="closeTeams" aria-label="Close teams"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div class="teams-body">
        <div class="teams-controls">
          <select id="teamsSelect" class="provider-key-input" aria-label="Team"></select>
          <textarea id="teamsTask" rows="3" placeholder="Describe the task for the team…" aria-label="Team task"></textarea>
          <button class="btn-primary" id="teamsRun" type="button">Run team</button>
        </div>
        <div class="teams-results hidden" id="teamsResults"></div>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('#closeTeams').addEventListener('click', () => overlay.classList.add('hidden'));
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.classList.add('hidden'); });
  overlay.querySelector('#teamsRun').addEventListener('click', runTeam);
  return overlay;
}

export async function openTeamsModal() {
  const overlay = ensureModal();
  overlay.classList.remove('hidden');
  const select = overlay.querySelector('#teamsSelect');
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
  setTimeout(() => overlay.querySelector('#teamsTask')?.focus(), 0);
}

async function runTeam() {
  const overlay = document.getElementById('teamsOverlay');
  const teamId = overlay.querySelector('#teamsSelect').value;
  const task = overlay.querySelector('#teamsTask').value.trim();
  const resultsEl = overlay.querySelector('#teamsResults');
  const runBtn = overlay.querySelector('#teamsRun');
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
