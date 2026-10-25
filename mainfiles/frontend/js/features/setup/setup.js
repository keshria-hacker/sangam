/**
 * Guided first-run setup — Batch 1 UX consolidation, stepped in the
 * UX-refine wave.
 *
 * Shown inside Chat (never a separate wizard page) when no provider is
 * ready. The old layout showed three cards at once — three competing
 * "next actions" plus a form — which is exactly the confusion the UX
 * work targets. The stepped version shows exactly one obvious next
 * action per step, with visible progress:
 *
 *   Step 1 of 3 — pick ONE path (cloud key / local Ollama / look around)
 *   Step 2 of 3 — only that path's single action (save+test a key,
 *                  list + test Ollama models, or a labelled sample)
 *   Step 3 of 3 — one guided first prompt: "What do you want to get
 *                  done today?" -> Auto answers (or, on the look-around
 *                  path, an honest "connect a provider first" note).
 *
 * The skip path for power users is kept on both steps ("I'll configure
 * later" → dismissible banner, never a dead chat box). Completion is
 * per-device localStorage, not a server setting: the settings schema
 * rejects unknown keys, and first-run state is about this browser, not
 * the account.
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

function skipSetup() {
  try { localStorage.setItem(DISMISSED_KEY, '1'); } catch {}
  removeSetup();
  showBanner();
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
    <div class="setup-progress" role="progressbar" aria-valuemin="1" aria-valuemax="3" aria-valuenow="1" aria-label="Setup progress">
      <div class="setup-progress-bar" id="setupProgressBar" style="width:33%"></div>
    </div>
    <p class="setup-step-label" id="setupStepLabel">Step 1 of 3 — choose how to connect</p>
    <h2>Let's get your first answer</h2>
    <p class="settings-hint">Sangam is your private AI workspace. This takes under two minutes.</p>
    <div id="setupStepBody"></div>
    <button type="button" class="btn-secondary setup-skip" id="setupSkipLink">I'll configure later</button>`;
  chatView.prepend(panel);

  const body = panel.querySelector('#setupStepBody');
  const label = panel.querySelector('#setupStepLabel');
  const bar = panel.querySelector('#setupProgressBar');
  panel.querySelector('#setupSkipLink').addEventListener('click', skipSetup);

  function setStep(step, labelText) {
    label.textContent = labelText;
    bar.style.width = step === 1 ? '33%' : step === 2 ? '66%' : '100%';
    panel.querySelector('.setup-progress').setAttribute('aria-valuenow', String(step));
  }

  // Step 3 of 3 — the one guided first prompt. On a connected path it
  // sends through the normal composer (Auto mode decides the rest);
  // on the look-around path there is no provider, so it says so and
  // offers the way back to connecting instead of faking an answer.
  function renderStep3(path, suggestedModel) {
    setStep(3, 'Step 3 of 3 — your first prompt');
    if (path === 'tour') {
      body.innerHTML = `
        <h3>What do you want to get done today?</h3>
        <p class="settings-hint">That is the question to start with once a provider is connected. Right now chat cannot answer — the banner at the top will remind you — so this step ends at connecting, not at a fake reply.</p>
        <div class="setup-step-actions">
          ${backButton()}
          <button type="button" class="btn-primary" id="setupConnect">Connect a provider</button>
        </div>`;
      body.querySelector('#setupBack').addEventListener('click', renderStep1);
      body.querySelector('#setupConnect').addEventListener('click', renderStep1);
      return;
    }
    body.innerHTML = `
      <h3>What do you want to get done today?</h3>
      ${suggestedModel ? `<p class="settings-hint">✓ Connected — suggested model: ${escapeHtml(suggestedModel)}.</p>` : ''}
      <p class="settings-hint">Type one thing you want done. Auto answers — no settings needed.</p>
      <input type="text" id="setupFirstPrompt" class="provider-key-input" placeholder="What do you want to get done today?" aria-label="What do you want to get done today?" style="width:100%">
      <div class="setup-step-actions">
        ${backButton()}
        <button type="button" class="btn-primary" id="setupAsk">Ask Sangam</button>
      </div>
      <p class="settings-hint" id="setupAskStatus"></p>`;
    body.querySelector('#setupBack').addEventListener('click', renderStep1);
    body.querySelector('#setupAsk').addEventListener('click', async () => {
      const input = body.querySelector('#setupFirstPrompt');
      const text = input.value.trim();
      if (!text) {
        body.querySelector('#setupAskStatus').textContent = 'Type what you want to get done first.';
        input.focus();
        return;
      }
      const ta = document.getElementById('messageInput');
      if (!ta) { markDone(); return; }
      ta.value = text;
      markDone();
      try {
        const { handleSend } = await import('../chat/chat.js');
        await handleSend();
      } catch (err) {
        showToast({ type: 'info', title: 'Prompt ready in the composer', message: 'Press Send when you are ready.' });
      }
    });
  }

  // After a provider connects, refresh the model list and pre-select
  // the suggested model so step 3's Ask actually sends. Returns the
  // suggested model name (or '' when nothing could be selected).
  async function refreshAndSelectModel(matchProvider) {
    try {
      const modelsMod = await import('../models/models.js');
      await modelsMod.loadProvidersAndModels();
      const { getModels } = await import('../../core/state.js');
      const models = getModels() || [];
      const match = models.find((m) => m.provider === matchProvider || m.provider_id === matchProvider)
        || models.find((m) => String(m.id || '').toLowerCase().includes(String(matchProvider || '').toLowerCase()))
        || models[0];
      if (match) {
        try { modelsMod.selectModel(match, { silent: true }); } catch {}
        return match.name || match.id || '';
      }
    } catch { /* selection is best-effort; step 3 still works via the picker */ }
    return '';
  }

  function backButton() {
    return `<button type="button" class="btn-secondary setup-back" id="setupBack">← Back</button>`;
  }

  // --- Step 1: one choice, three buttons, each the only action on it.
  function renderStep1() {
    setStep(1, 'Step 1 of 3 — choose how to connect');
    body.innerHTML = `
      <div class="setup-paths">
        <button type="button" class="btn-primary setup-path" data-path="cloud">Use a cloud provider</button>
        <button type="button" class="btn-secondary setup-path" data-path="ollama">Use a free local model</button>
        <button type="button" class="btn-secondary setup-path" data-path="tour">Look around first</button>
      </div>
      <p class="settings-hint">Cloud needs one API key. Local needs Ollama running with a downloaded model. Looking around needs nothing — but chat won't answer until a provider is connected.</p>`;
    body.querySelectorAll('[data-path]').forEach((btn) => {
      btn.addEventListener('click', () => renderStep2(btn.dataset.path));
    });
  }

  // --- Step 2: only the chosen path's single action.
  function renderStep2(path) {
    setStep(2, `Step 2 of 3 — ${path === 'cloud' ? 'paste one API key' : path === 'ollama' ? 'check Ollama' : 'start exploring'}`);
    if (path === 'cloud') {
      body.innerHTML = `
        <p class="settings-hint">Paste one API key. Sangam tests it before you continue.</p>
        <select id="setupProvider" class="provider-key-input" aria-label="Provider">
          ${providerOptions.map((k) => `<option value="${escapeHtml(k.provider_id)}">${escapeHtml(k.label || k.provider_id)}</option>`).join('')}
        </select>
        <input type="password" id="setupKey" class="provider-key-input" placeholder="Paste API key…" aria-label="API key" style="margin-top:8px;width:100%">
        <div class="setup-step-actions">
          ${backButton()}
          <button type="button" class="btn-primary" id="setupSaveKey">Save key &amp; test it</button>
        </div>
        <p class="settings-hint" id="setupKeyStatus"></p>`;
      body.querySelector('#setupBack').addEventListener('click', renderStep1);
      body.querySelector('#setupSaveKey').addEventListener('click', async () => {
        const pid = body.querySelector('#setupProvider').value;
        const key = body.querySelector('#setupKey').value.trim();
        const status = body.querySelector('#setupKeyStatus');
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
          status.innerHTML = '✓ <strong>Provider connected.</strong> Finding a suggested model…';
          const suggested = await refreshAndSelectModel(pid);
          showToast({ type: 'success', title: 'Provider connected', message: suggested ? `Suggested model: ${suggested}` : 'You can start chatting.' });
          renderStep3('cloud', suggested);
        } catch (err) {
          status.textContent = err?.message || String(err);
        }
      });
    } else if (path === 'ollama') {
      body.innerHTML = `
        <p class="settings-hint">If Ollama is running on this machine with a downloaded model, Sangam uses it — no key, no cloud.</p>
        <div class="setup-step-actions">
          ${backButton()}
          <button type="button" class="btn-primary" id="setupOllama">Check Ollama</button>
        </div>
        <p class="settings-hint" id="setupOllamaStatus"></p>`;
      body.querySelector('#setupBack').addEventListener('click', renderStep1);
      body.querySelector('#setupOllama').addEventListener('click', async () => {
        const status = body.querySelector('#setupOllamaStatus');
        status.textContent = 'Checking…';
        try {
          const res = await apiFetch('/models/ollama');
          const data = await res.json().catch(() => ({}));
          const models = data.models || data || [];
          if (res.ok && Array.isArray(models) && models.length) {
            const names = models.map((m) => (typeof m === 'string' ? m : (m.id || m.name))).filter(Boolean);
            status.innerHTML = `✓ <strong>Ollama ready.</strong> ${names.length} local model(s) found: ${escapeHtml(names.slice(0, 5).join(', '))}${names.length > 5 ? '…' : ''} — using ${escapeHtml(names[0])} first.`;
            showToast({ type: 'success', title: 'Ollama ready', message: `${names.length} local model(s) found.` });
            const suggested = await refreshAndSelectModel('ollama');
            renderStep3('ollama', suggested || names[0]);
          } else if (res.ok) {
            status.textContent = 'Ollama is reachable but has no models yet. Pull one (e.g. ollama pull llama3.1), then check again.';
          } else {
            status.textContent = 'Ollama is not reachable on this machine. Start it with `ollama serve` and download a model, or use a cloud key instead.';
          }
        } catch {
          status.textContent = 'Ollama is not reachable on this machine. Start it with `ollama serve` and download a model, or use a cloud key instead.';
        }
      });
    } else {
      body.innerHTML = `
        <p class="settings-hint">Explore the app now. Chat won't answer until a provider is connected — the banner at the top will remind you.</p>
        <div class="setup-sample" role="note" aria-label="Labelled sample, not a model response">
          <p><strong>SAMPLE — not a real model response.</strong> This is what an answer looks like, so you can judge the layout before connecting anything.</p>
          <p><em>You:</em> What is Sangam?</p>
          <p><em>Sample answer:</em> Sangam is your private AI workspace — one interface for every model, with projects, artifacts, knowledge, and agents in one place.</p>
        </div>
        <div class="setup-step-actions">
          ${backButton()}
          <button type="button" class="btn-primary" id="setupTour">Continue</button>
        </div>`;
      body.querySelector('#setupBack').addEventListener('click', renderStep1);
      body.querySelector('#setupTour').addEventListener('click', () => renderStep3('tour', ''));
    }
  }

  renderStep1();
}
