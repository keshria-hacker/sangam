/**
 * Agent teams UI — pick a team, describe the task, watch specialists work live.
 *
 * Shown only when the backend `multi_agent` feature flag is on.
 * Uses POST /teams/run/stream (SSE): one live card per specialist with
 * per-agent Stop and Retry, then the streamed synthesis.
 * Activity Tray stays in sync via jobs.js (abort + progress updates).
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
  // Navigation via studio rail (core/nav.js) — no per-button wiring needed.
  try {
    const data = await (await apiFetch('/features')).json();
    teamsEnabled = !!(data && data.features && data.features.multi_agent);
  } catch {
    teamsEnabled = false;
  }
  if (!teamsEnabled) return false;
  window.__sangamTeams = true;
  return true;
}

/**
 * Render the Agent teams UI into a tab body.
 */
export async function renderTeamsTab(bodyEl) {
  bodyEl.innerHTML = `
    <div class="teams-tab">
      <div class="teams-controls">
        <select id="teamsSelect" class="provider-key-input" aria-label="Team"></select>
        <textarea id="teamsTask" rows="3" placeholder="Describe the task for the team…" aria-label="Team task"></textarea>
        <div class="teams-actions">
          <button class="btn-primary" id="teamsRun" type="button">Run team</button>
          <button class="btn-secondary hidden" id="teamsStopAll" type="button">Stop all</button>
        </div>
      </div>
      <div class="teams-results hidden" id="teamsResults"></div>
    </div>`;
  const runBtn = bodyEl.querySelector('#teamsRun');
  const stopAllBtn = bodyEl.querySelector('#teamsStopAll');
  const select = bodyEl.querySelector('#teamsSelect');
  if (!teams.length) {
    try {
      teams = await (await apiFetch('/teams')).json();
    } catch {
      teams = [];
    }
  }
  select.innerHTML = teams.length
    ? teams.map((t) => `<option value="${escapeHtml(t.id)}">${escapeHtml(t.name)} — ${escapeHtml((t.description || '').slice(0, 80))}</option>`).join('')
    : '<option value="">No teams available</option>';
  setTimeout(() => bodyEl.querySelector('#teamsTask')?.focus(), 0);

  let abort = null;
  let runState = null; // { runId, teamId, task, cards: Map<agentId, cardEl> }

  runBtn.addEventListener('click', () => runTeam(bodyEl, select, runBtn, stopAllBtn,
    (a) => { abort = a; }, (s) => { runState = s; }, () => runState));
  stopAllBtn.addEventListener('click', () => { abort?.abort(); });
}

// Back-compat: old modal entry point now opens the tab
export async function openTeamsModal() {
  const { openToolTab } = await import('../tabs/tabs.js');
  openToolTab('teams');
}

function cardFor(container, agentId, role) {
  let card = container.querySelector(`[data-agent="${CSS.escape(agentId)}"]`);
  if (card) return card;
  const wrap = container.querySelector('#teamsSpecialists');
  card = document.createElement('div');
  card.className = 'team-card';
  card.dataset.agent = agentId;
  card.innerHTML = `
    <div class="team-card-head">
      <strong>${escapeHtml(role || agentId)}</strong>
      <span class="team-card-status" data-status>working…</span>
      <span class="team-card-actions">
        <button class="btn-secondary btn-sm" data-stop type="button">Stop</button>
        <button class="btn-secondary btn-sm hidden" data-retry type="button">Retry</button>
      </span>
    </div>
    <div class="team-card-body" data-body></div>`;
  wrap.appendChild(card);
  return card;
}

function setCardStatus(card, text, cls) {
  const el = card.querySelector('[data-status]');
  el.textContent = text;
  el.className = `team-card-status ${cls || ''}`;
}

async function runTeam(bodyEl, select, runBtn, stopAllBtn, setAbort, setRunState, getRunState) {
  const root = bodyEl;
  const teamId = select.value;
  const task = root.querySelector('#teamsTask').value.trim();
  const resultsEl = root.querySelector('#teamsResults');
  if (!teamId || !task) {
    showToast({ type: 'info', title: 'Pick a team and describe the task' });
    return;
  }

  runBtn.classList.add('hidden');
  stopAllBtn.classList.remove('hidden');
  resultsEl.classList.remove('hidden');
  resultsEl.innerHTML = `
    <div class="team-synthesis hidden" id="teamsSynthesis"><h4>Synthesis</h4><div data-synth-body></div></div>
    <div class="team-specialists"><h4>Specialists</h4><div id="teamsSpecialists"></div></div>`;

  const abort = new AbortController();
  setAbort(abort);
  const jobsMod = await import('../../core/jobs.js');
  const jobId = jobsMod.startJob({
    kind: 'team',
    title: `${teamId}: ${task.slice(0, 50)}`,
    abort: () => abort.abort(),
  });

  const cards = new Map();
  const outputs = new Map(); // agentId -> full text (for retry rendering)
  let runId = null;
  let synthBuf = '';
  let doneCount = 0;
  const synthBody = () => resultsEl.querySelector('[data-synth-body]');

  const updateProgress = () => {
    const total = cards.size || 1;
    jobsMod.updateJob(jobId, { progress: doneCount / total, detail: `${doneCount}/${total} specialists done` });
  };

  const wireCardButtons = (card, agentId) => {
    card.querySelector('[data-stop]').addEventListener('click', async () => {
      if (!runId) return;
      try {
        const r = await (await apiPost('/teams/stop-agent', { run_id: runId, agent_id: agentId })).json();
        if (r.stopped) {
          setCardStatus(card, 'stopped', 'team-stopped');
          card.querySelector('[data-stop]').classList.add('hidden');
          card.querySelector('[data-retry]').classList.remove('hidden');
        } else {
          showToast({ type: 'info', title: 'Agent already finished' });
        }
      } catch (err) {
        showToast({ type: 'error', title: 'Stop failed', message: String(err?.message || err) });
      }
    });
    card.querySelector('[data-retry]').addEventListener('click', async () => {
      const retryBtn = card.querySelector('[data-retry]');
      retryBtn.disabled = true;
      setCardStatus(card, 'retrying…', '');
      card.querySelector('[data-body]').innerHTML = '';
      try {
        const r = await (await apiPost('/teams/retry-agent', { team_id: teamId, task, agent_id: agentId })).json();
        if (r.error) {
          setCardStatus(card, 'failed', 'team-failed');
          card.querySelector('[data-body]').innerHTML = `<p class="team-error">${escapeHtml(r.error)}</p>`;
        } else {
          outputs.set(agentId, r.output);
          setCardStatus(card, `done (${r.elapsed_s}s)`, 'team-done');
          card.querySelector('[data-body]').innerHTML = renderMarkdown(r.output || '');
          card.querySelector('[data-stop]').classList.add('hidden');
        }
      } catch (err) {
        setCardStatus(card, 'failed', 'team-failed');
        card.querySelector('[data-body]').innerHTML = `<p class="team-error">${escapeHtml(err?.message || String(err))}</p>`;
      } finally {
        retryBtn.disabled = false;
        retryBtn.classList.add('hidden');
      }
    });
  };

  setRunState({ get runId() { return runId; }, teamId, task });

  try {
    const res = await apiFetch('/teams/run/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ team_id: teamId, task }),
      signal: abort.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    const handleEvent = (ev) => {
      switch (ev.type) {
        case 'team_start':
          runId = ev.run_id || runId;
          break;
        case 'specialist_start': {
          const card = cardFor(resultsEl, ev.agent_id, ev.role);
          cards.set(ev.agent_id, card);
          outputs.set(ev.agent_id, '');
          wireCardButtons(card, ev.agent_id);
          setCardStatus(card, 'working…', '');
          updateProgress();
          break;
        }
        case 'specialist_chunk': {
          const card = cards.get(ev.agent_id);
          if (!card) break;
          outputs.set(ev.agent_id, (outputs.get(ev.agent_id) || '') + (ev.text || ''));
          const body = card.querySelector('[data-body]');
          // Append as plain text during streaming for speed; render markdown on done
          body.textContent = outputs.get(ev.agent_id);
          body.scrollTop = body.scrollHeight;
          break;
        }
        case 'specialist_done': {
          const card = cards.get(ev.agent_id);
          doneCount++;
          if (card) {
            outputs.set(ev.agent_id, ev.output || outputs.get(ev.agent_id) || '');
            setCardStatus(card, `done (${ev.elapsed_s}s)`, 'team-done');
            card.querySelector('[data-body]').innerHTML = renderMarkdown(outputs.get(ev.agent_id));
            card.querySelector('[data-stop]').classList.add('hidden');
          }
          updateProgress();
          break;
        }
        case 'specialist_error': {
          const card = cards.get(ev.agent_id);
          doneCount++;
          if (card) {
            setCardStatus(card, 'failed', 'team-failed');
            card.querySelector('[data-body]').innerHTML = `<p class="team-error">${escapeHtml(ev.error || 'Unknown error')}</p>`;
            card.querySelector('[data-stop]').classList.add('hidden');
            card.querySelector('[data-retry]').classList.remove('hidden');
          }
          updateProgress();
          break;
        }
        case 'specialist_stopped': {
          const card = cards.get(ev.agent_id);
          doneCount++;
          if (card) {
            setCardStatus(card, 'stopped', 'team-stopped');
            card.querySelector('[data-stop]').classList.add('hidden');
            card.querySelector('[data-retry]').classList.remove('hidden');
          }
          updateProgress();
          break;
        }
        case 'synthesis_start': {
          resultsEl.querySelector('#teamsSynthesis').classList.remove('hidden');
          jobsMod.updateJob(jobId, { detail: 'Synthesizing…' });
          break;
        }
        case 'synthesis_chunk': {
          synthBuf += ev.text || '';
          synthBody().textContent = synthBuf;
          break;
        }
        case 'synthesis_done': {
          synthBody().innerHTML = renderMarkdown(ev.output || synthBuf);
          break;
        }
        case 'team_done': {
          jobsMod.finishJob(jobId, 'done');
          break;
        }
        case 'error': {
          resultsEl.insertAdjacentHTML('beforeend',
            `<p class="team-error">Team error: ${escapeHtml(ev.error || 'Unknown')}</p>`);
          jobsMod.finishJob(jobId, 'failed', ev.error);
          break;
        }
        default:
          break;
      }
    };

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
          handleEvent(JSON.parse(line.slice(5).trim()));
        } catch { /* partial JSON */ }
      }
    }
  } catch (err) {
    if (err?.name !== 'AbortError') {
      resultsEl.insertAdjacentHTML('beforeend',
        `<p class="team-error">Team run failed: ${escapeHtml(err?.message || String(err))}</p>`);
      jobsMod.finishJob(jobId, 'failed', String(err?.message || err));
    } else {
      jobsMod.finishJob(jobId, 'done');
    }
  } finally {
    const job = jobsMod.getJobs().find((j) => j.id === jobId);
    if (job && job.status === 'running') jobsMod.finishJob(jobId, 'done');
    runBtn.classList.remove('hidden');
    stopAllBtn.classList.add('hidden');
    setAbort(null);
    setRunState(null);
  }
}
