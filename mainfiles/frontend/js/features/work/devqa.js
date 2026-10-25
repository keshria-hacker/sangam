/**
 * Dev / QA section inside Work (Batch 12) — one panel for the combined
 * surfaces, not one button per repo:
 *  - workflow starter templates + node catalogue (langflow/dify depth)
 *  - writing lint, now with a/an, double-comparative and typo rules
 *    (harper depth, same /quality/lint route — suggest only, never rewrite)
 *  - security scope check + checklist + excluded-category guard
 *  - service health + notification inbox (platform depth)
 *  - prompt templates + chat folders + model presets (chat parity)
 *
 * Every panel has a plain-language empty state. Nothing here launches a
 * VM, installs a tool, runs a Windows tweak, or starts an autonomous
 * security run — those are documented in the backend as excluded or
 * approval-gated, and this UI does not offer them.
 */
import { apiFetch } from '../../shared/http.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] devqa.js loaded');

const EMPTY = (text) => `<p class="settings-hint">${escapeHtml(text)}</p>`;

export async function renderDevQaPage(bodyEl) {
  bodyEl.innerHTML = `
    <div class="library">
      <h2>Dev &amp; QA</h2>
      <p class="settings-hint">Starter workflow templates, writing checks, guarded security
      helpers, service health, and chat organisation — all in one place.</p>
      <section>
        <h3>Workflow starters</h3>
        <p class="settings-hint">Pick a starter graph, then create it as a workflow in the
        Workflows section. Starter graphs use only real node types.</p>
        <div id="dqTemplates" class="kn-mem-list">${EMPTY('Loading starter templates…')}</div>
      </section>
      <section>
        <h3>Writing check</h3>
        <p class="settings-hint">Paste text to check it. Suggestions only — nothing is rewritten for you.</p>
        <textarea id="dqLintText" class="provider-key-input" rows="4" style="width:100%" aria-label="Text to check"></textarea>
        <button class="btn-secondary" id="dqLintBtn" style="margin-top:8px">Check writing</button>
        <div id="dqLintOut" class="kn-mem-list">${EMPTY('No text checked yet.')}</div>
      </section>
      <section>
        <h3>Security scope check</h3>
        <p class="settings-hint">Security tools only ever run against systems you own, with
        per-run approval. Check a target against a scope file first.</p>
        <div class="kn-mem-controls">
          <input type="text" id="dqScopeTarget" class="provider-key-input" placeholder="Target host, e.g. example.com" aria-label="Target host" style="flex:1">
          <input type="text" id="dqScopeDomains" class="provider-key-input" placeholder="In-scope domains, comma-separated" aria-label="In-scope domains" style="flex:1">
          <button class="btn-secondary" id="dqScopeBtn">Check scope</button>
        </div>
        <div id="dqScopeOut" class="kn-mem-list">${EMPTY('No scope checked yet.')}</div>
      </section>
      <section>
        <h3>Service health</h3>
        <p class="settings-hint">Register a local service URL you run, then probe it. Uptime
        comes only from probes actually recorded — no history means unknown, not 100%.</p>
        <div class="kn-mem-controls">
          <input type="text" id="dqSvcName" class="provider-key-input" placeholder="Service name" aria-label="Service name" style="flex:1">
          <input type="text" id="dqSvcUrl" class="provider-key-input" placeholder="https://localhost:PORT/health" aria-label="Service URL" style="flex:1">
          <button class="btn-secondary" id="dqSvcBtn">Register</button>
        </div>
        <div id="dqSvcOut" class="kn-mem-list">${EMPTY('No services registered yet.')}</div>
      </section>
      <section>
        <h3>Notifications</h3>
        <div id="dqNotifOut" class="kn-mem-list">${EMPTY('No notifications yet.')}</div>
      </section>
      <section>
        <h3>Chat organisation</h3>
        <p class="settings-hint">Prompt templates to reuse, folders to group chats, and
        shareable model presets (settings only — never keys or history).</p>
        <div id="dqChatOut" class="kn-mem-list">${EMPTY('Loading chat organisation…')}</div>
      </section>
    </div>`;

  const get = async (path) => (await apiFetch(path)).json();
  const show = (id, html) => { const el = bodyEl.querySelector(id); if (el) el.innerHTML = html; };

  try {
    const tpl = await get('/devqa/workflow-templates');
    const list = tpl.templates || [];
    show('#dqTemplates', list.length ? list.map((t) => `
      <div class="kn-mem-row"><strong>${escapeHtml(t.label)}</strong>
      <p class="settings-hint">${escapeHtml(t.desc)}</p>
      <details><summary>Starter graph (JSON)</summary><pre>${escapeHtml(JSON.stringify(t.definition, null, 2))}</pre></details></div>`).join('')
      : EMPTY('No starter templates are available right now.'));
  } catch { show('#dqTemplates', EMPTY('Could not load starter templates.')); }

  bodyEl.querySelector('#dqLintBtn')?.addEventListener('click', async () => {
    const text = bodyEl.querySelector('#dqLintText').value || '';
    try {
      const data = await (await apiFetch('/quality/lint', { method: 'POST', body: JSON.stringify({ text }) })).json();
      const issues = data.issues || [];
      show('#dqLintOut', issues.length ? issues.map((i) => `
        <div class="kn-mem-row"><strong>${escapeHtml(i.rule)}</strong>: ${escapeHtml(i.quote || '')}
        ${i.suggestion ? `<p class="settings-hint">${escapeHtml(i.suggestion)}</p>` : ''}</div>`).join('')
        : EMPTY('No issues found in this text.'));
    } catch { show('#dqLintOut', EMPTY('Writing check failed.')); }
  });

  bodyEl.querySelector('#dqScopeBtn')?.addEventListener('click', async () => {
    const target = bodyEl.querySelector('#dqScopeTarget').value.trim();
    const domains = bodyEl.querySelector('#dqScopeDomains').value.split(',').map((s) => s.trim()).filter(Boolean);
    if (!target || !domains.length) { show('#dqScopeOut', EMPTY('Enter a target host and at least one in-scope domain.')); return; }
    try {
      const data = await (await apiFetch('/devqa/security/scope/check', { method: 'POST', body: JSON.stringify({ target, scope: { domains } }) })).json();
      show('#dqScopeOut', data.allowed
        ? `<p class="settings-hint">In scope: ${escapeHtml(target)} matches the scope file. A run still needs its own per-run approval.</p>`
        : `<p class="settings-hint">OUT OF SCOPE: ${escapeHtml(target)} does not match the scope file. A run against it would be rejected, not warned about.</p>`);
    } catch (e) { show('#dqScopeOut', EMPTY(`Scope check failed: ${e?.message || 'unknown error'}`)); }
  });

  const loadServices = async () => {
    try {
      const data = await get('/devqa/platform/services');
      const list = data.services || [];
      show('#dqSvcOut', list.length ? list.map((s) => `
        <div class="kn-mem-row"><strong>${escapeHtml(s.name)}</strong> — ${escapeHtml(s.url)}
        <button class="btn-secondary" data-svc-check="${escapeHtml(s.id)}">Probe now</button>
        <span data-svc-result="${escapeHtml(s.id)}"></span></div>`).join('')
        : EMPTY('No services registered yet.'));
      bodyEl.querySelectorAll('[data-svc-check]').forEach((btn) => btn.addEventListener('click', async () => {
        const out = bodyEl.querySelector(`[data-svc-result="${btn.dataset.svcCheck}"]`);
        try {
          const r = await (await apiFetch(`/devqa/platform/services/${encodeURIComponent(btn.dataset.svcCheck)}/check`, { method: 'POST' })).json();
          if (out) out.textContent = ` ${r.status} (HTTP ${r.http_code ?? 'no response'})`;
        } catch { if (out) out.textContent = ' Probe failed.'; }
      }));
    } catch { show('#dqSvcOut', EMPTY('Could not load services.')); }
  };
  await loadServices();
  bodyEl.querySelector('#dqSvcBtn')?.addEventListener('click', async () => {
    const name = bodyEl.querySelector('#dqSvcName').value.trim();
    const url = bodyEl.querySelector('#dqSvcUrl').value.trim();
    if (!name || !url) return;
    try { await apiFetch('/devqa/platform/services', { method: 'POST', body: JSON.stringify({ name, url }) }); await loadServices(); }
    catch { show('#dqSvcOut', EMPTY('Service registration failed — the URL must be http(s).')); }
  });

  try {
    const data = await get('/devqa/platform/notifications');
    const list = data.notifications || [];
    show('#dqNotifOut', list.length ? list.map((n) => `
      <div class="kn-mem-row"><strong>${escapeHtml(n.title)}</strong>
      <p class="settings-hint">${escapeHtml(n.body || '')} — ${escapeHtml(n.source)}${n.read ? ' (read)' : ''}</p></div>`).join('')
      : EMPTY('No notifications yet. Webhook notifications need a secret configured on the server first.'));
  } catch { show('#dqNotifOut', EMPTY('Could not load notifications.')); }

  try {
    const [tpls, folders] = await Promise.all([get('/devqa/chat/prompt-templates'), get('/devqa/chat/folders')]);
    const pt = (tpls.templates || []).map((t) => `<div class="kn-mem-row"><strong>${escapeHtml(t.title)}</strong><p class="settings-hint">${escapeHtml(t.prompt)}</p></div>`).join('');
    const fl = (folders.folders || []).map((f) => `<div class="kn-mem-row"><strong>Folder: ${escapeHtml(f.name)}</strong><p class="settings-hint">${(f.chat_ids || []).length} chat(s)</p></div>`).join('');
    show('#dqChatOut', `<h4>Prompt templates</h4>${pt || EMPTY('No prompt templates.')}
      <h4>Chat folders</h4>${fl || EMPTY('No chat folders yet — create one from the API or here later; folders group chats, they never move chat history.')}`);
  } catch { show('#dqChatOut', EMPTY('Could not load chat organisation.')); }
}
