/**
 * Runs centre — Phase 1 one-workspace surface.
 *
 * One tab for everything long-running plus the artifacts those runs
 * produced: live runs (Phase 0 RunStore, via GET /api/runs/live),
 * durable run history (GET /api/runs), and artifacts (GET /api/artifacts)
 * with preview, signed download (POST /artifacts/{id}/signed-url then
 * GET /api/artifacts/download?token=…), delete, and explicit retention
 * pruning. Nothing here invents a run or an artifact: empty states say
 * so, and every action hits a real endpoint.
 *
 * Accessibility: semantic headings, labelled buttons, list roles, and
 * text empty states (no icon-only controls).
 */
import { apiDelete, apiFetch, apiGet, apiPost, getApiBaseUrl } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] runs.js loaded');

function stateBadge(state) {
  const s = (state || 'unknown').toLowerCase();
  return `<span class="lib-kind">${escapeHtml(s)}</span>`;
}

function signedDownloadUrl(path) {
  // Backend returns "/api/artifacts/download?token=…"; apiBase already
  // ends in "/api", so strip it to get the backend origin first.
  return `${getApiBaseUrl().replace(/\/api$/, '')}${path}`;
}

export function renderRunsTab(bodyEl) {
  bodyEl.innerHTML = `
    <section class="library" aria-labelledby="runsTitle">
      <h2 id="runsTitle"><i class="fa-solid fa-list-check" aria-hidden="true"></i> Runs centre</h2>
      <p class="settings-hint">Live runs, run history, and artifacts in one place. Runs are recorded when agents, code agents, and teams finish; live runs also appear while they are in flight.</p>
      <button type="button" class="btn" id="runsRefresh" aria-label="Refresh runs and artifacts">Refresh</button>
      <h3 id="liveRunsTitle">Live runs</h3>
      <div id="liveRuns" role="region" aria-labelledby="liveRunsTitle"><p class="settings-hint">Loading…</p></div>
      <h3 id="historyTitle">Run history</h3>
      <div id="runHistory" role="region" aria-labelledby="historyTitle"><p class="settings-hint">Loading…</p></div>
      <h3 id="artifactsTitle">Artifacts</h3>
      <div id="artifactPanel" role="region" aria-labelledby="artifactsTitle"><p class="settings-hint">Loading…</p></div>
      <h3 id="mediaJobsTitle">Media jobs</h3>
      <div id="mediaJobs" role="region" aria-labelledby="mediaJobsTitle"><p class="settings-hint">Loading…</p></div>
      <h3 id="workflowRunsTitle">Workflow runs</h3>
      <div id="workflowRuns" role="region" aria-labelledby="workflowRunsTitle"><p class="settings-hint">Loading…</p></div>
      <div id="runsEmptyActions"></div>
      <div>
        <label for="pruneDays">Delete artifacts not updated in</label>
        <input id="pruneDays" type="number" min="1" value="90" aria-label="Retention days for pruning artifacts" style="width:80px">
        <span>days</span>
        <button type="button" class="btn" id="pruneArtifacts" aria-label="Delete stale artifacts">Prune stale artifacts</button>
      </div>
    </section>`;
  bodyEl.querySelector('#runsRefresh').addEventListener('click', () => loadAll(bodyEl));
  bodyEl.querySelector('#pruneArtifacts').addEventListener('click', async () => {
    const days = Number(bodyEl.querySelector('#pruneDays').value) || 90;
    try {
      const data = await (await apiPost('/artifacts/retention/prune', { days })).json();
      showToast({ type: 'info', title: `Pruned ${data.deleted} artifact(s) older than ${days} days` });
    } catch (err) {
      showToast({ type: 'error', title: 'Prune failed', message: err?.message || String(err) });
    }
    loadAll(bodyEl);
  });
  loadAll(bodyEl);
}

async function loadAll(bodyEl) {
  await Promise.all([
    loadLive(bodyEl), loadHistory(bodyEl), loadArtifacts(bodyEl),
    loadMediaJobs(bodyEl), loadWorkflowRuns(bodyEl),
  ]);
  // Batch 1: an empty Activity feed is a dead end without this — exactly
  // one clear next action per empty destination.
  const actions = bodyEl.querySelector('#runsEmptyActions');
  if (actions) {
    const liveEmpty = (bodyEl.querySelector('#liveRuns')?.textContent || '').includes('No live runs');
    const histEmpty = (bodyEl.querySelector('#runHistory')?.textContent || '').includes('No run history yet');
    if (liveEmpty && histEmpty) {
      actions.innerHTML = `<p class="settings-hint">Nothing has run yet.</p>
        <button type="button" class="btn-primary btn-sm" id="runsStartAgent">Run your first agent</button>
        <button type="button" class="btn-secondary btn-sm" id="runsStartWorkflow">Create your first workflow</button>`;
      actions.querySelector('#runsStartAgent').addEventListener('click', () => {
        import('../tabs/tabs.js').then((m) => m.showToolSection('work', 'agents'));
      });
      actions.querySelector('#runsStartWorkflow').addEventListener('click', () => {
        import('../tabs/tabs.js').then((m) => m.showToolSection('work', 'workflows'));
      });
    } else {
      actions.innerHTML = '';
    }
  }
}

/** Batch 1: media jobs mirrored into the Activity feed (tracking lives
 *  here; creation lives in Create > Media jobs). */
async function loadMediaJobs(bodyEl) {
  const wrap = bodyEl.querySelector('#mediaJobs');
  if (!wrap) return;
  try {
    const data = await (await apiFetch('/media-jobs')).json();
    const jobs = data.jobs || [];
    wrap.innerHTML = listHtml(jobs, 'No media jobs yet — create one in Create > Media jobs.',
      (j) => `<strong>${escapeHtml(j.kind || 'job')}</strong> · ${escapeHtml(j.status || '')}${j.error ? ` · ${escapeHtml(j.error)}` : ''}`);
  } catch {
    wrap.innerHTML = '<p class="settings-hint">Could not load media jobs.</p>';
  }
}

/** Batch 1: workflow runs aggregated across workflows (tracking lives
 *  here; the per-workflow list inside Workflows stays as a filter view). */
async function loadWorkflowRuns(bodyEl) {
  const wrap = bodyEl.querySelector('#workflowRuns');
  if (!wrap) return;
  try {
    const wfs = (await (await apiFetch('/workflows')).json()).workflows || [];
    const all = [];
    for (const wf of wfs.slice(0, 10)) {
      try {
        const runs = (await (await apiFetch(`/workflows/${encodeURIComponent(wf.id)}/runs`)).json()).runs || [];
        for (const r of runs.slice(0, 5)) all.push({ wf: wf.name, ...r });
      } catch { /* one workflow's runs failing must not hide the rest */ }
    }
    wrap.innerHTML = listHtml(all.slice(0, 20), 'No workflow runs yet — run a workflow in Work > Workflows.',
      (r) => `<strong>${escapeHtml(r.wf || '')}</strong> · ${escapeHtml(r.status || r.state || '')}`);
  } catch {
    wrap.innerHTML = '<p class="settings-hint">Could not load workflow runs.</p>';
  }
}

function listHtml(items, emptyText, row) {
  if (!items.length) return `<p class="settings-hint">${escapeHtml(emptyText)}</p>`;
  return `<ul role="list">${items.map((item) => `<li role="listitem">${row(item)}</li>`).join('')}</ul>`;
}

async function loadLive(bodyEl) {
  const wrap = bodyEl.querySelector('#liveRuns');
  try {
    const data = await (await apiGet('/runs/live')).json();
    wrap.innerHTML = listHtml(data.runs || [], 'No live runs right now.',
      (r) => `${escapeHtml(r.title || r.kind)} ${stateBadge(r.state)} — ${escapeHtml(r.kind)} · ${r.tokens || 0} tokens · $${Number(r.cost_usd || 0).toFixed(4)}`);
  } catch (err) {
    wrap.innerHTML = `<p class="settings-hint">Could not load live runs: ${escapeHtml(err?.message || err)}</p>`;
  }
}

async function loadHistory(bodyEl) {
  const wrap = bodyEl.querySelector('#runHistory');
  try {
    const data = await (await apiGet('/runs?limit=50')).json();
    wrap.innerHTML = listHtml(data.runs || [], 'No run history yet. Run an agent, code agent, or team to see it here.',
      (r) => `${escapeHtml(r.title)} ${stateBadge(r.status)} — ${escapeHtml(r.kind)} · ${r.tokens || 0} tokens · $${Number(r.cost_usd || 0).toFixed(4)}`);
  } catch (err) {
    wrap.innerHTML = `<p class="settings-hint">Could not load run history: ${escapeHtml(err?.message || err)}</p>`;
  }
}

async function loadArtifacts(bodyEl) {
  const wrap = bodyEl.querySelector('#artifactPanel');
  try {
    const data = await (await apiGet('/artifacts?limit=50')).json();
    const arts = data.artifacts || [];
    wrap.innerHTML = listHtml(arts, 'No artifacts yet. Create one from the Create hub or an agent run.',
      (a) => `${escapeHtml(a.title)} ${stateBadge(a.type)}
        <button type="button" class="btn" data-art-view="${escapeHtml(a.id)}" aria-label="Preview artifact ${escapeHtml(a.title)}">Preview</button>
        <button type="button" class="btn" data-art-download="${escapeHtml(a.id)}" aria-label="Download artifact ${escapeHtml(a.title)}">Download</button>
        <button type="button" class="btn" data-art-delete="${escapeHtml(a.id)}" aria-label="Delete artifact ${escapeHtml(a.title)}">Delete</button>
        <div data-art-preview="${escapeHtml(a.id)}"></div>`);
    wrap.querySelectorAll('[data-art-view]').forEach((b) => b.addEventListener('click', async () => {
      const preview = wrap.querySelector(`[data-art-preview="${b.dataset.artView}"]`);
      try {
        const art = await (await apiGet(`/artifacts/${b.dataset.artView}`)).json();
        preview.innerHTML = `<pre>${escapeHtml(art.content || '')}</pre>`;
      } catch (err) {
        preview.innerHTML = `<p class="settings-hint">Could not load artifact: ${escapeHtml(err?.message || err)}</p>`;
      }
    }));
    wrap.querySelectorAll('[data-art-download]').forEach((b) => b.addEventListener('click', async () => {
      try {
        const data2 = await (await apiPost(`/artifacts/${b.dataset.artDownload}/signed-url`, {})).json();
        window.open(signedDownloadUrl(data2.url), '_blank', 'noopener');
      } catch (err) {
        showToast({ type: 'error', title: 'Download failed', message: err?.message || String(err) });
      }
    }));
    wrap.querySelectorAll('[data-art-delete]').forEach((b) => b.addEventListener('click', async () => {
      try {
        await apiDelete(`/artifacts/${b.dataset.artDelete}`);
        showToast({ type: 'info', title: 'Artifact deleted' });
      } catch (err) {
        showToast({ type: 'error', title: 'Delete failed', message: err?.message || String(err) });
      }
      loadArtifacts(bodyEl);
    }));
  } catch (err) {
    wrap.innerHTML = `<p class="settings-hint">Could not load artifacts: ${escapeHtml(err?.message || err)}</p>`;
  }
}

// Re-exported for the module-link checker and for tests that import it.
export { loadAll };
