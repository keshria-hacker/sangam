/**
 * Studio section (Batch 11) — a SECTION inside Create, not a destination.
 *
 * One panel for the unified media pipeline: create a staged pipeline
 * job, approve a checkpoint, validate a diagram, critique a prototype,
 * and run a node graph. Every output is an asset with its sidecar
 * (engine, parameters, evidence, cost) shown next to it. Plain-language
 * empty states explain what each tool does and what it refuses to do:
 * no voice cloning, no video, no face-identity work.
 */
import { apiFetch, apiPost } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] media/studio.js loaded');

export async function renderStudioSection(container) {
  container.innerHTML = `
    <div class="studio-panel">
      <h4 class="hub-section-title">Advanced: multi-step jobs</h4>
      <p class="settings-hint">Build a staged job: stages run in order, and a stage set to
        pause waits for your approval before the next stage runs. Nothing here clones
        a voice, makes video, or uses face identity — those requests are refused.</p>
      <details class="advanced-section"><summary>Advanced: combine steps</summary>
      <div class="studio-form">
        <label class="settings-hint">Job kind
          <select id="studioKind" class="provider-key-input">
            <option value="tts">Voice a script (text → audio)</option>
            <option value="image">Image (prompt → image)</option>
            <option value="audiobook">Audiobook (chapters → audio)</option>
          </select>
        </label>
        <textarea id="studioText" class="create-ed-input" rows="4"
          placeholder="Text to voice, image prompt, or audiobook text…"></textarea>
        <label class="settings-hint"><input type="checkbox" id="studioCheckpoint">
          Pause for my approval between steps</label>
        <button class="btn-primary btn-sm" id="studioCreate">Create pipeline job</button>
      </div>
      </details>
      <div id="studioJobs"><p class="settings-hint">No pipeline jobs yet — create one above.</p></div>
      <h4 class="hub-section-title">Diagram check</h4>
      <p class="settings-hint">Paste a typed diagram (architecture, ERD, sequence, workflow,
        timeline) as JSON to validate it, or check a layout's 4px grid and overlap.</p>
      <div class="studio-form">
        <textarea id="studioDiagram" class="create-ed-input" rows="4"
          placeholder='{"schema_version": 1, "diagram_type": "erd", "meta": {"title": "…", "evidence": "illustrative"}, "tables": []}'></textarea>
        <button class="btn-secondary btn-sm" id="studioValidate">Validate diagram</button>
        <pre id="studioValidateOut" class="settings-hint"></pre>
      </div>
      <h4 class="hub-section-title">Subtitles for video</h4>
      <p class="settings-hint">Subtitles for video fits a script onto timed subtitle segments and
        exports SRT, VTT and word-level ASS. It needs timed segments — timings are never
        invented. The Media jobs "dub" kind only voices a script; this section builds the timed subtitles.</p>
      <div class="studio-form">
        <textarea id="studioDub" class="create-ed-input" rows="3"
          placeholder='{"segments": [{"start": 0, "end": 2.5, "text": "Hello"}], "script": "Hello"}'></textarea>
        <button class="btn-secondary btn-sm" id="studioDubBtn">Build subtitles</button>
        <pre id="studioDubOut" class="settings-hint"></pre>
      </div>
    </div>`;

  container.querySelector('#studioCreate').addEventListener('click', async () => {
    const kind = container.querySelector('#studioKind').value;
    const text = container.querySelector('#studioText').value.trim();
    const checkpoint = container.querySelector('#studioCheckpoint').checked;
    if (!text) { showToast({ type: 'error', title: 'Enter some text or a prompt first' }); return; }
    const stage = kind === 'image'
      ? { name: 'generate', action: 'image', checkpoint_required: checkpoint, input: { prompt: text } }
      : kind === 'audiobook'
        ? { name: 'plan', action: 'audiobook_plan', checkpoint_required: checkpoint, input: { text } }
        : { name: 'voice', action: 'voice_script', checkpoint_required: checkpoint, input: { text } };
    try {
      const res = await apiPost('/media-jobs', {
        kind: kind === 'audiobook' ? 'audiobook' : kind,
        text: kind === 'image' ? undefined : text,
        prompt: kind === 'image' ? text : undefined,
        pipeline: { stages: [stage] },
      });
      const data = await res.json();
      showToast({ type: 'success', title: `Pipeline job ${data.id} created (${data.status})` });
      await loadJobs(container);
    } catch (err) {
      showToast({ type: 'error', title: 'Job failed', message: err?.message || String(err) });
    }
  });

  container.querySelector('#studioValidate').addEventListener('click', async () => {
    const out = container.querySelector('#studioValidateOut');
    try {
      const diagram = JSON.parse(container.querySelector('#studioDiagram').value);
      const res = await apiPost('/diagrams/validate', { diagram });
      out.textContent = JSON.stringify(await res.json(), null, 2);
    } catch (err) {
      out.textContent = `Could not validate: ${escapeHtml(err?.message || String(err))}`;
    }
  });

  container.querySelector('#studioDubBtn').addEventListener('click', async () => {
    const out = container.querySelector('#studioDubOut');
    try {
      const payload = JSON.parse(container.querySelector('#studioDub').value);
      const res = await apiPost('/voice/dub', payload);
      const data = await res.json();
      out.textContent = `SRT:\n${data.srt}\nVTT:\n${data.vtt}`;
    } catch (err) {
      out.textContent = `Could not build subtitles: ${escapeHtml(err?.message || String(err))}`;
    }
  });

  await loadJobs(container);
}

async function loadJobs(container) {
  const wrap = container.querySelector('#studioJobs');
  try {
    const data = await (await apiFetch('/media-jobs')).json();
    const jobs = (data.jobs || []).filter((j) => j.input && j.input.pipeline);
    if (!jobs.length) {
      wrap.innerHTML = '<p class="settings-hint">No pipeline jobs yet — create one above.</p>';
      return;
    }
    wrap.innerHTML = jobs.map((j) => `
      <div class="hub-card">
        <div class="hub-card-head"><strong>${escapeHtml(j.id)}</strong>
          <span class="settings-hint">${escapeHtml(j.kind)} · ${escapeHtml(j.status)}</span></div>
        <span class="settings-hint">${escapeHtml(JSON.stringify(j.result?.pipeline_state || {}))}</span>
        ${j.status === 'awaiting_approval'
          ? `<button class="btn-primary btn-sm" data-approve="${escapeHtml(j.id)}">Approve &amp; continue</button>`
          : ''}
      </div>`).join('');
    wrap.querySelectorAll('[data-approve]').forEach((b) => {
      b.addEventListener('click', async () => {
        try {
          await apiPost(`/media-jobs/${b.dataset.approve}/approve`, {});
          showToast({ type: 'success', title: 'Approved — pipeline continues' });
          await loadJobs(container);
        } catch (err) {
          showToast({ type: 'error', title: 'Approve failed', message: err?.message || String(err) });
        }
      });
    });
  } catch {
    wrap.innerHTML = '<p class="settings-hint">Could not load pipeline jobs.</p>';
  }
}
