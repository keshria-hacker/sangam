/**
 * Home view + Doctor (Sangam-native).
 *
 * Home: "continue where you left off" (recent chats + jobs), suggested
 * starts based on enabled features, and setup status (provider check).
 * Doctor: health checks with status pills, fix actions, and a
 * redacted diagnostics export.
 */
import { apiFetch } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
import { getJobs } from '../../core/jobs.js';
import { showTool } from '../tabs/tabs.js';

console.log('[Module] home.js loaded');

// ---------------------------------------------------------------------------
// Home
// ---------------------------------------------------------------------------

const SUGGESTED_STARTS = [
  { id: 'new-chat', tool: null, icon: 'fa-message', title: 'New chat',
    desc: 'Ask anything — a fresh conversation.', feature: null },
  { id: 'code', tool: 'code', icon: 'fa-code', title: 'Code agent',
    desc: 'Build, fix, and refactor code with an agent.', feature: null },
  { id: 'design', tool: 'design', icon: 'fa-palette', title: 'Design studio',
    desc: 'Generate web prototypes with live preview.', feature: null },
  { id: 'images', tool: 'images', icon: 'fa-image', title: 'Image studio',
    desc: 'Create images from text prompts.', feature: 'image_gen' },
  { id: 'teams', tool: 'teams', icon: 'fa-users', title: 'Agent teams',
    desc: 'Run parallel specialist agents on a task.', feature: 'multi_agent' },
  { id: 'learn', tool: 'learn', icon: 'fa-graduation-cap', title: 'Learn',
    desc: 'Interactive lessons with an AI tutor.', feature: 'learning' },
];

function timeAgo(ts) {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function jobStatusIcon(status) {
  return { running: 'fa-circle-play', 'needs-you': 'fa-hand', done: 'fa-circle-check',
           failed: 'fa-circle-exclamation', paused: 'fa-circle-pause' }[status] || 'fa-circle';
}

export async function renderHome(bodyEl) {
  bodyEl.innerHTML = `
    <div class="home-view">
      <div class="home-hero">
        <h2>Home</h2>
        <p class="home-sub">Pick up where you left off, or start something new.</p>
      </div>
      <div id="homeSetup" class="home-setup"></div>
      <section class="home-section">
        <h3><i class="fa-solid fa-clock-rotate-left"></i> Continue where you left off</h3>
        <div id="homeRecent" class="home-recent"><div class="loading">Loading…</div></div>
      </section>
      <section class="home-section">
        <h3><i class="fa-solid fa-wand-magic-sparkles"></i> Suggested starts</h3>
        <div id="homeStarts" class="home-cards"><div class="loading">Loading…</div></div>
      </section>
    </div>`;

  // --- Suggested starts (feature-gated) ---
  let features = {};
  try {
    const data = await (await apiFetch('/features')).json();
    features = (data && data.features) || {};
  } catch { /* offline — show the basics */ }
  const startsEl = bodyEl.querySelector('#homeStarts');
  const visible = SUGGESTED_STARTS.filter((s) => !s.feature || features[s.feature]);
  startsEl.innerHTML = visible.map((s) => `
    <button type="button" class="home-card" data-start="${s.id}">
      <i class="fa-solid ${s.icon}"></i>
      <span class="home-card-title">${escapeHtml(s.title)}</span>
      <span class="home-card-desc">${escapeHtml(s.desc)}</span>
    </button>`).join('');
  startsEl.querySelectorAll('.home-card').forEach((btn) => {
    btn.addEventListener('click', () => {
      const def = SUGGESTED_STARTS.find((s) => s.id === btn.dataset.start);
      if (!def) return;
      if (def.tool) showTool(def.tool);
      else import('../chat/chat.js').then((m) => m.startNewChat()).catch(() => {});
    });
  });

  // --- Recent chats + jobs ---
  const recentEl = bodyEl.querySelector('#homeRecent');
  let chats = [];
  try {
    const data = await (await apiFetch('/chats?limit=3')).json();
    chats = Array.isArray(data) ? data : (data.chats || data.items || []);
  } catch { /* offline */ }
  const jobs = getJobs().slice(0, 3);

  const chatRows = chats.slice(0, 3).map((c) => `
    <button type="button" class="home-row" data-chat="${escapeHtml(String(c.id))}">
      <i class="fa-regular fa-message"></i>
      <span class="home-row-title">${escapeHtml(c.title || 'Untitled chat')}</span>
      <span class="home-row-meta">${c.updated_at ? timeAgo(new Date(c.updated_at).getTime()) : ''}</span>
    </button>`).join('');
  const jobRows = jobs.map((j) => `
    <div class="home-row home-row-static">
      <i class="fa-solid ${jobStatusIcon(j.status)}"></i>
      <span class="home-row-title">${escapeHtml(j.title || j.kind || 'Job')}</span>
      <span class="home-row-meta">${escapeHtml(j.status)} · ${timeAgo(j.startedAt)}</span>
    </div>`).join('');

  recentEl.innerHTML = (chatRows || jobRows)
    ? `${chatRows}${jobRows}`
    : '<p class="home-empty">Nothing yet — start a chat or run an agent above.</p>';
  recentEl.querySelectorAll('[data-chat]').forEach((btn) => {
    btn.addEventListener('click', () => {
      import('../sidebar/sidebar.js')
        .then((m) => m.openChat?.(btn.dataset.chat))
        .catch(() => showToast({ type: 'warning', message: 'Could not open chat.' }));
    });
  });

  // --- Setup status: provider check ---
  const setupEl = bodyEl.querySelector('#homeSetup');
  try {
    const providers = await (await apiFetch('/providers')).json();
    const linked = Array.isArray(providers)
      ? providers.filter((p) => p.state === 'online' || p.state === 'local')
      : [];
    if (!linked.length) {
      setupEl.innerHTML = `
        <div class="home-setup-banner">
          <i class="fa-solid fa-plug-circle-exclamation"></i>
          <div>
            <strong>No provider connected.</strong>
            <span>Link an API key or start Ollama to begin chatting.</span>
          </div>
          <button type="button" class="btn-primary btn-sm" id="homeConnectBtn">Connect a provider</button>
        </div>`;
      setupEl.querySelector('#homeConnectBtn')?.addEventListener('click', () => {
        document.getElementById('settingsBtn')?.click();
      });
    }
  } catch { /* offline — skip setup banner */ }
}

// ---------------------------------------------------------------------------
// Doctor
// ---------------------------------------------------------------------------

function pill(status) {
  const cls = status === 'ok' ? 'ok' : status === 'warn' ? 'warn' : 'fail';
  const label = status === 'ok' ? 'OK' : status === 'warn' ? 'Warning' : 'Failed';
  return `<span class="doc-pill doc-${cls}">${label}</span>`;
}

function copyText(text, label) {
  navigator.clipboard?.writeText(text)
    .then(() => showToast({ type: 'success', message: `${label} copied to clipboard.` }))
    .catch(() => showToast({ type: 'warning', message: 'Copy failed — select the text manually.' }));
}

export async function renderDoctor(bodyEl) {
  bodyEl.innerHTML = `
    <div class="doctor-view">
      <div class="doctor-head">
        <div>
          <h2>Doctor</h2>
          <p class="home-sub">Health checks for your Sangam setup. Each failure has a fix.</p>
        </div>
        <button type="button" class="btn-secondary" id="docCopyDiag">
          <i class="fa-solid fa-clipboard"></i> Copy diagnostics
        </button>
      </div>
      <div id="docChecks" class="doc-checks"><div class="loading">Running checks…</div></div>
    </div>`;

  const checksEl = bodyEl.querySelector('#docChecks');
  const checks = [];
  const errors = [];

  // 1. Backend reachable
  let health = null;
  try {
    health = await (await apiFetch('/health')).json();
    checks.push({ name: 'Backend reachable', status: 'ok',
      detail: `${health.app || 'Sangam'} v${health.version || '?'} · API ${health.api_version || 'v1'}` });
  } catch (err) {
    errors.push(`backend: ${err?.message || err}`);
    checks.push({ name: 'Backend reachable', status: 'fail',
      detail: 'Could not reach the API. Is the backend running?',
      fix: { label: 'Copy start command', cmd: 'cd ~/workspace/projects/sangam && ./start.sh' } });
  }

  // 2. Database (from /health)
  if (health?.database) {
    const ok = health.database === 'connected';
    checks.push({ name: 'Database', status: ok ? 'ok' : 'fail',
      detail: String(health.database),
      fix: ok ? null : { label: 'Copy repair command', cmd: 'cd ~/workspace/projects/sangam && ls mainfiles/history/' } });
  }

  // 3. Providers + keys
  try {
    const providers = await (await apiFetch('/providers')).json();
    const list = Array.isArray(providers) ? providers : [];
    const online = list.filter((p) => p.state === 'online');
    const local = list.filter((p) => p.state === 'local');
    if (online.length || local.length) {
      checks.push({ name: 'Providers', status: 'ok',
        detail: `${online.length} online${local.length ? `, ${local.length} local` : ''}: ${[...online, ...local].map((p) => p.label || p.id).join(', ')}` });
    } else {
      checks.push({ name: 'Providers', status: 'warn',
        detail: 'No providers linked. Chat will not work until you add one.',
        fix: { label: 'Open Settings', settings: true } });
    }
  } catch (err) {
    errors.push(`providers: ${err?.message || err}`);
    checks.push({ name: 'Providers', status: 'fail', detail: 'Could not list providers.' });
  }

  // 4. Ollama (from /health)
  if (health?.ollama) {
    const v = String(health.ollama);
    checks.push({ name: 'Ollama (local models)', status: v === 'connected' ? 'ok' : 'warn',
      detail: v === 'connected' ? 'Connected' : v === 'unreachable' ? 'Not running — local models unavailable.' : v,
      fix: v === 'connected' ? null : { label: 'Copy start command', cmd: 'ollama serve' } });
  } else {
    checks.push({ name: 'Ollama (local models)', status: 'warn',
      detail: 'Not checked — /health did not report Ollama status.',
      fix: { label: 'Copy check command', cmd: 'curl -s http://localhost:11434/api/tags | head -c 200' } });
  }

  // 5. Disk space — cannot check from the browser
  checks.push({ name: 'Disk space', status: 'warn',
    detail: 'Cannot check from the browser. Run the command and confirm /tmp and the project dir have free space.',
    fix: { label: 'Copy check command', cmd: 'df -h /tmp ~/workspace | tail -3' } });

  // 6. Migrations — via /health database check + alembic stamp hint
  checks.push({ name: 'Migrations', status: health?.database === 'connected' ? 'ok' : 'fail',
    detail: health?.database === 'connected'
      ? 'Database connected — schema managed by Alembic.'
      : 'Database unreachable — migrations cannot be verified.',
    fix: health?.database === 'connected' ? null
      : { label: 'Copy check command', cmd: 'cd ~/workspace/projects/sangam/mainfiles && alembic current 2>&1 | tail -2' } });

  checksEl.innerHTML = checks.map((c) => `
    <div class="doc-check">
      <i class="fa-solid ${c.status === 'ok' ? 'fa-circle-check doc-ic-ok' : c.status === 'warn' ? 'fa-triangle-exclamation doc-ic-warn' : 'fa-circle-xmark doc-ic-fail'}"></i>
      <div class="doc-check-body">
        <div class="doc-check-head"><strong>${escapeHtml(c.name)}</strong>${pill(c.status)}</div>
        <p class="doc-check-detail">${escapeHtml(c.detail)}</p>
      </div>
      ${c.fix ? `<button type="button" class="btn-secondary btn-sm doc-fix"
          data-fix-cmd="${escapeHtml(c.fix.cmd || '')}"
          data-fix-settings="${c.fix.settings ? '1' : ''}">${escapeHtml(c.fix.label)}</button>` : ''}
    </div>`).join('');

  checksEl.querySelectorAll('.doc-fix').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (btn.dataset.fixSettings) {
        document.getElementById('settingsBtn')?.click();
      } else if (btn.dataset.fixCmd) {
        copyText(btn.dataset.fixCmd, 'Command');
      }
    });
  });

  // --- Copy diagnostics (redacted) ---
  bodyEl.querySelector('#docCopyDiag')?.addEventListener('click', async () => {
    let features = {};
    try { features = ((await (await apiFetch('/features')).json()).features) || {}; } catch {}
    const diag = {
      app: 'sangam',
      version: health?.version || 'unknown',
      api_version: health?.api_version || 'unknown',
      timestamp: new Date().toISOString(),
      user_agent: navigator.userAgent,
      checks: checks.map((c) => ({ name: c.name, status: c.status, detail: c.detail })),
      features,
      recent_errors: errors,
      note: 'API keys and secrets are never included in diagnostics.',
    };
    const text = JSON.stringify(diag, null, 2);
    // Offer download as well as clipboard
    const blob = new Blob([text], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `sangam-diagnostics-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    copyText(text, 'Diagnostics');
  });
}
