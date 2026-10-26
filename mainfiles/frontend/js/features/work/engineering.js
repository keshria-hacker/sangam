/**
 * Engineering pipeline page (Batch 5) — Work > Engineering section.
 *
 * Renders the enforced pipeline list, stage progress, advance form and
 * artifact view. Stages advance only in order (grill -> brainstorm ->
 * design -> plan -> subagent -> review-spec -> review-quality -> finish);
 * the backend returns 422 on out-of-order advances or missing review
 * prerequisites, and that error is shown, not hidden.
 */
import { apiGet, apiPost } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] engineering.js loaded');

export async function renderEngineeringPage(bodyEl) {
  bodyEl.innerHTML = `
    <section class="library" aria-labelledby="engTitle">
      <h2 id="engTitle">Engineering</h2>
      <p class="settings-hint">Enforced workflow: grill, brainstorm, design, plan, subagent, two-stage review, finish. The subagent stage runs a linked team run when a model is configured, otherwise it records a marked handoff brief — never fabricated output.</p>
      <h3>New pipeline</h3>
      <form id="engCreateForm">
        <label>Title <input type="text" id="engTitleInput" placeholder="Feature name" aria-label="Pipeline title" required></label>
        <label>Goal <input type="text" id="engGoalInput" placeholder="What are we building?" aria-label="Pipeline goal"></label>
        <button type="submit" class="btn" aria-label="Create engineering pipeline">Create pipeline</button>
      </form>
      <h3>Pipelines</h3>
      <div id="engList" role="region" aria-label="Engineering pipelines"><p class="settings-hint">Loading…</p></div>
    </section>`;

  const listEl = bodyEl.querySelector('#engList');

  async function load() {
    try {
      const data = await (await apiGet('/engineering')).json();
      const pipes = Array.isArray(data) ? data : [];
      listEl.innerHTML = pipes.map((p) => `
        <div class="lib-card eng-card" data-pipe="${escapeHtml(p.id)}">
          <div class="lib-card-head">
            <strong>${escapeHtml(p.title)}</strong>
            <span class="settings-hint">${escapeHtml(p.current_stage || 'not started')} → ${escapeHtml(p.next_stage || 'done')}</span>
          </div>
          <p class="settings-hint">Progress: ${(p.stages || []).length} stage(s) recorded — now: ${escapeHtml(p.current_stage || 'not started')}, next: ${escapeHtml(p.next_stage || 'done')}.</p>
          <p class="lib-desc">${escapeHtml(p.goal || '')}</p>
          <div class="eng-stages">
            ${(p.stages || []).map((s) => `
              <div class="eng-stage">
                <strong>${escapeHtml(s.stage)}</strong>
                ${s.verdict ? `<span class="lib-kind">${escapeHtml(s.verdict)}</span>` : ''}
                <span class="settings-hint">${escapeHtml(s.source || '')}</span>
                <pre class="lib-skill-md">${escapeHtml((s.artifact || '').slice(0, 1000))}</pre>
              </div>`).join('') || '<p class="settings-hint">No stages yet.</p>'}
          </div>
          ${p.next_stage ? `
          <form class="eng-advance-form" data-advance>
            <label>Advance to ${escapeHtml(p.next_stage)}
              <textarea data-artifact placeholder="Stage artifact text (for the subagent stage, a request note — the output comes from the team run or a handoff brief)" aria-label="Stage artifact"></textarea>
            </label>
            ${p.next_stage.startsWith('review') ? `
            <label>Verdict
              <select data-verdict aria-label="Review verdict">
                <option value="pass">pass</option>
                <option value="fail">fail</option>
              </select>
            </label>
            <label>Prerequisite artifact id
              <select data-prereq aria-label="Prerequisite artifact">
                ${(p.stages || []).map((s) => `<option value="${escapeHtml(s.id)}">${escapeHtml(s.stage)}</option>`).join('')}
              </select>
            </label>` : ''}
            <button type="submit" class="btn-secondary btn-sm" aria-label="Advance pipeline stage">Advance: ${escapeHtml(p.next_stage)}</button>
          </form>` : '<p class="settings-hint">Pipeline finished.</p>'}
        </div>`).join('') || '<p class="settings-hint">No pipelines yet.</p>';
      listEl.querySelectorAll('[data-advance]').forEach((form) => {
        form.addEventListener('submit', async (ev) => {
          ev.preventDefault();
          const card = form.closest('.eng-card');
          const pipeId = card.dataset.pipe;
          const pipe = pipes.find((x) => x.id === pipeId);
          const body = {
            stage: pipe.next_stage,
            artifact: form.querySelector('[data-artifact]').value,
          };
          const verdictEl = form.querySelector('[data-verdict]');
          const prereqEl = form.querySelector('[data-prereq]');
          if (verdictEl) body.verdict = verdictEl.value;
          if (prereqEl) body.prerequisite_artifact_id = prereqEl.value;
          try {
            await apiPost(`/engineering/${encodeURIComponent(pipeId)}/advance`, body);
            showToast({ type: 'success', title: `Advanced to ${pipe.next_stage}` });
            await load();
          } catch (err) {
            showToast({ type: 'error', title: 'Advance failed', message: err?.message || String(err) });
          }
        });
      });
    } catch (err) {
      listEl.innerHTML = `<p class="team-error">Could not load pipelines: ${escapeHtml(err?.message || String(err))}</p>`;
    }
  }

  bodyEl.querySelector('#engCreateForm').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try {
      await apiPost('/engineering', {
        title: bodyEl.querySelector('#engTitleInput').value.trim(),
        goal: bodyEl.querySelector('#engGoalInput').value.trim(),
      });
      showToast({ type: 'success', title: 'Pipeline created' });
      await load();
    } catch (err) {
      showToast({ type: 'error', title: 'Create failed', message: err?.message || String(err) });
    }
  });

  await load();
}
