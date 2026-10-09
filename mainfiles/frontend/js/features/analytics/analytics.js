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
  // Navigation via studio rail (core/nav.js) — no per-button wiring needed.
  let enabled = false;
  try {
    const data = await (await apiFetch('/features')).json();
    enabled = !!(data && data.features && data.features.analytics);
  } catch {
    enabled = false;
  }
  if (!enabled) return false;
  btn?.classList.remove('hidden');
  return true;
}

/**
 * Render the Analytics dashboard into a tab body (replaces the old modal).
 */
export function renderAnalyticsTab(bodyEl) {
  bodyEl.innerHTML = `
    <div class="analytics-tab">
      <div class="analytics-controls">
        <span class="analytics-note">Private — stored only on this server, never shared.</span>
        <select id="analyticsDays" class="provider-key-input" aria-label="Days">
          <option value="7">Last 7 days</option>
          <option value="14" selected>Last 14 days</option>
          <option value="30">Last 30 days</option>
        </select>
      </div>
      <div id="analyticsContent"><div class="loading">Loading…</div></div>
    </div>`;
  bodyEl.querySelector('#analyticsDays').addEventListener('change', () => loadStats(bodyEl));
  loadStats(bodyEl);
}

// Back-compat: old modal entry point now opens the tab
export function openAnalyticsModal() {
  import('../tabs/tabs.js').then(({ openToolTab }) => openToolTab('analytics'));
}

async function loadStats(container) {
  const root = container || document.getElementById('toolViewBody') || document;
  const content = root.querySelector('#analyticsContent');
  const days = root.querySelector('#analyticsDays').value;
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
      </div>
      <div id="arenaSection"><h4>Arena leaderboard</h4><div class="loading">Loading…</div></div>`;
    loadArena(root);
  } catch (err) {
    content.innerHTML = `<p class="analytics-empty">Could not load stats: ${escapeHtml(err?.message || String(err))}</p>`;
  }
}

async function loadArena(root) {
  const section = root.querySelector('#arenaSection');
  if (!section) return;
  try {
    const data = await (await apiFetch('/arena/leaderboard')).json();
    const board = data.leaderboard || [];
    if (!board.length) {
      section.innerHTML = '<h4>Arena leaderboard</h4><p class="analytics-empty">No Arena votes yet. Use Compare to vote.</p>';
      return;
    }
    section.innerHTML = `<h4>Arena leaderboard</h4>
      <table class="cmp-lb">
        <thead><tr><th>Model</th><th>Wins</th><th>Losses</th><th>Win rate</th></tr></thead>
        <tbody>${board.map((r) => `
          <tr><td>${escapeHtml(r.model)}</td><td>${r.wins}</td><td>${r.losses}</td>
          <td>${(r.win_rate * 100).toFixed(1)}%</td></tr>`).join('')}
        </tbody>
      </table>
      <p class="cmp-muted">${data.total_votes} votes total</p>`;
  } catch {
    section.innerHTML = '<h4>Arena leaderboard</h4><p class="analytics-empty">Could not load.</p>';
  }
}
