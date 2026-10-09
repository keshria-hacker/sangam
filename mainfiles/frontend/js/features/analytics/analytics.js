/**
 * Analytics dashboard UI — private, local-first usage stats (openpanel-style).
 *
 * Shown only when the backend `analytics` feature flag is on. All data is
 * per-user aggregates; raw events never leave the backend.
 */

import { apiFetch } from '../../shared/http.js';
import { escapeHtml } from '../../shared/utils.js';
console.log('[Module] analytics.js loaded');

export async function initAnalytics() {
  let enabled = false;
  try {
    const data = await (await apiFetch('/features')).json();
    enabled = !!(data && data.features && data.features.analytics);
  } catch {
    enabled = false;
  }
  if (!enabled) return false;
  const btn = document.getElementById('analyticsBtn');
  if (btn) {
    btn.classList.remove('hidden');
    btn.addEventListener('click', openAnalyticsModal);
  }
  return true;
}

function ensureModal() {
  let overlay = document.getElementById('analyticsOverlay');
  if (overlay) return overlay;
  overlay = document.createElement('div');
  overlay.id = 'analyticsOverlay';
  overlay.className = 'modal-overlay hidden';
  overlay.innerHTML = `
    <div class="modal analytics-modal" role="dialog" aria-modal="true" aria-labelledby="analyticsModalTitle">
      <div class="modal-header">
        <h2 id="analyticsModalTitle"><i class="fa-solid fa-chart-simple"></i> Usage</h2>
        <button class="icon-btn ghost" id="closeAnalytics" aria-label="Close analytics"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div class="analytics-body">
        <div class="analytics-controls">
          <span class="analytics-note">Private — stored only on this server, never shared.</span>
          <select id="analyticsDays" class="provider-key-input" aria-label="Days">
            <option value="7">Last 7 days</option>
            <option value="14" selected>Last 14 days</option>
            <option value="30">Last 30 days</option>
          </select>
        </div>
        <div id="analyticsContent"><div class="loading">Loading…</div></div>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('#closeAnalytics').addEventListener('click', () => overlay.classList.add('hidden'));
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.classList.add('hidden'); });
  overlay.querySelector('#analyticsDays').addEventListener('change', loadStats);
  return overlay;
}

export function openAnalyticsModal() {
  const overlay = ensureModal();
  overlay.classList.remove('hidden');
  loadStats();
}

async function loadStats() {
  const overlay = document.getElementById('analyticsOverlay');
  const content = overlay.querySelector('#analyticsContent');
  const days = overlay.querySelector('#analyticsDays').value;
  content.innerHTML = '<div class="loading">Loading…</div>';
  try {
    const stats = await (await apiFetch(`/analytics/stats?days=${encodeURIComponent(days)}`)).json();
    if (!stats.enabled) {
      content.innerHTML = '<p class="analytics-empty">Analytics are disabled.</p>';
      return;
    }
    const maxDay = Math.max(1, ...stats.per_day.map((d) => d.count));
    const bars = stats.per_day.map((d) => `
      <div class="abar-row">
        <span class="abar-label">${escapeHtml(d.day.slice(5))}</span>
        <div class="abar-track"><div class="abar-fill" style="width:${Math.round((d.count / maxDay) * 100)}%"></div></div>
        <span class="abar-count">${d.count}</span>
      </div>`).join('');
    const types = (stats.by_type || []).map((t) => `
      <div class="astat-row"><span>${escapeHtml(t.type.replace(/_/g, ' '))}</span><strong>${t.count}</strong></div>`).join('');
    const models = (stats.top_models || []).map((m) => `
      <div class="astat-row"><span>${escapeHtml(m.model)}</span><strong>${m.count}</strong></div>`).join('');
    content.innerHTML = `
      <div class="astat-total"><strong>${stats.total_events}</strong><span>events in ${stats.days} days</span></div>
      <h4>Activity</h4>
      <div class="abar-chart">${bars || '<p class="analytics-empty">No activity yet.</p>'}</div>
      <div class="analytics-cols">
        <div><h4>By type</h4>${types || '<p class="analytics-empty">—</p>'}</div>
        <div><h4>Top models</h4>${models || '<p class="analytics-empty">—</p>'}</div>
      </div>`;
  } catch (err) {
    content.innerHTML = `<p class="analytics-empty">Could not load stats: ${escapeHtml(err?.message || String(err))}</p>`;
  }
}
