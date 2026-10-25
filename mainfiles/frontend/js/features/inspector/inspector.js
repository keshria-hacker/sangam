/**
 * Inspector — right-side contextual panel (Sangam-native, Phase 2).
 *
 * Shows: current model, context usage, active run details, selected message.
 * Toggle with the inspector button or Ctrl+Shift+I.
 */
import { getSelectedModel } from '../../core/state.js';
import { getActiveJobs } from '../../core/jobs.js';
import { escapeHtml } from '../../shared/utils.js';
import { apiGet } from '../../shared/http.js';
import { showGlobalHttpBanner } from '../settings/http-banner.js';

console.log('[Module] inspector.js loaded');

let visible = false;
let selectedMessage = null;
let lastProvenance = null; // {used_nodes: [...], count} from the latest answer

export function isInspectorVisible() { return visible; }

export function setSelectedMessage(msg) {
  selectedMessage = msg;
  if (visible) render();
}

/** Phase 7: store provenance from the latest answer for the "Used in this answer" panel. */
export function setProvenance(prov) {
  lastProvenance = prov;
  if (visible) render();
}

export function getProvenance() { return lastProvenance; }

export function toggleInspector() {
  visible = !visible;
  const panel = document.getElementById('inspectorPanel');
  panel?.classList.toggle('hidden', !visible);
  panel?.classList.toggle('open', visible);
  if (visible) render();
  document.dispatchEvent(new CustomEvent('sangam:inspector-toggled', { detail: { visible } }));
  if (visible) loadLiveRuns();
}

/** Live runs from the server, shown in the Inspector on open (UX-refine
 *  wave): review evidence without opening the Work tab. Failures render
 *  as a one-line note, never a toast — the Inspector is a side view. */
async function loadLiveRuns() {
  const body = document.getElementById('inspectorBody');
  if (!body) return;
  let section = body.querySelector('[data-insp-live-runs]');
  if (!section) {
    section = document.createElement('section');
    section.className = 'insp-section';
    section.setAttribute('data-insp-live-runs', '');
    body.appendChild(section);
  }
  section.innerHTML = '<h4>Live runs</h4><p class="settings-hint">Loading…</p>';
  try {
    const data = await (await apiGet('/runs/live')).json();
    const runs = data.runs || [];
    section.innerHTML = `<h4>Live runs</h4>` + (runs.length
      ? runs.slice(0, 5).map((r) => `
        <div class="insp-ev-item"><strong>${escapeHtml(r.title || r.kind || 'run')}</strong>
          <span>${escapeHtml(r.state || '')} · ${escapeHtml(r.kind || '')}</span></div>`).join('')
      : '<p class="settings-hint">No live runs right now.</p>') +
      `<button type="button" class="btn-secondary" data-insp-open-runs>Open all runs</button>`;
    section.querySelector('[data-insp-open-runs]')?.addEventListener('click', async () => {
      const { showToolSection } = await import('../tabs/tabs.js');
      showToolSection('work', 'activity');
    });
  } catch {
    section.innerHTML = '<h4>Live runs</h4><p class="settings-hint">Could not load live runs.</p>';
  }
}

function render() {
  const body = document.getElementById('inspectorBody');
  if (!body) return;
  const model = getSelectedModel();
  const jobs = getActiveJobs();

  let html = '';

  // Model section
  if (model) {
    html += `<section class="insp-section">
      <h4>Model</h4>
      <div class="insp-row"><span>Name</span><strong>${escapeHtml(model.name || model.id)}</strong></div>
      <div class="insp-row"><span>Provider</span><strong>${escapeHtml(model.provider || '')}</strong></div>
      ${model.capabilities ? `<div class="insp-row"><span>Capabilities</span><strong>${Object.keys(model.capabilities).filter((k) => model.capabilities[k]).join(', ') || '—'}</strong></div>` : ''}
    </section>`;
  }

  // Active runs
  if (jobs.length) {
    html += `<section class="insp-section"><h4>Active runs (${jobs.length})</h4>` +
      jobs.map((j) => `
        <div class="insp-job">
          <div class="insp-job-title">${escapeHtml(j.title)}</div>
          <div class="insp-row"><span>Status</span><strong>${j.status}</strong></div>
          <div class="insp-row"><span>Elapsed</span><strong>${Math.floor((Date.now() - j.startedAt) / 1000)}s</strong></div>
          ${j.tokens ? `<div class="insp-row"><span>Tokens</span><strong>${j.tokens.toLocaleString()}</strong></div>` : ''}
          ${j.cost ? `<div class="insp-row"><span>Cost</span><strong>$${j.cost.toFixed(4)}</strong></div>` : ''}
        </div>`).join('') + `</section>`;
  }

  // Selected message — evidence lives here, not behind a tab hop.
  // Tool calls, citations, and artifacts are rendered in full: this is
  // the review surface for agent/code work (UX-refine wave). Previously
  // only a 300-char preview was shown, and nothing ever called
  // setSelectedMessage, so the section was dead.
  if (selectedMessage) {
    const m = selectedMessage;
    const toolHtml = (m.tool_calls && m.tool_calls.length)
      ? `<div class="insp-evidence"><h5>Tool calls (${m.tool_calls.length})</h5>` + m.tool_calls.map((t) => `
        <div class="insp-ev-item"><strong>${escapeHtml(t.name || 'tool')}</strong>
          <span>${escapeHtml(t.status || 'done')}</span>
          ${t.result ? `<pre>${escapeHtml(String(t.result).slice(0, 500))}</pre>` : ''}
        </div>`).join('') + `</div>` : '';
    const citeHtml = (m.citations && m.citations.length)
      ? `<div class="insp-evidence"><h5>Sources (${m.citations.length})</h5>` + m.citations.map((c) => `
        <div class="insp-ev-item">${escapeHtml(c.title || 'Source')}
          ${c.url ? `<a href="${escapeHtml(c.url)}" target="_blank" rel="noopener noreferrer">open</a>` : ''}</div>`).join('') + `</div>` : '';
    const artHtml = (m.artifacts && m.artifacts.length)
      ? `<div class="insp-evidence"><h5>Artifacts (${m.artifacts.length})</h5>` + m.artifacts.map((a) => `
        <div class="insp-ev-item"><strong>${escapeHtml(a.title || 'Untitled')}</strong>
          <span>${escapeHtml(a.type || '')}</span></div>`).join('') + `</div>` : '';
    html += `<section class="insp-section"><h4>Message</h4>
      <div class="insp-row"><span>Role</span><strong>${escapeHtml(m.role || '')}</strong></div>
      <div class="insp-row"><span>Model</span><strong>${escapeHtml(m.model || '')}</strong></div>
      ${m.response_time ? `<div class="insp-row"><span>Time</span><strong>${m.response_time}s</strong></div>` : ''}
      ${m.tokens ? `<div class="insp-row"><span>Tokens</span><strong>${m.tokens}</strong></div>` : ''}
      <div class="insp-msg-preview">${escapeHtml((m.content || '').slice(0, 300))}</div>
      ${toolHtml}${citeHtml}${artHtml}
      ${(!toolHtml && !citeHtml && !artHtml) ? '<p class="settings-hint">No tool calls, sources, or artifacts on this message.</p>' : ''}
    </section>`;
  }

  // Phase 7: Used in this answer (provenance)
  if (lastProvenance && lastProvenance.used_nodes && lastProvenance.used_nodes.length) {
    const typeIcon = { document: 'fa-file', memory: 'fa-brain', graph: 'fa-diagram-project' };
    html += `<section class="insp-section"><h4>Used in this answer (${lastProvenance.count})</h4>` +
      lastProvenance.used_nodes.map((n) => `
        <div class="insp-prov">
          <i class="fa-solid ${typeIcon[n.type] || 'fa-circle'}"></i>
          <div class="insp-prov-body">
            <div class="insp-prov-label">${escapeHtml(n.label || n.id)}</div>
            <div class="insp-prov-meta">${escapeHtml(n.type)}${n.reason ? ` — ${escapeHtml(n.reason)}` : ''}</div>
          </div>
        </div>`).join('') + `</section>`;
  }

  if (!html) {
    html = '<p class="settings-hint">Nothing to inspect. Select a message or start a run.</p>';
  }
  body.innerHTML = html;
}

export function initInspector() {
  // App-shell hook (UX-refine wave): the LAN HTTP-fallback warning must
  // render globally, not only inside Settings → Devices. initInspector
  // runs unconditionally in app init; the call is idempotent, so moving
  // it to app.js later is safe. See settings/http-banner.js.
  showGlobalHttpBanner();
  if (document.getElementById('inspectorPanel')) return;
  const panel = document.createElement('aside');
  panel.id = 'inspectorPanel';
  panel.className = 'inspector-panel hidden';
  panel.innerHTML = `
    <div class="inspector-header">
      <h3><i class="fa-solid fa-circle-info"></i> Inspector</h3>
      <button class="icon-btn" id="inspectorClose" aria-label="Close inspector"><i class="fa-solid fa-xmark"></i></button>
    </div>
    <div class="inspector-body" id="inspectorBody"></div>`;
  // The app shell's main element is .main-panel (there is no .app-main
  // in index.html — the old selector silently dropped the panel, so
  // the Inspector could never open and toggleInspector no-opped).
  const main = document.querySelector('.main-panel') || document.body;
  main.appendChild(panel);
  panel.querySelector('#inspectorClose')?.addEventListener('click', toggleInspector);
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'i') {
      e.preventDefault();
      toggleInspector();
    }
  });
  // Refresh on job changes
  document.addEventListener('sangam:jobs-changed', () => { if (visible) render(); });
}
