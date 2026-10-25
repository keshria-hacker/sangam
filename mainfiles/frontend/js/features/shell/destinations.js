/**
 * Destination pages — A1 perfect-flow IA (§3).
 *
 * Each destination is one real page. Sub-navigation inside a
 * destination is a segmented control at the top of the content area
 * (never a second sidebar, never another destination opened as a tab).
 * Previously unmounted feature modules are mounted here:
 *   Projects -> projects.js (list + project home)
 *   Studio   -> studio/a6-studio.js families + create/media/design hubs
 *   Code     -> code-agent/spec-qa.js panel + code agent + code graph
 *   Agents   -> agents/taskboard.js + hub + runs + workflows + security
 *   Settings -> memory/privacy.js dashboard (inside Settings → Memory)
 * Research reuses the knowledge tab (search, graph, notebooks, study);
 * Library reuses the library view (skills, MCP, extensions, prompts).
 * Every renderer calls real APIs only; an empty list renders exactly
 * one guided next action, never three competing CTAs.
 */
import { apiFetch, apiGet, apiPost } from '../../shared/http.js';
import { escapeHtml } from '../../shared/utils.js';
import { showToast } from '../../shared/toast.js';
import { registerSectionActivator } from '../tabs/tabs.js';
import { renderProjectsView, renderProjectHome } from '../projects/projects.js';
import { renderTaskBoard } from '../agents/taskboard.js';
import { SPEC_V2_STAGES, specQaPanelHtml, fetchSpecPipeline, fetchQaLevels } from '../code-agent/spec-qa.js';
import { A6_STUDIO_FAMILIES } from '../studio/a6-studio.js';

console.log('[Module] destinations.js loaded');

/** Mount-once segmented page: one control row, one body per segment. */
function segmentedPage(bodyEl, dest, sections, initialId) {
  bodyEl.innerHTML = `
    <div class="dest-page">
      <div class="library-tabs dest-segments" role="tablist" aria-label="${escapeHtml(dest)} sections">
        ${sections.map((s, i) => `
          <button class="library-tab${(s.id === initialId || (!initialId && i === 0)) ? ' active' : ''}" role="tab"
            data-dest-section="${s.id}" aria-selected="${s.id === initialId || (!initialId && i === 0)}">
            ${escapeHtml(s.label)}
          </button>`).join('')}
      </div>
      <div class="dest-bodies"></div>
    </div>`;
  const bodies = bodyEl.querySelector('.dest-bodies');
  const mounted = new Map();
  async function show(id) {
    const sec = sections.find((s) => s.id === id) || sections[0];
    bodyEl.querySelectorAll('[data-dest-section]').forEach((b) => {
      const on = b.dataset.destSection === sec.id;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', String(on));
    });
    let container = mounted.get(sec.id);
    if (!container) {
      container = document.createElement('div');
      container.className = 'dest-section-body';
      bodies.appendChild(container);
      mounted.set(sec.id, container);
      try { await sec.render(container); }
      catch (err) {
        container.innerHTML = `<p class="settings-hint">Could not load ${escapeHtml(sec.label)}: ${escapeHtml(err?.message || String(err))}</p>`;
      }
    }
    bodies.querySelectorAll('.dest-section-body').forEach((el) => {
      el.classList.toggle('hidden', el !== container);
    });
  }
  bodyEl.querySelectorAll('[data-dest-section]').forEach((b) => {
    b.addEventListener('click', () => show(b.dataset.destSection));
  });
  registerSectionActivator(dest, (section) => show(section));
  show(initialId || sections[0].id);
  return show;
}

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------

export async function renderProjectsDestination(bodyEl, opts = {}) {
  if (opts.param) await renderProjectHome(bodyEl, opts.param);
  else await renderProjectsView(bodyEl);
}

// ---------------------------------------------------------------------------
// Studio
// ---------------------------------------------------------------------------

async function renderStudioOverview(bodyEl, showSegment, artifactId) {
  bodyEl.innerHTML = `<div class="studio-overview">
    <p class="settings-hint">Creative + production: documents, slides, diagrams, images, voice, design systems. Video production is not available this round — it is never offered as if it were.</p>
    <div id="stArtifact"></div>
    <h4>Families</h4>
    <div id="stFamilies"><p class="settings-hint">Loading studio catalogue…</p></div>
    <h4>Recent artifacts</h4>
    <div id="stRecent"><p class="settings-hint">Loading…</p></div>
  </div>`;

  if (artifactId) {
    const box = bodyEl.querySelector('#stArtifact');
    try {
      const data = await (await apiGet(`/artifacts/${encodeURIComponent(artifactId)}`)).json();
      const a = data.artifact || data;
      box.innerHTML = `<div class="dest-detail"><strong>${escapeHtml(a.title || a.name || artifactId)}</strong>
        <span class="settings-hint">${escapeHtml(a.kind || a.type || '')}</span></div>`;
    } catch (err) {
      box.innerHTML = `<p class="settings-hint">Could not load artifact ${escapeHtml(artifactId)}: ${escapeHtml(err?.message || '')}</p>`;
    }
  }
  try {
    const cat = await (await apiGet('/studio/catalog')).json();
    const families = cat.families || [];
    bodyEl.querySelector('#stFamilies').innerHTML = `<ul>${families.map((f) => {
      const name = typeof f === 'string' ? f : (f.id || f.name);
      const avail = typeof f === 'object' ? (f.available !== false) : true;
      const engine = f.engine ? ` — ${escapeHtml(f.engine)}` : '';
      const notOffered = (f.not_offered || []).length
        ? ` <span class="settings-hint">(not offered: ${escapeHtml(f.not_offered.join(', '))})</span>` : '';
      const note = f.note ? ` <span class="settings-hint">${escapeHtml(f.note)}</span>` : '';
      return `<li><strong>${escapeHtml(name)}</strong>${engine} — ${avail ? 'available' : 'not available in this build'}${notOffered}${note}</li>`;
    }).join('')}</ul>`;
  } catch {
    bodyEl.querySelector('#stFamilies').innerHTML =
      `<ul>${A6_STUDIO_FAMILIES.map((f) => `<li><strong>${escapeHtml(f)}</strong></li>`).join('')}</ul>
       <p class="settings-hint">Live catalogue status unavailable; families listed from the Studio module.</p>`;
  }
  try {
    const data = await (await apiGet('/artifacts')).json();
    const items = Array.isArray(data) ? data : (data.artifacts || []);
    const recent = bodyEl.querySelector('#stRecent');
    if (!items.length) {
      // Empty state: exactly ONE guided next action.
      recent.innerHTML = `<div class="empty-state"><p>No artifacts yet.</p>
        <button type="button" class="btn-primary" id="stFirstArtifact">Create your first artifact</button></div>`;
      recent.querySelector('#stFirstArtifact')?.addEventListener('click', () => showSegment('create'));
      return;
    }
    recent.innerHTML = `<ul>${items.slice(0, 10).map((a) => `<li><strong>${escapeHtml(a.title || a.name || a.id)}</strong>
      <span class="settings-hint">${escapeHtml(a.kind || a.type || '')}</span></li>`).join('')}</ul>`;
  } catch (err) {
    bodyEl.querySelector('#stRecent').innerHTML =
      `<p class="settings-hint">Could not load artifacts: ${escapeHtml(err?.message || '')}</p>`;
  }
}

export async function renderStudioDestination(bodyEl, opts = {}) {
  const sections = [
    { id: 'overview', label: 'Overview', render: (el) => renderStudioOverview(el, (s) => showFn(s), opts.param) },
    { id: 'create', label: 'Create', render: async (el) => {
      const { renderCreateHub } = await import('../create/hub.js');
      await renderCreateHub(el);
    } },
    { id: 'media', label: 'Media', render: async (el) => {
      const { renderMediaTab } = await import('../media/media.js');
      await renderMediaTab(el);
    } },
    { id: 'design', label: 'Design', render: async (el) => {
      const { renderDesignTab } = await import('../design/design-studio.js');
      renderDesignTab(el);
    } },
  ];
  // Overview's empty-state CTA switches segments via this closure; it
  // only fires on click, after segmentedPage has returned the switcher.
  let showFn = null;
  const show = segmentedPage(bodyEl, 'studio', sections, opts.section || 'overview');
  showFn = show;
}

// ---------------------------------------------------------------------------
// Code
// ---------------------------------------------------------------------------

async function renderSpecSegment(bodyEl) {
  bodyEl.innerHTML = `
    <div class="spec-segment">
      <p class="settings-hint">Spec-driven development: constitution → spec → clarify → plan → checklist → tasks → analyze → implement → verify → converge. TDD evidence (RED + GREEN) is required before implement; GreenContract verification starts at targeted.</p>
      <form id="specCreate" class="pj-create">
        <input type="text" id="specTitle" placeholder="Pipeline title" maxlength="200" required>
        <input type="text" id="specGoal" placeholder="Goal (optional)">
        <button type="submit" class="btn-primary">Create spec pipeline</button>
      </form>
      <div id="specList"><p class="settings-hint">Loading pipelines…</p></div>
      <div id="specDetail"></div>
      <div id="specQaLevels" class="settings-hint"></div>
    </div>`;
  const listEl = bodyEl.querySelector('#specList');
  const detailEl = bodyEl.querySelector('#specDetail');
  async function loadList() {
    try {
      const data = await (await apiGet('/spec-v2')).json();
      const items = Array.isArray(data) ? data : (data.pipelines || []);
      if (!items.length) {
        // Empty state: the create form above is the single guided action.
        listEl.innerHTML = '<p class="settings-hint">No spec pipelines yet. Create one above to start the chain.</p>';
        return;
      }
      listEl.innerHTML = `<ul>${items.map((p) => `<li><button class="btn-secondary btn-sm" data-pid="${escapeHtml(String(p.id))}">${escapeHtml(p.title || p.id)}</button>
        <span class="settings-hint">${escapeHtml(p.current_stage || '')}</span></li>`).join('')}</ul>`;
      listEl.querySelectorAll('[data-pid]').forEach((btn) => {
        btn.addEventListener('click', () => loadPipeline(btn.dataset.pid));
      });
    } catch (err) {
      listEl.innerHTML = `<p class="settings-hint">Could not load pipelines: ${escapeHtml(err?.message || '')}</p>`;
    }
  }
  async function loadPipeline(pid) {
    try {
      const res = await fetchSpecPipeline(apiFetch, pid);
      const pipeline = await res.json();
      detailEl.innerHTML = specQaPanelHtml(pipeline)
        + `<button type="button" class="btn-secondary btn-sm" id="specAdvance">Advance one stage</button>
           <p class="settings-hint" id="specAdvanceOut"></p>`;
      detailEl.querySelector('#specAdvance')?.addEventListener('click', async () => {
        const out = detailEl.querySelector('#specAdvanceOut');
        try {
          await apiPost(`/spec-v2/${encodeURIComponent(pid)}/advance`, {});
          out.textContent = 'Advanced. Reloading…';
          await loadPipeline(pid);
          await loadList();
        } catch (err) {
          out.textContent = err?.message || String(err);
        }
      });
    } catch (err) {
      detailEl.innerHTML = `<p class="settings-hint">Could not load pipeline: ${escapeHtml(err?.message || '')}</p>`;
    }
  }
  bodyEl.querySelector('#specCreate')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const title = bodyEl.querySelector('#specTitle').value.trim();
    if (!title) return;
    try {
      await apiPost('/spec-v2', { title, goal: bodyEl.querySelector('#specGoal').value.trim() });
      showToast({ type: 'success', message: 'Spec pipeline created.' });
      await loadList();
    } catch (err) {
      showToast({ type: 'error', title: 'Create failed', message: err?.message || String(err) });
    }
  });
  try {
    const res = await fetchQaLevels(apiFetch);
    const levels = await res.json();
    bodyEl.querySelector('#specQaLevels').textContent =
      `GreenContract levels: ${(levels.levels || []).map((l) => l.name || l).join(', ') || 'see /api/qa/levels'}. Stages: ${SPEC_V2_STAGES.join(' → ')}.`;
  } catch { /* levels line is informational only */ }
  await loadList();
}

async function renderGraphSegment(bodyEl) {
  bodyEl.innerHTML = `
    <div class="graph-segment">
      <p class="settings-hint">Code map search (grep + graph, graph+grep ranked first). Python, JavaScript/TypeScript, Go, Rust, Java extractors only — no broader language claim.</p>
      <div class="kn-mem-controls">
        <input type="text" id="cgQ" class="provider-key-input" placeholder="Search symbols or code…" aria-label="Code search query" style="flex:1">
        <button type="button" class="btn-secondary" id="cgSearch">Search</button>
      </div>
      <div id="cgResults" class="settings-hint">Type a query above — search is the guided action here.</div>
    </div>`;
  bodyEl.querySelector('#cgSearch')?.addEventListener('click', async () => {
    const q = bodyEl.querySelector('#cgQ').value.trim();
    const out = bodyEl.querySelector('#cgResults');
    if (!q) { out.textContent = 'Type a query first.'; return; }
    out.textContent = 'Searching…';
    try {
      const data = await (await apiGet(`/code-graph/search-v2?q=${encodeURIComponent(q)}`)).json();
      if (data.error) { out.textContent = data.error; return; }
      const hits = data.merged || data.graph || [];
      out.innerHTML = hits.length
        ? `<ul>${hits.slice(0, 20).map((h) => `<li><code>${escapeHtml(h.symbol || h.name || '')}</code> ${escapeHtml(h.file || '')}${h.line ? `:${h.line}` : ''} <span class="settings-hint">${escapeHtml(h.source || '')}</span></li>`).join('')}</ul>`
        : '<p class="settings-hint">No matches.</p>';
    } catch (err) {
      out.textContent = `Search failed: ${err?.message || err}`;
    }
  });
}

export async function renderCodeDestination(bodyEl, opts = {}) {
  const sections = [
    { id: 'agent', label: 'Agent', render: async (el) => {
      const { renderCodePage } = await import('../code-agent/code-agent.js');
      await renderCodePage(el);
    } },
    { id: 'spec', label: 'Spec & QA', render: renderSpecSegment },
    { id: 'graph', label: 'Code map', render: renderGraphSegment },
    { id: 'engineering', label: 'Engineering', render: async (el) => {
      const { renderEngineeringPage } = await import('../work/engineering.js');
      await renderEngineeringPage(el);
    } },
  ];
  return segmentedPage(bodyEl, 'code', sections, opts.section || 'agent');
}

// ---------------------------------------------------------------------------
// Research
// ---------------------------------------------------------------------------

export async function renderResearchDestination(bodyEl, opts = {}) {
  // One page (the knowledge tab: search, graph, notebooks, study) with
  // a segmented control on top that scrolls to the section. Sections
  // are parts of one destination, not separate destinations.
  bodyEl.innerHTML = `
    <div class="dest-page">
      <div class="library-tabs dest-segments" role="tablist" aria-label="Research sections">
        <button class="library-tab active" role="tab" data-dest-section="explore" aria-selected="true">Search & Graph</button>
        <button class="library-tab" role="tab" data-dest-section="notebooks" aria-selected="false">Notebooks</button>
        <button class="library-tab" role="tab" data-dest-section="study" aria-selected="false">Study</button>
      </div>
      <div class="dest-bodies"><div class="dest-section-body" id="researchBody"></div></div>
    </div>`;
  const content = bodyEl.querySelector('#researchBody');
  const scrollTo = (section) => {
    bodyEl.querySelectorAll('[data-dest-section]').forEach((b) => {
      const on = b.dataset.destSection === section;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', String(on));
    });
    let target = null;
    if (section === 'explore') target = content.querySelector('#knSearch');
    else if (section === 'notebooks') target = content.querySelector('#nbList')?.closest('.kn-section');
    else if (section === 'study') target = content.querySelector('[data-study-section]');
    (target || content).scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  bodyEl.querySelectorAll('[data-dest-section]').forEach((b) => {
    b.addEventListener('click', () => scrollTo(b.dataset.destSection));
  });
  registerSectionActivator('research', (section) => scrollTo(section));
  const { renderKnowledgeTab } = await import('../knowledge/knowledge.js');
  await renderKnowledgeTab(content);
  if (opts.section) scrollTo(opts.section);
  if (opts.param) {
    // /research/:notebook lands on the Notebooks section; the notebook
    // itself is opened from that section's list (no fake detail view).
    scrollTo('notebooks');
  }
}

// ---------------------------------------------------------------------------
// Agents
// ---------------------------------------------------------------------------

export async function renderAgentsDestination(bodyEl, opts = {}) {
  const sections = [
    { id: 'hub', label: 'Hub', render: async (el) => {
      const { renderAgentsPage } = await import('../agents/hub.js');
      await renderAgentsPage(el);
    } },
    { id: 'tasks', label: 'Task board', render: (el) => renderTaskBoard(el, { taskId: opts.param || null }) },
    { id: 'run-history', label: 'Run History', render: async (el) => {
      const { renderRunsTab } = await import('../runs/runs.js');
      renderRunsTab(el);
    } },
    { id: 'workflows', label: 'Workflows', render: async (el) => {
      const { renderWorkflowsTab } = await import('../workflows/workflows.js');
      await renderWorkflowsTab(el);
    } },
    { id: 'security', label: 'Security', render: async (el) => {
      const { renderSecurityPage } = await import('../security/security.js');
      await renderSecurityPage(el);
    } },
  ];
  // /agents/:id is a task: land on the Task board segment for it.
  const initial = opts.param ? 'tasks' : (opts.section || 'hub');
  return segmentedPage(bodyEl, 'agents', sections, initial);
}

// ---------------------------------------------------------------------------
// Library
// ---------------------------------------------------------------------------

export async function renderLibraryDestination(bodyEl, opts = {}) {
  const { renderLibrary } = await import('../library/library.js');
  renderLibrary(bodyEl);
  registerSectionActivator('library', (section) => {
    const btn = bodyEl.querySelector(`[data-libtab="${section}"]`);
    if (btn) btn.click();
  });
  if (opts.section) {
    const btn = bodyEl.querySelector(`[data-libtab="${opts.section}"]`);
    if (btn) btn.click();
  }
}

// ---------------------------------------------------------------------------
// Settings (wrapper: the page itself owns categories + search)
// ---------------------------------------------------------------------------

export async function renderSettingsDestination(bodyEl, opts = {}) {
  const { renderSettingsPage } = await import('../settings/settings_page.js');
  // /settings/:section is a category id; ?section= is a segment alias.
  renderSettingsPage(bodyEl, { section: opts.param || opts.section || 'general' });
}
