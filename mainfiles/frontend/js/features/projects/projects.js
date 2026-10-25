/**
 * Projects view — A3 (perfect-flow §3.1 Projects).
 *
 * Destination-agnostic on purpose: the coordinator's shell agent mounts
 * this module under the new Projects destination; nothing here assumes
 * a tab id, a sidebar entry, or a route. Two exports:
 *   renderProjectsView(containerEl) — project list → project home
 *   renderProjectHome(containerEl, projectId) — one project, sections
 *     Overview / Instructions / Sources / Tasks / Chats, with a
 *     scoped-retrieve box that only ever searches this project.
 * All data comes from /projects/* — no mock content, no fabricated
 * citations. Retrieval results show their grade + provenance label.
 */
import { apiDelete, apiFetch, apiGet, apiPost, apiPut } from '../../shared/http.js';
import { escapeHtml } from '../../shared/utils.js';
import { showError, showSuccess } from '../../shared/toast.js';

console.log('[Module] projects.js loaded');

let currentProjectId = null;

function sectionNav(active) {
  const sections = [
    ['overview', 'Overview'], ['instructions', 'Instructions'],
    ['sources', 'Sources'], ['tasks', 'Tasks'], ['chats', 'Chats'],
  ];
  return `<div class="pj-sections" role="tablist">${sections.map(([id, label]) => `
    <button class="pj-section-btn${active === id ? ' active' : ''}" data-section="${id}" role="tab">${label}</button>`).join('')}
  </div>`;
}

export async function renderProjectsView(containerEl) {
  containerEl.innerHTML = `
    <div class="projects-view">
      <div class="pj-head">
        <h3>Projects</h3>
        <p class="settings-hint">Persistent workspaces: instructions, sources, tasks and chats scoped to one project. Nothing from one project leaks into another.</p>
      </div>
      <form id="pjCreate" class="pj-create">
        <input type="text" id="pjName" placeholder="Project name" maxlength="200" required>
        <input type="text" id="pjDesc" placeholder="What is this project about? (optional)">
        <select id="pjScope" title="Memory scope">
          <option value="project">Scoped memory (this project only)</option>
          <option value="global">Global memory (all uploads)</option>
        </select>
        <button type="submit" class="btn-primary">New project</button>
      </form>
      <div id="pjList"></div>
      <div id="pjHome"></div>
    </div>`;
  containerEl.querySelector('#pjCreate').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = containerEl.querySelector('#pjName').value.trim();
    if (!name) return;
    try {
      await apiPost('/projects', {
        name,
        description: containerEl.querySelector('#pjDesc').value.trim(),
        memory_scope: containerEl.querySelector('#pjScope').value,
      });
      showSuccess('Project created');
      await loadList(containerEl);
    } catch (err) { showError(err.message || 'Could not create project'); }
  });
  await loadList(containerEl);
}

async function loadList(containerEl) {
  const listEl = containerEl.querySelector('#pjList');
  try {
    const data = await (await apiGet('/projects')).json();
    const projects = data.projects || [];
    if (!projects.length) {
      listEl.innerHTML = `<div class="empty-state"><p>No projects yet.</p>
        <p class="settings-hint">One guided next action: create a project above, then add its instructions and sources.</p></div>`;
      return;
    }
    listEl.innerHTML = `<ul class="pj-list">${projects.map((p) => `
      <li><button class="pj-item" data-id="${escapeHtml(p.id)}">
        <strong>${escapeHtml(p.name)}</strong>
        <span>${escapeHtml(p.description || '')}</span>
        <small>Scope: ${escapeHtml(p.memory_scope || 'project')}</small>
      </button></li>`).join('')}</ul>`;
    listEl.querySelectorAll('.pj-item').forEach((btn) => {
      btn.addEventListener('click', () => renderProjectHome(containerEl, btn.dataset.id));
    });
  } catch (err) { listEl.innerHTML = `<p class="settings-hint">Could not load projects: ${escapeHtml(err.message || '')}</p>`; }
}

export async function renderProjectHome(containerEl, projectId) {
  currentProjectId = projectId;
  const homeEl = containerEl.querySelector('#pjHome') || containerEl;
  try {
    const project = await (await apiGet(`/projects/${projectId}`)).json();
    homeEl.innerHTML = `
      <div class="pj-home">
        <button class="btn-secondary" id="pjBack">← All projects</button>
        <h3>${escapeHtml(project.name)}</h3>
        <p class="settings-hint">${escapeHtml(project.description || '')} · Scope: ${escapeHtml(project.memory_scope || 'project')} · ${project.open_task_count || 0} open tasks · ${project.chat_count || 0} chats</p>
        ${sectionNav('overview')}
        <div id="pjSection"></div>
      </div>`;
    homeEl.querySelector('#pjBack').addEventListener('click', () => {
      currentProjectId = null;
      homeEl.innerHTML = '';
      loadList(containerEl);
    });
    homeEl.querySelectorAll('.pj-section-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        homeEl.querySelectorAll('.pj-section-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        renderSection(homeEl, projectId, btn.dataset.section);
      });
    });
    await renderSection(homeEl, projectId, 'overview');
  } catch (err) { homeEl.innerHTML = `<p class="settings-hint">Could not open project: ${escapeHtml(err.message || '')}</p>`; }
}

async function renderSection(homeEl, projectId, section) {
  const el = homeEl.querySelector('#pjSection');
  el.innerHTML = '<p class="settings-hint">Loading…</p>';
  try {
    if (section === 'overview') {
      const project = await (await apiGet(`/projects/${projectId}`)).json();
      el.innerHTML = `
        <p>${escapeHtml(project.instruction || 'No instructions yet — add them under Instructions so every answer in this project follows them.')}</p>
        <form id="pjAsk" class="pj-ask">
          <input type="text" id="pjQuery" placeholder="Search only this project's sources…" required>
          <button type="submit" class="btn-primary">Search project</button>
        </form>
        <div id="pjResults"></div>`;
      el.querySelector('#pjAsk').addEventListener('submit', async (e) => {
        e.preventDefault();
        const q = el.querySelector('#pjQuery').value.trim();
        const resEl = el.querySelector('#pjResults');
        resEl.innerHTML = '<p class="settings-hint">Searching this project only…</p>';
        try {
          const data = await (await apiGet(`/projects/${projectId}/retrieve?q=${encodeURIComponent(q)}`)).json();
          const results = data.results || [];
          resEl.innerHTML = `<p class="settings-hint">Grade: ${escapeHtml(data.grade || '')} · Fallback: ${escapeHtml(data.fallback_used || 'none')} · Scope: ${escapeHtml(data.memory_scope || 'project')}</p>` +
            (results.length ? `<ul>${results.map((r) => {
              const c = r.citation || {};
              return `<li><p>${escapeHtml((r.text || '').slice(0, 300))}</p>
                <small>Source: ${escapeHtml(c.filename || '')} · chunk ${c.chunk_index ?? ''} · ${escapeHtml(c.provenance || 'verified')} · grade ${escapeHtml(c.grade || '')}</small></li>`;
            }).join('')}</ul>` : '<p class="settings-hint">No results in this project.</p>');
        } catch (err) { resEl.innerHTML = `<p class="settings-hint">Search failed: ${escapeHtml(err.message || '')}</p>`; }
      });
      return;
    }
    if (section === 'instructions') {
      const data = await (await apiGet(`/projects/${projectId}/instructions`)).json();
      el.innerHTML = `
        <form id="pjInstr" class="pj-form">
          <textarea id="pjInstrText" rows="6" placeholder="Instructions for this project — tone, constraints, facts the model must respect…">${escapeHtml((data.current && data.current.content) || '')}</textarea>
          <button type="submit" class="btn-primary">Save as current instructions</button>
        </form>
        <p class="settings-hint">Saving creates a new version; earlier versions stay in history below.</p>
        <ul>${(data.history || []).map((h) => `<li><small>${escapeHtml(h.created_at || '')}${h.is_current ? ' · current' : ''}</small><p>${escapeHtml(h.content.slice(0, 300))}</p></li>`).join('')}</ul>`;
      el.querySelector('#pjInstr').addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
          await apiPost(`/projects/${projectId}/instructions`, { content: el.querySelector('#pjInstrText').value });
          showSuccess('Instructions saved');
          await renderSection(homeEl, projectId, 'instructions');
        } catch (err) { showError(err.message || 'Could not save instructions'); }
      });
      return;
    }
    if (section === 'sources') {
      const data = await (await apiGet(`/projects/${projectId}/sources`)).json();
      el.innerHTML = `
        <form id="pjSrc" class="pj-form">
          <select id="pjSrcKind"><option value="url">Web page (URL)</option><option value="file">Uploaded file id</option><option value="chat">Chat id</option></select>
          <input type="text" id="pjSrcRef" placeholder="URL, file id, or chat id" required>
          <select id="pjSrcMode"><option value="full">Full context</option><option value="summary">Summary only</option><option value="excluded">Excluded</option></select>
          <button type="submit" class="btn-primary">Add source</button>
        </form>
        <p class="settings-hint">URL sources are fetched once on add (SSRF-guarded). Excluded sources are never fetched and never retrieved.</p>
        <ul>${(data.sources || []).map((s) => `<li>
          <strong>${escapeHtml(s.kind)}</strong> ${escapeHtml(s.ref.slice(0, 80))}
          <small>· ${escapeHtml(s.context_mode)} · ingest: ${escapeHtml(s.ingest_status || '')}</small>
          <button class="btn-secondary pj-src-del" data-id="${escapeHtml(s.id)}">Remove</button></li>`).join('')}</ul>`;
      el.querySelector('#pjSrc').addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
          await apiPost(`/projects/${projectId}/sources`, {
            kind: el.querySelector('#pjSrcKind').value,
            ref: el.querySelector('#pjSrcRef').value.trim(),
            context_mode: el.querySelector('#pjSrcMode').value,
          });
          showSuccess('Source added');
          await renderSection(homeEl, projectId, 'sources');
        } catch (err) { showError(err.message || 'Could not add source'); }
      });
      el.querySelectorAll('.pj-src-del').forEach((btn) => {
        btn.addEventListener('click', async () => {
          await apiDelete(`/projects/${projectId}/sources/${btn.dataset.id}`);
          await renderSection(homeEl, projectId, 'sources');
        });
      });
      return;
    }
    if (section === 'tasks') {
      const data = await (await apiGet(`/projects/${projectId}/tasks`)).json();
      el.innerHTML = `
        <form id="pjTask" class="pj-form">
          <input type="text" id="pjTaskTitle" placeholder="Task title" maxlength="200" required>
          <button type="submit" class="btn-primary">Add task</button>
        </form>
        <ul>${(data.tasks || []).map((t) => `<li>
          <strong>${escapeHtml(t.title)}</strong> <small>· ${escapeHtml(t.status)}</small>
          <select class="pj-task-status" data-id="${escapeHtml(t.id)}">
            ${['backlog', 'todo', 'in_progress', 'in_review', 'blocked', 'done', 'cancelled'].map((s) => `<option value="${s}"${s === t.status ? ' selected' : ''}>${s}</option>`).join('')}
          </select></li>`).join('')}</ul>`;
      el.querySelector('#pjTask').addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
          await apiPost(`/projects/${projectId}/tasks`, { title: el.querySelector('#pjTaskTitle').value.trim() });
          await renderSection(homeEl, projectId, 'tasks');
        } catch (err) { showError(err.message || 'Could not add task'); }
      });
      el.querySelectorAll('.pj-task-status').forEach((sel) => {
        sel.addEventListener('change', async () => {
          try {
            await apiFetch(`/projects/${projectId}/tasks/${sel.dataset.id}`, {
              method: 'PATCH', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ status: sel.value }),
            });
          } catch (err) { showError(err.message || 'Could not update task'); }
        });
      });
      return;
    }
    if (section === 'chats') {
      const data = await (await apiGet(`/projects/${projectId}/chats`)).json();
      el.innerHTML = `
        <form id="pjChat" class="pj-form">
          <input type="text" id="pjChatTitle" placeholder="Chat title" maxlength="200" required>
          <button type="submit" class="btn-primary">New project chat</button>
        </form>
        <p class="settings-hint">Project chats are listed here and stay scoped to this project.</p>
        <ul>${(data.chats || []).map((c) => `<li><strong>${escapeHtml(c.title)}</strong> <small>· ${escapeHtml(c.model || '')}</small></li>`).join('')}</ul>`;
      el.querySelector('#pjChat').addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
          await apiPost(`/projects/${projectId}/chats`, { title: el.querySelector('#pjChatTitle').value.trim() });
          await renderSection(homeEl, projectId, 'chats');
        } catch (err) { showError(err.message || 'Could not create chat'); }
      });
    }
  } catch (err) { el.innerHTML = `<p class="settings-hint">Could not load section: ${escapeHtml(err.message || '')}</p>`; }
}
