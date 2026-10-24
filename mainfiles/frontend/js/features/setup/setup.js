/**
 * Guided first-run setup — Batch 1 UX consolidation.
 *
 * Shown inside Chat (never a separate wizard page) when no provider is
 * ready: one screen, three honest paths — cloud key (pasted key, tested
 * inline), local Ollama (reachability + model check), or "look around
 * first" (skip path for power users, with a dismissible banner instead of
 * a dead chat box). Completion is per-device localStorage, not a server
 * setting: the settings schema rejects unknown keys, and first-run state
 * is about this browser, not the account.
 *
 * The "demo" path is deliberately NOT a fake model: a mock provider only
 * exists when the server is started with it (smoke tests), and pretending
 * otherwise would be the same lie the old onboarding card told. The tour
 * path says plainly that chat needs a provider to answer.
 */
import { apiFetch } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { showToolSection } from '../tabs/tabs.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] setup.js loaded');

const DONE_KEY = 'sangam:setup-done';
const DISMISSED_KEY = 'sangam:setup-dismissed';

async function providerReady() {
  try {
    const providers = await (await apiFetch('/providers')).json();
    if (Array.isArray(providers)) {
      return providers.some((p) => p.state === 'online' || p.state === 'local');
    }
  } catch { /* offline: setup cannot verify, so it shows */ }
  return false;
}

function removeSetup() {
  document.getElementById('firstRunSetup')?.remove();
  document.getElementById('setupBanner')?.remove();
}

function markDone() {
  try { localStorage.setItem(DONE_KEY, '1'); } catch {}
  removeSetup();
}

function showBanner() {
  const chatView = document.getElementById('chatView');
  if (!chatView || document.getElementById('setupBanner')) return;
  const banner = document.createElement('div');
  banner.id = 'setupBanner';
  banner.className = 'setup-banner';
  banner.innerHTML = `<span>No model connected yet — chat can't answer until a provider is linked.</span>
    <button type="button" class="btn-primary btn-sm" id="setupBannerBtn">Connect a provider</button>
    <button type="button" class="icon-btn" id="setupBannerDismiss" aria-label="Dismiss setup banner"><i class="fa-solid fa-xmark"></i></button>`;
  chatView.prepend(banner);
  banner.querySelector('#setupBannerBtn').addEventListener('click', () => {
    showToolSection('settings', 'models');
  });
  banner.querySelector('#setupBannerDismiss').addEventListener('click', () => banner.remove());
}

export async function maybeShowFirstRunSetup() {
  try {
    if (localStorage.getItem(DONE_KEY) || localStorage.getItem(DISMISSED_KEY)) {
      if (localStorage.getItem(DISMISSED_KEY) && !(await providerReady())) showBanner();
      return;
    }
  } catch { return; }
  if (await providerReady()) { markDone(); return; }
  const chatView = document.getElementById('chatView');
  if (!chatView || document.getElementById('firstRunSetup')) return;

  let providerOptions = [];
  try {
    const keys = await (await apiFetch('/settings/providers')).json();
    if (Array.isArray(keys)) providerOptions = keys;
  } catch { /* fall back to the known provider list */ }
  if (!providerOptions.length) {
    providerOptions = ['openai', 'anthropic', 'gemini', 'deepseek', 'groq', 'mistral', 'openrouter', 'together', 'nvidia'].map((pid) => ({ provider_id: pid, label: pid }));
  }

  const panel = document.createElement('div');
  panel.id = 'firstRunSetup';
  panel.className = 'setup-panel';
  panel.innerHTML = `
    <h2>Let's get your first answer</h2>
    <p class="settings-hint">Sangam is your private AI workspace. Pick one path — this takes under two minutes.</p>
    <div class="setup-cards">
      <section class="setup-card">
        <h3>Use a cloud provider</h3>
        <p class="settings-hint">Paste one API key. Sangam tests it before you continue.</p>
        <select id="setupProvider" class="provider-key-input" aria-label="Provider">
          ${providerOptions.map((k) => `<option value="${escapeHtml(k.provider_id)}">${escapeHtml(k.label || k.provider_id)}</option>`).join('')}
        </select>
        <input type="password" id="setupKey" class="provider-key-input" placeholder="Paste API key…" aria-label="API key" style="margin-top:8px;width:100%">
        <button type="button" class="btn-primary" id="setupSaveKey" style="margin-top:8px">Save key &amp; test it</button>
        <p class="settings-hint" id="setupKeyStatus"></p>
      </section>
      <section class="setup-card">
        <h3>Use a free local model</h3>
        <p class="settings-hint">If Ollama is running on this machine with a downloaded model, Sangam uses it — no key, no cloud.</p>
        <button type="button" class="btn-secondary" id="setupOllama">Check Ollama</button>
        <p class="settings-hint" id="setupOllamaStatus"></p>
      </section>
      <section class="setup-card">
        <h3>Look around first</h3>
        <p class="settings-hint">Explore the app now. Chat won't answer until a provider is connected — the banner at the top will remind you.</p>
        <button type="button" class="btn-secondary" id="setupSkip">I'll configure later</button>
      </section>
    </div>`;
  chatView.prepend(panel);

  panel.querySelector('#setupSaveKey').addEventListener('click', async () => {
    const pid = panel.querySelector('#setupProvider').value;
    const key = panel.querySelector('#setupKey').value.trim();
    const status = panel.querySelector('#setupKeyStatus');
    if (!key) { status.textContent = 'Paste a key first.'; return; }
    status.textContent = 'Saving and testing…';
    try {
      const save = await apiFetch(`/settings/providers/${encodeURIComponent(pid)}/key`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: key }),
      });
      if (!save.ok) throw new Error((await save.json().catch(() => ({}))).detail || `Save failed (${save.status})`);
      const test = await apiFetch(`/settings/providers/${encodeURIComponent(pid)}/models/refresh`);
      if (!test.ok) throw new Error('The key was saved but the provider rejected it — check for a missing character.');
      showToast({ type: 'success', title: 'Provider connected', message: 'You can start chatting.' });
      markDone();
    } catch (err) {
      status.textContent = err?.message || String(err);
    }
  });

  panel.querySelector('#setupOllama').addEventListener('click', async () => {
    const status = panel.querySelector('#setupOllamaStatus');
    status.textContent = 'Checking…';
    try {
      const res = await apiFetch('/models/ollama');
      const data = await res.json().catch(() => ({}));
      const models = data.models || data || [];
      if (res.ok && Array.isArray(models) && models.length) {
        showToast({ type: 'success', title: 'Ollama ready', message: `${models.length} local model(s) found.` });
        markDone();
      } else if (res.ok) {
        status.textContent = 'Ollama is reachable but has no models yet. Pull one (e.g. ollama pull llama3.1), then check again.';
      } else {
        status.textContent = 'Ollama is not reachable on this machine. Start it with `ollama serve` and download a model, or use a cloud key instead.';
      }
    } catch {
      status.textContent = 'Ollama is not reachable on this machine. Start it with `ollama serve` and download a model, or use a cloud key instead.';
    }
  });

  panel.querySelector('#setupSkip').addEventListener('click', () => {
    try { localStorage.setItem(DISMISSED_KEY, '1'); } catch {}
    removeSetup();
    showBanner();
  });
}
