/**
 * Activity Tray — bottom bar showing all running jobs (Sangam-native).
 *
 * Always one line high; expands to a list. Each job: name, kind, model,
 * elapsed, tokens/cost, Pause/Stop/Open. Global Stop-all. Unread dot.
 */
import { getActiveJobs, getJobs, stopJob, stopAllJobs, markSeen, onJobsChange } from '../../core/jobs.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] tray.js loaded');

let expanded = false;

function fmtElapsed(ms) {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

function render() {
  const tray = document.getElementById('activityTray');
  if (!tray) return;
  const active = getActiveJobs();
  const bar = tray.querySelector('.tray-bar');
  const list = tray.querySelector('.tray-list');

  // Bar: summary
  if (!active.length) {
    bar.innerHTML = `<span class="tray-idle"><i class="fa-solid fa-circle-check"></i> All quiet</span>`;
    tray.classList.toggle('has-active', false);
  } else {
    const needsYou = active.filter((j) => j.status === 'needs-you').length;
    bar.innerHTML = `
      <button class="tray-toggle" aria-expanded="${expanded}">
        <i class="fa-solid fa-chevron-${expanded ? 'down' : 'up'}"></i>
        <span><strong>${active.length}</strong> running${needsYou ? ` · <strong class="tray-needs">${needsYou} need you</strong>` : ''}</span>
        ${active.some((j) => !j.seen) ? '<span class="tray-dot"></span>' : ''}
      </button>
      <button class="tray-stop-all" title="Stop all"><i class="fa-solid fa-stop"></i> Stop all</button>`;
    tray.classList.toggle('has-active', true);
    bar.querySelector('.tray-toggle')?.addEventListener('click', () => {
      expanded = !expanded;
      render();
    });
    bar.querySelector('.tray-stop-all')?.addEventListener('click', (e) => {
      e.stopPropagation();
      stopAllJobs();
    });
  }

  // List: expanded jobs
  if (!expanded) {
    list.classList.add('hidden');
    return;
  }
  list.classList.remove('hidden');
  const jobs = getJobs().slice(0, 20);
  list.innerHTML = jobs.map((j) => `
    <div class="tray-job tray-${j.status}" data-id="${j.id}">
      <span class="tray-kind"><i class="fa-solid ${kindIcon(j.kind)}"></i></span>
      <span class="tray-title">${escapeHtml(j.title)}</span>
      <span class="tray-meta">${escapeHtml(j.model || '')} · ${fmtElapsed((j.endedAt || Date.now()) - j.startedAt)}</span>
      <span class="tray-status">${j.status.replace('-', ' ')}</span>
      ${j.status === 'running' || j.status === 'paused' ? `<button class="icon-btn tray-stop" title="Stop"><i class="fa-solid fa-stop"></i></button>` : ''}
      ${!j.seen ? '<span class="tray-dot"></span>' : ''}
    </div>`).join('') || '<div class="no-results">No jobs yet.</div>';
  list.querySelectorAll('.tray-stop').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      stopJob(btn.closest('.tray-job').dataset.id);
    });
  });
  list.querySelectorAll('.tray-job').forEach((el) => {
    el.addEventListener('click', () => markSeen(el.dataset.id));
  });
}

function kindIcon(kind) {
  return {
    'code-agent': 'fa-code', 'agent': 'fa-robot', 'team': 'fa-users',
    'image': 'fa-image', 'tts': 'fa-volume-high', 'stt': 'fa-microphone',
    'design': 'fa-palette', 'learn': 'fa-graduation-cap',
  }[kind] || 'fa-gear';
}

export function initTray() {
  if (document.getElementById('activityTray')) return;
  const tray = document.createElement('div');
  tray.id = 'activityTray';
  tray.className = 'activity-tray';
  tray.innerHTML = `<div class="tray-bar"></div><div class="tray-list hidden"></div>`;
  document.body.appendChild(tray);
  onJobsChange(render);
  render();
  // Tick elapsed times
  setInterval(() => { if (getActiveJobs().length) render(); }, 5000);
}
