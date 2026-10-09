/**
 * Inspector — right-side contextual panel (Sangam-native, Phase 2).
 *
 * Shows: current model, context usage, active run details, selected message.
 * Toggle with the inspector button or Ctrl+Shift+I.
 */
import { getSelectedModel } from '../../core/state.js';
import { getActiveJobs } from '../../core/jobs.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] inspector.js loaded');

let visible = false;
let selectedMessage = null;

export function isInspectorVisible() { return visible; }

export function setSelectedMessage(msg) {
  selectedMessage = msg;
  if (visible) render();
}

export function toggleInspector() {
  visible = !visible;
  const panel = document.getElementById('inspectorPanel');
  panel?.classList.toggle('hidden', !visible);
  panel?.classList.toggle('open', visible);
  if (visible) render();
  document.dispatchEvent(new CustomEvent('sangam:inspector-toggled', { detail: { visible } }));
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

  // Selected message
  if (selectedMessage) {
    const m = selectedMessage;
    html += `<section class="insp-section"><h4>Message</h4>
      <div class="insp-row"><span>Role</span><strong>${escapeHtml(m.role || '')}</strong></div>
      <div class="insp-row"><span>Model</span><strong>${escapeHtml(m.model || '')}</strong></div>
      ${m.response_time ? `<div class="insp-row"><span>Time</span><strong>${m.response_time}s</strong></div>` : ''}
      ${m.tokens ? `<div class="insp-row"><span>Tokens</span><strong>${m.tokens}</strong></div>` : ''}
      <div class="insp-msg-preview">${escapeHtml((m.content || '').slice(0, 300))}</div>
    </section>`;
  }

  if (!html) {
    html = '<p class="settings-hint">Nothing to inspect. Select a message or start a run.</p>';
  }
  body.innerHTML = html;
}

export function initInspector() {
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
  document.querySelector('.app-main')?.appendChild(panel);
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
