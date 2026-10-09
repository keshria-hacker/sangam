/**
 * Library view — Skills, MCP Servers, Extensions, Templates (Sangam-native, Phase 4).
 *
 * Data comes from GET /api/extensions (kinds: skill, mcp_server, tool,
 * provider, capability). Enable/disable via POST /api/extensions/{name}/enable|disable.
 * There is currently no backend install/delete endpoint, so those actions are
 * honestly unavailable (not fake buttons).
 */
import { apiFetch, apiPost } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] library.js loaded');

const TABS = [
  { id: 'skills', label: 'Skills', icon: 'fa-wand-magic-sparkles' },
  { id: 'mcp', label: 'MCP Servers', icon: 'fa-plug' },
  { id: 'extensions', label: 'Extensions', icon: 'fa-puzzle-piece' },
  { id: 'templates', label: 'Templates', icon: 'fa-file-lines' },
];

let activeTab = 'skills';
let extensions = [];
let kindFilter = 'all';

export function renderLibrary(bodyEl) {
  activeTab = 'skills';
  bodyEl.innerHTML = `
    <div class="library">
      <div class="library-tabs" role="tablist">
        ${TABS.map((t) => `
          <button class="library-tab${t.id === activeTab ? ' active' : ''}" role="tab"
            data-libtab="${t.id}" aria-selected="${t.id === activeTab}">
            <i class="fa-solid ${t.icon}"></i> ${t.label}
          </button>`).join('')}
      </div>
      <div class="library-body" id="libraryBody"></div>
    </div>`;
  bodyEl.querySelectorAll('[data-libtab]').forEach((b) => {
    b.addEventListener('click', () => {
      activeTab = b.dataset.libtab;
      bodyEl.querySelectorAll('[data-libtab]').forEach((x) => {
        x.classList.toggle('active', x === b);
        x.setAttribute('aria-selected', String(x === b));
      });
      renderTab(bodyEl);
    });
  });
  loadExtensions(bodyEl);
}

async function loadExtensions(bodyEl) {
  const wrap = bodyEl.querySelector('#libraryBody');
  wrap.innerHTML = '<p class="settings-hint">Loading…</p>';
  try {
    const data = await (await apiFetch('/extensions')).json();
    extensions = data.extensions || [];
  } catch (err) {
    wrap.innerHTML = `<p class="settings-hint">Could not load extensions: ${escapeHtml(err?.message || err)}</p>`;
    return;
  }
  renderTab(bodyEl);
}

function renderTab(bodyEl) {
  const wrap = bodyEl.querySelector('#libraryBody');
  if (!wrap) return;
  if (activeTab === 'skills') renderSkills(wrap);
  else if (activeTab === 'mcp') renderMcp(wrap);
  else if (activeTab === 'extensions') renderExtensions(wrap);
  else renderTemplates(wrap);
}

function kindBadge(kind) {
  return `<span class="lib-kind">${escapeHtml(kind || 'unknown')}</span>`;
}

function toggleSwitch(ext) {
  return `<label class="switch" title="${ext.enabled ? 'Disable' : 'Enable'}">
    <input type="checkbox" data-toggle-ext="${escapeHtml(ext.name)}"${ext.enabled ? ' checked' : ''}>
    <span class="switch-track"><span class="switch-thumb"></span></span>
  </label>`;
}

function wireToggles(wrap) {
  wrap.querySelectorAll('[data-toggle-ext]').forEach((cb) => {
    cb.addEventListener('change', async () => {
      const name = cb.dataset.toggleExt;
      const action = cb.checked ? 'enable' : 'disable';
      try {
        await apiPost(`/extensions/${encodeURIComponent(name)}/${action}`, {});
        const ext = extensions.find((e) => e.name === name);
        if (ext) ext.enabled = cb.checked;
        showToast({ type: 'success', title: `${name} ${action}d` });
      } catch (err) {
        cb.checked = !cb.checked;
        showToast({ type: 'error', title: 'Toggle failed', message: err?.message || String(err) });
      }
    });
  });
}

// --- Skills ---

function renderSkills(wrap) {
  const skills = extensions.filter((e) => e.kind === 'skill');
  wrap.innerHTML = `
    <div class="lib-grid">
      ${skills.map((s) => `
        <div class="lib-card">
          <div class="lib-card-head">
            <strong>${escapeHtml(s.name)}</strong>
            ${kindBadge(s.kind)}
          </div>
          <p class="lib-desc">${escapeHtml(s.description || 'No description.')}</p>
          <div class="lib-card-foot">
            <span class="settings-hint">v${escapeHtml(s.version || '?')}</span>
            ${toggleSwitch(s)}
          </div>
        </div>`).join('') || '<p class="settings-hint">No skills registered.</p>'}
    </div>
    <div class="lib-section">
      <h4><i class="fa-solid fa-file-import"></i> Imported drafts <span class="settings-hint">(local, until backend install lands)</span></h4>
      <div id="libDrafts" class="lib-grid"></div>
    </div>`;
  wireToggles(wrap);
  renderDrafts(wrap);
}

async function renderDrafts(wrap) {
  const el = wrap.querySelector('#libDrafts');
  if (!el) return;
  let drafts = [];
  try {
    const { getSkillDrafts } = await import('../learn/learn.js');
    drafts = getSkillDrafts();
  } catch { /* learn module unavailable */ }
  el.innerHTML = drafts.map((d) => `
    <div class="lib-card lib-draft">
      <div class="lib-card-head"><strong>${escapeHtml(d.name)}</strong><span class="lib-kind">draft</span></div>
      <p class="lib-desc">${escapeHtml((d.content || '').slice(0, 120))}…</p>
      <div class="lib-card-foot">
        <span class="settings-hint">${escapeHtml((d.savedAt || '').slice(0, 10))}</span>
        <button class="btn-secondary btn-sm" data-del-draft="${escapeHtml(d.name)}">Delete</button>
      </div>
    </div>`).join('') || '<p class="settings-hint">No drafts. Use Learn → Import skill.</p>';
  el.querySelectorAll('[data-del-draft]').forEach((b) => {
    b.addEventListener('click', () => {
      try {
        const key = 'sangam:skill-drafts';
        const rest = JSON.parse(localStorage.getItem(key) || '[]').filter((d) => d.name !== b.dataset.delDraft);
        localStorage.setItem(key, JSON.stringify(rest));
      } catch {}
      renderDrafts(wrap);
    });
  });
}

// --- MCP Servers ---

function renderMcp(wrap) {
  const servers = extensions.filter((e) => e.kind === 'mcp_server');
  wrap.innerHTML = `
    <p class="settings-hint">MCP servers expose tools to agents automatically once connected.</p>
    <div class="lib-list">
      ${servers.map((s) => `
        <div class="lib-row">
          <i class="fa-solid fa-plug lib-row-icon"></i>
          <div class="lib-row-main">
            <strong>${escapeHtml(s.name)}</strong>
            <span class="settings-hint">${escapeHtml(s.description || '')}</span>
          </div>
          <span class="lib-status ${s.enabled ? 'on' : 'off'}">${s.enabled ? 'Connected' : 'Off'}</span>
          <button class="btn-secondary btn-sm" data-mcp="${escapeHtml(s.name)}" data-on="${s.enabled ? '0' : '1'}">
            ${s.enabled ? 'Disconnect' : 'Connect'}
          </button>
        </div>`).join('') || '<p class="settings-hint">No MCP servers configured.</p>'}
    </div>`;
  wrap.querySelectorAll('[data-mcp]').forEach((b) => {
    b.addEventListener('click', async () => {
      const action = b.dataset.on === '1' ? 'enable' : 'disable';
      try {
        await apiPost(`/extensions/${encodeURIComponent(b.dataset.mcp)}/${action}`, {});
        const ext = extensions.find((e) => e.name === b.dataset.mcp);
        if (ext) ext.enabled = action === 'enable';
        showToast({ type: 'success', title: `MCP server ${action}d` });
        renderMcp(wrap);
      } catch (err) {
        showToast({ type: 'error', title: 'Failed', message: err?.message || String(err) });
      }
    });
  });
}

// --- Extensions ---

const KIND_OPTIONS = ['all', 'tool', 'skill', 'provider', 'capability', 'mcp_server'];

function renderExtensions(wrap) {
  const kinds = [...new Set(extensions.map((e) => e.kind).filter(Boolean))];
  const shown = extensions.filter((e) => kindFilter === 'all' || e.kind === kindFilter);
  wrap.innerHTML = `
    <div class="lib-toolbar">
      <label class="settings-hint">Kind:</label>
      <select id="libKindFilter" class="provider-key-input" aria-label="Filter by kind">
        ${KIND_OPTIONS.filter((k) => k === 'all' || kinds.includes(k)).map((k) =>
          `<option value="${k}"${k === kindFilter ? ' selected' : ''}>${k}</option>`).join('')}
      </select>
      <span class="settings-hint">${shown.length} of ${extensions.length}</span>
    </div>
    <div class="lib-list">
      ${shown.map((e) => `
        <div class="lib-row">
          <div class="lib-row-main">
            <strong>${escapeHtml(e.name)}</strong> ${kindBadge(e.kind)}
            <span class="settings-hint">${escapeHtml(e.description || '')}</span>
          </div>
          <span class="settings-hint">v${escapeHtml(e.version || '?')}</span>
          ${toggleSwitch(e)}
        </div>`).join('') || '<p class="settings-hint">No extensions.</p>'}
    </div>`;
  wrap.querySelector('#libKindFilter')?.addEventListener('change', (ev) => {
    kindFilter = ev.target.value;
    renderExtensions(wrap);
  });
  wireToggles(wrap);
}

// --- Templates ---

const ARTIFACT_TEMPLATES = [
  { name: 'Python script', icon: 'fa-brands fa-python', body: '#!/usr/bin/env python3\n"""{{description}}"""\n\ndef main():\n    pass\n\nif __name__ == "__main__":\n    main()\n' },
  { name: 'Bash script', icon: 'fa-solid fa-terminal', body: '#!/usr/bin/env bash\nset -euo pipefail\n# {{description}}\n' },
  { name: 'Markdown doc', icon: 'fa-brands fa-markdown', body: '# {{title}}\n\n## Overview\n\n## Details\n' },
  { name: 'HTML prototype', icon: 'fa-brands fa-html5', body: '<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8"><title>{{title}}</title></head>\n<body>\n\n</body>\n</html>\n' },
];

const PROMPT_TEMPLATES = [
  { name: 'Code review', body: 'Review the following code for bugs, style, and performance. Be specific:\n\n```\n{{code}}\n```' },
  { name: 'Explain simply', body: 'Explain the following like I\'m a beginner, with a concrete example:\n\n{{topic}}' },
  { name: 'Test plan', body: 'Write a test plan for:\n\n{{feature}}\n\nCover happy path, edge cases, and failure modes.' },
  { name: 'Commit message', body: 'Write a conventional commit message for these changes:\n\n{{diff}}' },
];

function renderTemplates(wrap) {
  const card = (t) => `
    <div class="lib-card">
      <div class="lib-card-head">
        <strong>${escapeHtml(t.name)}</strong>
        ${t.icon ? `<i class="fa-solid ${t.icon}"></i>` : ''}
      </div>
      <pre class="lib-template-body">${escapeHtml(t.body.slice(0, 160))}${t.body.length > 160 ? '…' : ''}</pre>
      <div class="lib-card-foot">
        <button class="btn-secondary btn-sm" data-copy-tpl="${escapeHtml(t.name)}">
          <i class="fa-regular fa-copy"></i> Copy
        </button>
      </div>
    </div>`;
  wrap.innerHTML = `
    <div class="lib-section"><h4>Artifact templates</h4>
      <div class="lib-grid">${ARTIFACT_TEMPLATES.map(card).join('')}</div></div>
    <div class="lib-section"><h4>Prompt templates</h4>
      <div class="lib-grid">${PROMPT_TEMPLATES.map(card).join('')}</div></div>`;
  const all = [...ARTIFACT_TEMPLATES, ...PROMPT_TEMPLATES];
  wrap.querySelectorAll('[data-copy-tpl]').forEach((b) => {
    b.addEventListener('click', async () => {
      const t = all.find((x) => x.name === b.dataset.copyTpl);
      if (!t) return;
      try {
        await navigator.clipboard.writeText(t.body);
        showToast({ type: 'success', title: `Copied: ${t.name}` });
      } catch {
        showToast({ type: 'error', title: 'Copy failed' });
      }
    });
  });
}
