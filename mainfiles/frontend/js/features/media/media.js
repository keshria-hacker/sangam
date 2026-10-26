/**
 * Media tab — Phase 4 (all-in-one plan): media work as observable jobs.
 *
 * Create a job (transcribe / TTS / dub / image), then poll it from the
 * list below. Results render natively: transcript text, an audio
 * player for TTS/dub output, or generated images. Voice cloning is
 * not offered here — it was proposed as consent-gated and the user
 * has not confirmed it.
 */
import { apiFetch } from '../../shared/http.js';
import { escapeHtml } from '../../shared/utils.js';
import { showToast } from '../../shared/toast.js';
import { showToolSection } from '../tabs/tabs.js';

console.log('[Module] media.js loaded');

export async function renderMediaTab(bodyEl) {
  bodyEl.innerHTML = `
    <div class="library">
      <h2>Media jobs</h2>
      <p class="settings-hint">Long media work runs as a background job: create it, watch it in this list and in the Runs centre, and collect the result when it finishes.</p>
      <section>
        <h3>Create media job</h3>
        <div class="kn-mem-controls">
          <select id="mjKind" class="provider-key-input" aria-label="Media job kind">
            <option value="tts">Text to speech</option>
            <option value="dub">Voice a script (subtitles are in Studio)</option>
            <option value="transcribe">Transcribe audio</option>
            <option value="image">Generate image</option>
          </select>
          <input type="text" id="mjText" class="provider-key-input" placeholder="Text, prompt, or audio media id…" aria-label="Media job input" style="flex:1">
          <button class="btn-secondary" id="mjCreateBtn">Create job</button>
        </div>
        <div id="mjCreateStatus" class="settings-hint"></div>
      </section>
      <section>
        <h3>Jobs</h3>
        <p class="settings-hint"><button class="btn-secondary btn-sm" type="button" id="mjActivityLink">Track all jobs in Work → Activity</button> Creation stays here; tracking lives in Activity.</p>
        <div id="mjList" class="kn-mem-list"></div>
      </section>
    </div>`;

  bodyEl.querySelector('#mjActivityLink').addEventListener('click', () => {
    showToolSection('work', 'activity');
  });

  bodyEl.querySelector('#mjCreateBtn').addEventListener('click', async () => {
    const kind = bodyEl.querySelector('#mjKind').value;
    const text = bodyEl.querySelector('#mjText').value.trim();
    const status = bodyEl.querySelector('#mjCreateStatus');
    const payload = { kind };
    if (kind === 'transcribe') payload.media_id = text;
    else if (kind === 'image') payload.prompt = text;
    else payload.text = text;
    try {
      const res = await apiFetch('/media-jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      status.textContent = `Job ${data.id} created (${data.status}).`;
      showToast({ type: 'success', title: 'Media job created' });
      loadJobs(bodyEl);
    } catch (err) {
      status.textContent = `Create failed: ${err?.message || String(err)}`;
    }
  });

  loadJobs(bodyEl);
}

async function loadJobs(bodyEl) {
  const box = bodyEl.querySelector('#mjList');
  box.innerHTML = '<p class="settings-hint">Loading…</p>';
  try {
    const data = await (await apiFetch('/media-jobs')).json();
    const jobs = data.jobs || [];
    if (!jobs.length) {
      box.innerHTML = '<p class="settings-hint">No media jobs yet.</p>';
      return;
    }
    box.innerHTML = jobs.map((j) => {
      const r = j.result || {};
      let resultHtml = '';
      if (j.status === 'succeeded' && r.text) resultHtml = `<br>${escapeHtml(r.text.slice(0, 300))}`;
      if (j.status === 'succeeded' && r.url) resultHtml = `<br><audio controls src="${escapeHtml(r.url)}"></audio>`;
      if (j.status === 'succeeded' && r.images) resultHtml = r.images.map((im) => `<br><img src="${escapeHtml(im.url || '')}" alt="Generated image" style="max-width:240px">`).join('');
      if (j.status === 'failed' && j.error) resultHtml = `<br>Error: ${escapeHtml(j.error.slice(0, 200))}`;
      return `<div class="kn-mem"><span class="kn-mem-content"><strong>${escapeHtml(j.kind)}</strong> · ${escapeHtml(j.status)}${resultHtml}</span>
        <button class="btn-secondary mj-refresh-btn">Refresh</button></div>`;
    }).join('');
    box.querySelectorAll('.mj-refresh-btn').forEach((btn) => {
      btn.addEventListener('click', () => loadJobs(bodyEl));
    });
  } catch {
    box.innerHTML = '<p class="settings-hint">Could not load media jobs.</p>';
  }
}
