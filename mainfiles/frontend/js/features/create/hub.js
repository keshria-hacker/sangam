/**
 * Create Hub — documents, diagrams, code snippets, HTML pages (Sangam-native, Phase 4).
 *
 * Exports renderCreateHub(bodyEl). Parent wires it as a tab renderer.
 * Backend: /api/artifacts (CRUD + version history).
 */
import { apiFetch, apiPost, apiPut, apiDelete } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml, formatTime, debounce } from '../../shared/utils.js';
import { renderMarkdown } from '../../shared/markdown.js';

console.log('[Module] create/hub.js loaded');

const TYPE_META = {
  doc:     { label: 'Document',    icon: 'fa-file-lines',     placeholder: 'Untitled document' },
  diagram: { label: 'Diagram',     icon: 'fa-diagram-project', placeholder: 'Untitled diagram' },
  code:    { label: 'Code snippet', icon: 'fa-code',           placeholder: 'Untitled snippet' },
  html:    { label: 'HTML page',   icon: 'fa-globe',           placeholder: 'Untitled page' },
};

const CODE_LANGUAGES = [
  'plaintext', 'javascript', 'typescript', 'python', 'html', 'css',
  'json', 'bash', 'sql', 'java', 'go', 'rust', 'cpp', 'yaml', 'markdown',
];

const TEMPLATES = [
  {
    name: 'Meeting notes', icon: 'fa-clipboard-list', type: 'doc',
    title: 'Meeting notes',
    content: `# Meeting notes — ${new Date().toLocaleDateString()}\n\n## Attendees\n- \n\n## Agenda\n1. \n\n## Decisions\n- \n\n## Action items\n- [ ] `,
  },
  {
    name: 'Project plan', icon: 'fa-list-check', type: 'doc',
    title: 'Project plan',
    content: `# Project plan\n\n## Goal\n\n## Milestones\n1. \n2. \n\n## Risks\n- \n\n## Timeline\n| Milestone | Owner | Due |\n|-----------|-------|-----|\n|           |       |     |`,
  },
  {
    name: 'API doc', icon: 'fa-plug', type: 'doc',
    title: 'API doc',
    content: `# API reference\n\n## \`GET /endpoint\`\n\n**Description:** \n\n**Parameters**\n| Name | Type | Required | Description |\n|------|------|----------|-------------|\n|      |      |          |             |\n\n**Response**\n\`\`\`json\n{}\n\`\`\``,
  },
  {
    name: 'Blog post', icon: 'fa-pen-nib', type: 'doc',
    title: 'Blog post draft',
    content: `# Title\n\n> One-line hook.\n\n## Intro\n\n## Body\n\n## Takeaways\n- \n- `,
  },
  {
    name: 'Diagram starter', icon: 'fa-diagram-project', type: 'diagram',
    title: 'Flow diagram',
    content: `A[Start]\nB[Process]\nC{Decision?}\nD[End]\nA --> B\nB --> C\nC -- yes --> D\nC -- no --> B`,
  },
  {
    name: 'HTML starter', icon: 'fa-globe', type: 'html',
    title: 'Landing page',
    content: `<!DOCTYPE html>\n<html>\n<head><meta charset="utf-8"><title>Page</title>\n<style>body{font-family:system-ui;max-width:640px;margin:40px auto;padding:0 16px}</style></head>\n<body>\n<h1>Hello</h1>\n<p>Start here.</p>\n</body>\n</html>`,
  },
];

// --- module state (one hub instance per mount) ---
let root = null;
let artifacts = [];
let editing = null;   // {id, title, type, language, content, version, dirty}
let viewVersion = null; // when viewing an old version: {version, content}
let docClickWired = false; // guard: document-level menu closers are wired once

/** Close any open dropdown menus in the hub. Idempotent. */
function closeAllMenus() {
  root?.querySelectorAll('.create-new-menu').forEach((m) => m.classList.add('hidden'));
}

function wireDocClickOnce() {
  if (docClickWired) return;
  docClickWired = true;
  document.addEventListener('click', () => closeAllMenus());
}

export async function renderCreateHub(bodyEl) {
  root = bodyEl;
  editing = null;
  viewVersion = null;
  bodyEl.innerHTML = `
    <div class="create-hub">
      <div class="hub-header">
        <h3><i class="fa-solid fa-wand-magic-sparkles"></i> Create</h3>
        <div class="create-new-wrap">
          <button class="btn-primary btn-sm" id="createNewBtn"><i class="fa-solid fa-plus"></i> New <i class="fa-solid fa-chevron-down"></i></button>
          <div class="create-new-menu hidden" id="createNewMenu" role="menu">
            ${Object.entries(TYPE_META).map(([k, m]) => `
              <button type="button" data-newtype="${k}"><i class="fa-solid ${m.icon}"></i> ${m.label}</button>`).join('')}
          </div>
        </div>
      </div>
      <div id="createEditorWrap"></div>
      <div id="createListWrap">
        <h4 class="hub-section-title">Start from a template</h4>
        <div class="hub-grid" id="createTemplates"></div>
        <h4 class="hub-section-title">My artifacts</h4>
        <div class="hub-grid" id="createGrid"><p class="settings-hint">Loading…</p></div>
      </div>
    </div>`;

  wireNewMenu();
  renderTemplates();
  await loadArtifacts();
}

function wireNewMenu() {
  wireDocClickOnce();
  const btn = root.querySelector('#createNewBtn');
  const menu = root.querySelector('#createNewMenu');
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const wasHidden = menu.classList.contains('hidden');
    closeAllMenus();
    if (wasHidden) menu.classList.remove('hidden');
  });
  menu.querySelectorAll('[data-newtype]').forEach((b) => {
    b.addEventListener('click', async (e) => {
      e.stopPropagation();
      menu.classList.add('hidden');
      await createArtifact(b.dataset.newtype, '', '');
    });
  });
}

function renderTemplates() {
  const wrap = root.querySelector('#createTemplates');
  wrap.innerHTML = TEMPLATES.map((t, i) => `
    <button type="button" class="hub-card create-tpl" data-tpl="${i}">
      <div class="hub-card-head"><i class="fa-solid ${t.icon}"></i><strong>${escapeHtml(t.name)}</strong></div>
      <span class="settings-hint">${escapeHtml(TYPE_META[t.type].label)}</span>
    </button>`).join('');
  wrap.querySelectorAll('[data-tpl]').forEach((b) => {
    b.addEventListener('click', () => {
      const t = TEMPLATES[Number(b.dataset.tpl)];
      createArtifact(t.type, t.title, t.content);
    });
  });
}

async function loadArtifacts() {
  const grid = root.querySelector('#createGrid');
  try {
    const data = await (await apiFetch('/artifacts')).json();
    artifacts = data.artifacts || [];
  } catch {
    artifacts = [];
    grid.innerHTML = '<p class="settings-hint">Could not load artifacts.</p>';
    return;
  }
  if (!artifacts.length) {
    grid.innerHTML = '<p class="settings-hint">No artifacts yet — create one or start from a template.</p>';
    return;
  }
  grid.innerHTML = artifacts.map((a) => {
    const m = TYPE_META[a.type] || TYPE_META.doc;
    return `
    <button type="button" class="hub-card create-card" data-id="${escapeHtml(a.id)}">
      <div class="hub-card-head"><i class="fa-solid ${m.icon}"></i><strong>${escapeHtml(a.title || m.placeholder)}</strong></div>
      <span class="settings-hint">${escapeHtml(m.label)}${a.language ? ` · ${escapeHtml(a.language)}` : ''} · ${escapeHtml(formatTime(a.updated_at))}</span>
    </button>`;
  }).join('');
  grid.querySelectorAll('[data-id]').forEach((b) => {
    b.addEventListener('click', () => openEditor(b.dataset.id));
  });
}

async function createArtifact(type, title, content) {
  try {
    const data = await (await apiPost('/artifacts', {
      title: title || TYPE_META[type].placeholder,
      type, content, language: type === 'code' ? 'plaintext' : null,
    })).json();
    showToast({ type: 'success', title: 'Artifact created' });
    await loadArtifacts();
    openEditor(data.id);
  } catch (err) {
    showToast({ type: 'error', title: 'Create failed', message: err?.message || String(err) });
  }
}

// ---------------------------------------------------------------- editor ---

async function openEditor(id) {
  try {
    const a = await (await apiFetch(`/artifacts/${id}`)).json();
    editing = { id: a.id, title: a.title, type: a.type, language: a.language || 'plaintext',
                content: a.content || '', version: a.version, dirty: false };
    viewVersion = null;
    renderEditor();
  } catch (err) {
    showToast({ type: 'error', title: 'Could not open artifact', message: err?.message || String(err) });
  }
}

function renderEditor() {
  const wrap = root.querySelector('#createEditorWrap');
  const listWrap = root.querySelector('#createListWrap');
  const a = editing;
  if (!a) { wrap.innerHTML = ''; listWrap.classList.remove('hidden'); return; }
  listWrap.classList.add('hidden');
  const m = TYPE_META[a.type] || TYPE_META.doc;

  wrap.innerHTML = `
    <div class="create-editor">
      <div class="create-ed-bar">
        <button class="icon-btn" id="ceBack" title="Back to list" aria-label="Back"><i class="fa-solid fa-arrow-left"></i></button>
        <input class="provider-key-input create-ed-title" id="ceTitle" value="${escapeHtml(a.title || '')}" placeholder="${m.placeholder}" aria-label="Title">
        <span class="settings-hint">v${a.version}</span>
        <div class="create-ver-wrap">
          <button class="btn-secondary btn-sm" id="ceVersions"><i class="fa-solid fa-clock-rotate-left"></i> History</button>
          <div class="create-new-menu hidden" id="ceVersionsMenu" role="menu"></div>
        </div>
        <button class="btn-secondary btn-sm" id="ceDelete"><i class="fa-solid fa-trash"></i></button>
        <button class="btn-primary btn-sm" id="ceSave" disabled><i class="fa-solid fa-floppy-disk"></i> Save</button>
      </div>
      ${a.type === 'code' ? `
      <div class="create-ed-tools">
        <label class="settings-hint">Language
          <select id="ceLang" class="provider-key-input">
            ${CODE_LANGUAGES.map((l) => `<option value="${l}"${a.language === l ? ' selected' : ''}>${l}</option>`).join('')}
          </select>
        </label>
      </div>` : ''}
      ${viewVersion ? `<div class="create-ver-banner"><i class="fa-solid fa-eye"></i> Viewing version ${viewVersion.version} (read-only)
        <button class="btn-secondary btn-sm" id="ceRestore">Restore this version</button>
        <button class="btn-secondary btn-sm" id="ceBackToCurrent">Back to current</button></div>` : ''}
      <div class="create-ed-split">
        <textarea id="ceContent" class="create-ed-input" spellcheck="false"
          placeholder="Write here…">${escapeHtml(viewVersion ? viewVersion.content : a.content)}</textarea>
        <div id="cePreview" class="create-ed-preview"></div>
      </div>
    </div>`;

  const textarea = wrap.querySelector('#ceContent');
  const preview = wrap.querySelector('#cePreview');
  const saveBtn = wrap.querySelector('#ceSave');
  if (viewVersion) textarea.setAttribute('readonly', '');

  const markDirty = () => {
    if (viewVersion) return;
    editing.dirty = true;
    saveBtn.disabled = false;
  };

  wrap.querySelector('#ceBack').addEventListener('click', async () => {
    if (editing.dirty && !viewVersion) {
      if (!confirm('Discard unsaved changes?')) return;
    }
    editing = null; viewVersion = null;
    wrap.innerHTML = '';
    listWrap.classList.remove('hidden');
    await loadArtifacts();
  });

  wrap.querySelector('#ceTitle').addEventListener('input', (e) => {
    editing.title = e.target.value;
    markDirty();
  });

  const doPreview = debounce(() => { updatePreview(a.type, textarea.value, preview, a.language); }, 250);
  textarea.addEventListener('input', () => { markDirty(); doPreview(); });
  updatePreview(a.type, textarea.value, preview, a.language);

  wrap.querySelector('#ceLang')?.addEventListener('change', (e) => {
    editing.language = e.target.value;
    markDirty();
    updatePreview(a.type, textarea.value, preview, a.language);
  });

  saveBtn.addEventListener('click', async () => {
    saveBtn.disabled = true;
    try {
      const res = await (await apiPut(`/artifacts/${a.id}`, {
        title: editing.title, content: textarea.value,
      })).json();
      editing.content = textarea.value;
      editing.version = res.version;
      editing.dirty = false;
      viewVersion = null;
      showToast({ type: 'success', title: `Saved as v${res.version}` });
      renderEditor();
    } catch (err) {
      saveBtn.disabled = false;
      showToast({ type: 'error', title: 'Save failed', message: err?.message || String(err) });
    }
  });

  wrap.querySelector('#ceDelete').addEventListener('click', async () => {
    if (!confirm(`Delete "${editing.title || 'artifact'}" and all its versions?`)) return;
    try {
      await apiDelete(`/artifacts/${a.id}`);
      showToast({ type: 'success', title: 'Deleted' });
      editing = null; viewVersion = null;
      wrap.innerHTML = '';
      listWrap.classList.remove('hidden');
      await loadArtifacts();
    } catch (err) {
      showToast({ type: 'error', title: 'Delete failed', message: err?.message || String(err) });
    }
  });

  wireVersionsMenu(wrap);
  wrap.querySelector('#ceRestore')?.addEventListener('click', () => {
    // Load old content into the editor (not auto-saved) so the user can review then Save
    editing.content = viewVersion.content;
    viewVersion = null;
    editing.dirty = true;
    showToast({ type: 'info', title: 'Old version loaded — Save to restore it' });
    renderEditor();
  });
  wrap.querySelector('#ceBackToCurrent')?.addEventListener('click', () => {
    viewVersion = null;
    renderEditor();
  });
}

async function wireVersionsMenu(wrap) {
  wireDocClickOnce();
  const btn = wrap.querySelector('#ceVersions');
  const menu = wrap.querySelector('#ceVersionsMenu');
  btn.addEventListener('click', async (e) => {
    e.stopPropagation();
    if (!menu.classList.contains('hidden')) { menu.classList.add('hidden'); return; }
    closeAllMenus();
    menu.innerHTML = '<span class="settings-hint" style="padding:8px">Loading…</span>';
    menu.classList.remove('hidden');
    try {
      const data = await (await apiFetch(`/artifacts/${editing.id}/versions`)).json();
      const vers = data.versions || [];
      menu.innerHTML = vers.length ? vers.map((v) => `
        <button type="button" data-ver="${v.version}"${v.version === editing.version && !viewVersion ? ' class="selected"' : ''}>
          <i class="fa-solid fa-clock-rotate-left"></i> v${v.version}
          <span class="settings-hint">${escapeHtml(formatTime(v.created_at))}</span>
        </button>`).join('')
        : '<span class="settings-hint" style="padding:8px">No versions</span>';
      menu.querySelectorAll('[data-ver]').forEach((b) => {
        b.addEventListener('click', async (ev) => {
          ev.stopPropagation();
          menu.classList.add('hidden');
          const v = Number(b.dataset.ver);
          if (v === editing.version) { viewVersion = null; renderEditor(); return; }
          try {
            const a = await (await apiFetch(`/artifacts/${editing.id}?version=${v}`)).json();
            viewVersion = { version: v, content: a.content || '' };
            renderEditor();
          } catch (err) {
            showToast({ type: 'error', title: 'Could not load version' });
          }
        });
      });
    } catch {
      menu.innerHTML = '<span class="settings-hint" style="padding:8px">Failed to load</span>';
    }
  });
}

// --------------------------------------------------------------- previews ---

function updatePreview(type, content, previewEl, language) {
  try {
    if (type === 'doc') {
      previewEl.innerHTML = renderMarkdown(content || '*Nothing to preview*');
    } else if (type === 'diagram') {
      previewEl.innerHTML = renderDiagram(content);
    } else if (type === 'code') {
      const codeEl = document.createElement('code');
      previewEl.innerHTML = '';
      const pre = document.createElement('pre');
      pre.className = `language-${language || 'plaintext'} create-code-pre`;
      codeEl.textContent = content;
      pre.appendChild(codeEl);
      previewEl.appendChild(pre);
      // highlight.js via CDN global (markdown.js's helper references a bare
      // `highlight` global that may not exist — use window.hljs defensively)
      if (window.hljs && typeof window.hljs.highlightElement === 'function') {
        try { window.hljs.highlightElement(codeEl); } catch { /* keep plain */ }
      }
    } else if (type === 'html') {
      previewEl.innerHTML = '';
      const frame = document.createElement('iframe');
      frame.className = 'create-html-frame';
      frame.setAttribute('sandbox', 'allow-scripts');
      frame.setAttribute('title', 'HTML preview');
      frame.srcdoc = content;
      previewEl.appendChild(frame);
    }
  } catch (err) {
    previewEl.innerHTML = `<p class="settings-hint">Preview error: ${escapeHtml(err?.message || String(err))}</p>`;
  }
}

/**
 * Minimal diagram renderer. Supports a small flowchart subset, one per line:
 *   A[Label]      box        A{Label}      diamond        A(Label)      rounded
 *   A --> B       arrow      A -> B        arrow          A -- text --> B   labeled arrow
 * Anything else renders as plain text lines.
 */
function renderDiagram(src) {
  const lines = (src || '').split('\n').map((l) => l.trim()).filter(Boolean);
  const nodes = new Map(); // id -> {label, shape}
  const edges = [];        // {from, to, label}

  const nodeRe = /^([A-Za-z0-9_]+)\s*(?:\[([^\]]*)\]|\{([^}]*)\}|\(([^)]*)\))$/;
  const edgeRe = /^([A-Za-z0-9_]+)\s*-{1,2}\s*(?:([^-]+?)\s*-{1,2}\s*)?>\s*([A-Za-z0-9_]+)\s*$/;

  for (const line of lines) {
    let m = line.match(nodeRe);
    if (m) {
      const shape = m[2] !== undefined ? 'box' : (m[3] !== undefined ? 'diamond' : 'round');
      const label = (m[2] ?? m[3] ?? m[4] ?? '').trim() || m[1];
      nodes.set(m[1], { label, shape });
      continue;
    }
    m = line.match(edgeRe);
    if (m) {
      if (!nodes.has(m[1])) nodes.set(m[1], { label: m[1], shape: 'box' });
      if (!nodes.has(m[3])) nodes.set(m[3], { label: m[3], shape: 'box' });
      edges.push({ from: m[1], to: m[3], label: (m[2] || '').trim() });
      continue;
    }
  }

  if (!nodes.size) {
    return `<div class="create-diagram-fallback">${escapeHtml(src || 'Empty diagram — try:\nA[Start]\nB[End]\nA --> B')}</div>`;
  }

  // Layered layout: depth = longest path from a root
  const depth = new Map();
  const visiting = new Set();
  function calcDepth(id) {
    if (depth.has(id)) return depth.get(id);
    if (visiting.has(id)) return 0;
    visiting.add(id);
    let d = 0;
    for (const e of edges) if (e.to === id) d = Math.max(d, calcDepth(e.from) + 1);
    visiting.delete(id);
    depth.set(id, d);
    return d;
  }
  for (const id of nodes.keys()) calcDepth(id);

  const layers = new Map();
  for (const [id, d] of depth) {
    if (!layers.has(d)) layers.set(d, []);
    layers.get(d).push(id);
  }

  const W = 170, H = 76, GX = 200, GY = 110;
  const maxLayer = Math.max(...layers.keys());
  const maxRows = Math.max(...[...layers.values()].map((l) => l.length));
  const svgW = (maxLayer + 1) * GX + 40;
  const svgH = maxRows * GY + 40;
  const pos = new Map();
  for (const [d, ids] of layers) {
    ids.forEach((id, i) => pos.set(id, { x: 20 + d * GX, y: 20 + i * GY }));
  }

  let svg = `<svg class="create-diagram-svg" viewBox="0 0 ${svgW} ${svgH}" role="img" aria-label="Diagram preview">
    <defs><marker id="cdArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 1 L 9 5 L 0 9 z" class="cd-arrow-head"/></marker></defs>`;

  for (const e of edges) {
    const a = pos.get(e.from), b = pos.get(e.to);
    if (!a || !b) continue;
    const x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2;
    const mx = (x1 + x2) / 2;
    svg += `<path d="M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2 - 2} ${y2}" class="cd-edge" marker-end="url(#cdArrow)"/>`;
    if (e.label) svg += `<text x="${mx}" y="${(y1 + y2) / 2 - 6}" class="cd-edge-label" text-anchor="middle">${escapeHtml(e.label)}</text>`;
  }
  for (const [id, n] of nodes) {
    const p = pos.get(id);
    // Truncate long labels so they fit the fixed-size boxes
    const short = n.label.length > 22 ? n.label.slice(0, 21) + '…' : n.label;
    const label = escapeHtml(short);
    const full = escapeHtml(n.label);
    if (n.shape === 'diamond') {
      const cx = p.x + W / 2, cy = p.y + H / 2;
      svg += `<polygon points="${cx},${p.y} ${p.x + W},${cy} ${cx},${p.y + H} ${p.x},${cy}" class="cd-node"><title>${full}</title></polygon>`;
      svg += `<text x="${cx}" y="${cy + 4}" class="cd-label" text-anchor="middle">${label}</text>`;
    } else {
      const rx = n.shape === 'round' ? 18 : 8;
      svg += `<rect x="${p.x}" y="${p.y}" width="${W}" height="${H}" rx="${rx}" class="cd-node"><title>${full}</title></rect>`;
      svg += `<text x="${p.x + W / 2}" y="${p.y + H / 2 + 4}" class="cd-label" text-anchor="middle">${label}</text>`;
    }
  }
  svg += '</svg>';
  return `<div class="create-diagram-scroll">${svg}</div>
    <p class="settings-hint create-diagram-hint">Syntax: <code>A[Box]</code> <code>A{Choice}</code> <code>A(Round)</code> · <code>A --> B</code> · <code>A -- yes --> B</code></p>`;
}
