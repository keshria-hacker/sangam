/**
 * Knowledge view — unified knowledge graph, MCP tools, memory browser (Sangam-native, Phase 3).
 *
 * Sections:
 *   1. Header: search (debounced), stats chips, "Include code" toggle
 *   2. Graph: SVG with simple force simulation (no external libs)
 *   3. Detail panel: node metadata + related nodes
 *   4. MCP tools link (enable/disable lives in Library)
 *   5. Memory browser
 */
import { apiFetch } from '../../shared/http.js';
import { escapeHtml } from '../../shared/utils.js';
import { showToast } from '../../shared/toast.js';

console.log('[Module] knowledge.js loaded');

const TYPE_COLORS = {
  memory: '#a855f7',
  document: '#3b82f6',
  code: '#22c55e',
  chat: '#f59e0b',
};

let graphData = { nodes: [], edges: [], stats: {} };
let includeCode = false;
let selectedNode = null;
let zoom = 1;
let searchTimer = null;

export async function renderKnowledgeTab(bodyEl) {
  bodyEl.innerHTML = `
    <div class="knowledge-view">
      <div class="kn-header">
        <div class="kn-search-wrap">
          <i class="fa-solid fa-magnifying-glass"></i>
          <input type="text" id="knSearch" placeholder="Search memories, documents, chats…" autocomplete="off" aria-label="Search memories, documents, chats">
          <div class="kn-search-results hidden" id="knSearchResults"></div>
        </div>
        <div class="kn-stats" id="knStats"></div>
        <label class="kn-toggle">
          <input type="checkbox" id="knIncludeCode"> Include code graph
        </label>
      </div>
      <div class="kn-graph-row">
        <div class="kn-graph-wrap">
          <div class="kn-graph-controls">
            <button class="icon-btn" id="knZoomIn" title="Zoom in"><i class="fa-solid fa-plus"></i></button>
            <button class="icon-btn" id="knZoomOut" title="Zoom out"><i class="fa-solid fa-minus"></i></button>
            <button class="icon-btn" id="knZoomReset" title="Reset zoom"><i class="fa-solid fa-maximize"></i></button>
          </div>
          <svg id="knGraph" class="kn-graph" role="img" aria-label="Knowledge graph"></svg>
          <div class="kn-tooltip hidden" id="knTooltip"></div>
        </div>
        <div class="kn-detail hidden" id="knDetail"></div>
      </div>
      <div id="knGraphEmpty"></div>
      <section class="kn-section">
        <h3><i class="fa-solid fa-plug"></i> MCP tools</h3>
        <p class="settings-hint">MCP servers connect outside tools to Sangam. Manage them in Library → MCP Servers.</p>
        <div id="knMcp"></div>
      </section>
      <section class="kn-section">
        <h3><i class="fa-solid fa-brain"></i> Memories</h3>
        <div class="kn-mem-controls">
          <select id="knMemView" class="provider-key-input" aria-label="Memory view">
            <option value="list">List</option>
            <option value="rooms">Groups</option>
          </select>
          <select id="knMemKind" class="provider-key-input" aria-label="Memory kind">
            <option value="">All kinds</option>
            <option value="episodic">Events</option>
            <option value="semantic">Facts</option>
            <option value="procedural">How-tos</option>
          </select>
          <button class="btn-secondary" id="knTidy"><i class="fa-solid fa-broom"></i> Clean up old memories</button>
          <button class="btn-secondary" id="knExport"><i class="fa-solid fa-download"></i> Export</button>
        </div>
        <div id="knMemories" class="kn-mem-list"></div>
      </section>
      <section class="kn-section">
        <h3><i class="fa-solid fa-magnifying-glass"></i> Retrieve documents</h3>
        <p class="settings-hint">Searches your documents by meaning and by exact words, with citations.</p>
        <div class="kn-mem-controls">
          <input type="text" id="knRetrieveQ" class="provider-key-input" placeholder="Ask about your documents…" aria-label="Retrieve documents query" style="flex:1">
          <button class="btn-secondary" id="knRetrieveBtn">Retrieve</button>
        </div>
        <div id="knRetrieveResults" class="kn-mem-list"></div>
      </section>
      <section class="kn-section" data-study-section>
        <h3><i class="fa-solid fa-graduation-cap"></i> Study</h3>
        <p class="settings-hint">Interactive lessons and a Socratic tutor, over what you know.</p>
        <div id="knStudyBody"><p class="settings-hint">Loading…</p></div>
      </section>
      <section class="kn-section">
        <h3><i class="fa-solid fa-globe"></i> Add from URL</h3>
        <p class="settings-hint">Ingest a public web page as a document. Only public http/https pages are fetched; private addresses and redirects are refused.</p>
        <div class="kn-mem-controls">
          <input type="url" id="knIngestUrl" class="provider-key-input" placeholder="https://example.com/article" aria-label="URL to ingest" style="flex:1">
          <button class="btn-secondary" id="knIngestBtn">Ingest page</button>
        </div>
        <div id="knIngestStatus" class="settings-hint"></div>
      </section>
      <section class="kn-section">
        <h3><i class="fa-solid fa-book"></i> Notebooks</h3>
        <p class="settings-hint">Group sources, notes, and transforms per project. Retrieval honours each source's context mode.</p>
        <div class="kn-mem-controls">
          <input type="text" id="nbName" class="provider-key-input" placeholder="Notebook name" aria-label="Notebook name">
          <input type="text" id="nbDesc" class="provider-key-input" placeholder="Description (optional)" aria-label="Notebook description" style="flex:1">
          <button class="btn-secondary" id="nbCreateBtn">Create notebook</button>
        </div>
        <div id="nbList" class="kn-mem-list"></div>
        <div id="nbDetail"></div>
      </section>
      <section class="kn-section">
        <h3><i class="fa-solid fa-brain"></i> Memory tools</h3>
        <p class="settings-hint">On-demand AI fact-finding, reflection over recalled memories, entity timelines, verbatim transcripts, and memory updates. AI tools need a configured model.</p>
        <details class="advanced-section" id="knMemToolsAdvanced">
          <summary>Advanced memory tools</summary>
        <div class="kn-mem-controls">
          <textarea id="memv2ExtractText" class="provider-key-input" placeholder="Paste text to extract durable facts from…" aria-label="Text to extract facts from" style="flex:1"></textarea>
          <button class="btn-secondary" id="memv2ExtractBtn">Extract facts</button>
        </div>
        <div id="memv2ExtractResults" class="kn-mem-list"></div>
        <div class="kn-mem-controls">
          <input type="text" id="memv2ReflectQ" class="provider-key-input" placeholder="Reflect on… e.g. what do I prefer?" aria-label="Reflect query" style="flex:1">
          <button class="btn-secondary" id="memv2ReflectBtn">Reflect</button>
        </div>
        <div id="memv2ReflectResults" class="kn-mem-list"></div>
        <div class="kn-mem-controls">
          <input type="text" id="memv2EntityName" class="provider-key-input" placeholder="Entity name" aria-label="Entity name">
          <button class="btn-secondary" id="memv2TimelineBtn">Show timeline</button>
        </div>
        <div id="memv2Timeline" class="kn-mem-list"></div>
        <div class="kn-mem-controls">
          <input type="text" id="memv2TranscriptChat" class="provider-key-input" placeholder="Chat id (blank = all)" aria-label="Transcript chat id" style="flex:1">
          <button class="btn-secondary" id="memv2TranscriptBtn">List transcripts</button>
        </div>
        <div id="memv2TranscriptList" class="kn-mem-list"></div>
        <div class="kn-mem-controls">
          <input type="text" id="memv2UpdateId" class="provider-key-input" placeholder="Memory id" aria-label="Memory id to update">
          <input type="text" id="memv2UpdateContent" class="provider-key-input" placeholder="New content (blank = keep)" aria-label="New memory content" style="flex:1">
          <input type="text" id="memv2UpdateImportance" class="provider-key-input" placeholder="Importance 0–1" aria-label="New importance">
          <input type="text" id="memv2UpdateRoom" class="provider-key-input" placeholder="Group" aria-label="New group">
          <input type="text" id="memv2UpdateDrawer" class="provider-key-input" placeholder="Folder" aria-label="New folder">
          <button class="btn-secondary" id="memv2UpdateBtn">Update memory</button>
        </div>
        <div id="memv2UpdateStatus" class="settings-hint"></div>
        </details>
      </section>
      <section class="kn-section">
        <h3><i class="fa-solid fa-flask"></i> Memory &amp; Research</h3>
        <p class="settings-hint">Consolidated beliefs backed by evidence, deep-research jobs with cited reports, workspace packs, and a catalogue of MCP servers and AI app patterns. Nothing here installs or runs remote code on its own.</p>
        <h4>Observations</h4>
        <p class="settings-hint">A belief Sangam holds with its evidence attached. Supporting evidence strengthens it; contradicting evidence weakens it without erasing history.</p>
        <div class="kn-mem-controls">
          <input type="text" id="mrObsClaim" class="provider-key-input" placeholder="A belief, e.g. I prefer concise answers" aria-label="Observation claim" style="flex:1">
          <select id="mrObsKind" class="provider-key-input" aria-label="Observation kind">
            <option value="fact">Fact</option>
            <option value="decision">Decision</option>
            <option value="preference">Preference</option>
            <option value="correction">Correction</option>
          </select>
          <button class="btn-secondary" id="mrObsAddBtn">Save observation</button>
        </div>
        <div id="mrObsList" class="kn-mem-list"></div>
        <h4>Deep research</h4>
        <p class="settings-hint">Ask a question; Sangam searches, curates sources, and writes a report. A report only includes claims that cite a source actually retrieved.</p>
        <div class="kn-mem-controls">
          <input type="text" id="mrResearchQ" class="provider-key-input" placeholder="What should Sangam research?" aria-label="Research question" style="flex:1">
          <button class="btn-secondary" id="mrResearchBtn">Start research</button>
        </div>
        <div id="mrResearchStatus" class="kn-mem-list"></div>
        <details class="advanced-section">
          <summary>Reference catalogue</summary>
        <p class="settings-hint">Documented MCP servers and AI app patterns, with risk notes and the Sangam feature that already covers each pattern. Entries are reference only — they never install themselves.</p>
        <div class="kn-mem-controls">
          <input type="text" id="mrCatQ" class="provider-key-input" placeholder="Search the catalogue…" aria-label="Catalogue search" style="flex:1">
          <button class="btn-secondary" id="mrCatBtn">Search</button>
        </div>
        <div id="mrCatList" class="kn-mem-list"></div>
        </details>
        <h4>Workspace pack</h4>
        <p class="settings-hint">Bundle a folder inside your workspace into one AI-ready text pack (file tree + contents, token estimate). Files that look like credentials are left out and listed, never included.</p>
        <div class="kn-mem-controls">
          <input type="text" id="mrPackPath" class="provider-key-input" placeholder="Folder inside the workspace (blank = whole workspace)" aria-label="Pack path" style="flex:1">
          <button class="btn-secondary" id="mrPackBtn">Build pack</button>
        </div>
        <div id="mrPackStatus" class="kn-mem-list"></div>
        <h4>Memory notes</h4>
        <p class="settings-hint">Dated, typed Markdown notes in one browsable folder — memory you can read and correct by hand.</p>
        <div id="mrNotesList" class="kn-mem-list"></div>
      </section>
    </div>`;

  // Batch 1: Study section (Learn) + section activator for palette/aliases.
  import('../tabs/tabs.js').then((m) => m.registerSectionActivator('knowledge', (section) => {
    if (section === 'study') {
      bodyEl.querySelector('[data-study-section]')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  })).catch(() => {});
  import('../learn/learn.js').then((m) => {
    const studyBody = bodyEl.querySelector('#knStudyBody');
    if (!studyBody) return;
    studyBody.innerHTML = '';
    if (m.renderLearnTab) m.renderLearnTab(studyBody);
    else studyBody.innerHTML = '<p class="settings-hint">Study unavailable.</p>';
  }).catch(() => {
    const studyBody = bodyEl.querySelector('#knStudyBody');
    if (studyBody) studyBody.innerHTML = '<p class="settings-hint">Study unavailable.</p>';
  });

  // Batch 4: Notebooks + Memory tools sections (same dynamic-import
  // pattern as the Study section above).
  import('./notebooks.js').then((m) => {
    if (m.initNotebooks) m.initNotebooks(bodyEl);
    if (m.initMemoryTools) m.initMemoryTools(bodyEl);
  }).catch(() => {
    const nbList = bodyEl.querySelector('#nbList');
    if (nbList) nbList.innerHTML = '<p class="settings-hint">Notebooks unavailable.</p>';
  });

  // Wire search
  const searchInput = bodyEl.querySelector('#knSearch');
  searchInput.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => doSearch(bodyEl), 300);
  });
  searchInput.addEventListener('blur', () => {
    setTimeout(() => bodyEl.querySelector('#knSearchResults')?.classList.add('hidden'), 200);
  });

  // Wire include-code toggle
  bodyEl.querySelector('#knIncludeCode').addEventListener('change', (e) => {
    includeCode = e.target.checked;
    loadGraph(bodyEl);
  });

  // Wire zoom
  bodyEl.querySelector('#knZoomIn').addEventListener('click', () => { zoom = Math.min(zoom * 1.2, 4); applyZoom(bodyEl); });
  bodyEl.querySelector('#knZoomOut').addEventListener('click', () => { zoom = Math.max(zoom / 1.2, 0.4); applyZoom(bodyEl); });
  bodyEl.querySelector('#knZoomReset').addEventListener('click', () => { zoom = 1; applyZoom(bodyEl); });

  // Batch 9: Memory & Research section.
  initMemoryResearch(bodyEl);

  // Wire memory browser
  bodyEl.querySelector('#knMemKind').addEventListener('change', () => loadMemories(bodyEl));
  bodyEl.querySelector('#knMemView').addEventListener('change', () => loadMemories(bodyEl));
  bodyEl.querySelector('#knTidy').addEventListener('click', () => tidyMemories(bodyEl));
  bodyEl.querySelector('#knExport').addEventListener('click', () => exportMemories());
  bodyEl.querySelector('#knRetrieveBtn').addEventListener('click', () => retrieveDocuments(bodyEl));
  bodyEl.querySelector('#knRetrieveQ').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') retrieveDocuments(bodyEl);
  });
  bodyEl.querySelector('#knIngestBtn').addEventListener('click', () => ingestPage(bodyEl));

  await Promise.all([loadGraph(bodyEl), loadMcp(bodyEl), loadMemories(bodyEl)]);
}

// --- Graph ---------------------------------------------------------------

async function loadGraph(bodyEl) {
  const svg = bodyEl.querySelector('#knGraph');
  svg.innerHTML = '<text x="50%" y="50%" text-anchor="middle" class="kn-loading">Loading graph…</text>';
  try {
    const data = await (await apiFetch(`/knowledge/graph?include_code=${includeCode}&max_nodes=200`)).json();
    graphData = data;
    renderStats(bodyEl);
    layoutAndRender(bodyEl);
  } catch (err) {
    svg.innerHTML = '<text x="50%" y="50%" text-anchor="middle" class="kn-loading">Could not load graph.</text>';
  }
}

function renderStats(bodyEl) {
  const s = graphData.stats || {};
  bodyEl.querySelector('#knStats').innerHTML = ['memories', 'documents', 'code', 'chats'].map((t) => `
    <span class="kn-chip" style="--chip-color:${TYPE_COLORS[t]}">
      <i class="fa-solid fa-circle"></i> ${s[t] || 0} ${t}
    </span>`).join('');
}

/** Simple force-directed layout: 30 iterations of repulsion + spring forces. */
function forceLayout(nodes, edges, width, height) {
  const pos = new Map();
  const n = nodes.length;
  // Initial: circle
  nodes.forEach((nd, i) => {
    const a = (i / Math.max(n, 1)) * Math.PI * 2;
    pos.set(nd.id, { x: width / 2 + Math.cos(a) * width * 0.35, y: height / 2 + Math.sin(a) * height * 0.35 });
  });
  const adj = new Map();
  for (const e of edges) {
    if (!adj.has(e.from)) adj.set(e.from, []);
    if (!adj.has(e.to)) adj.set(e.to, []);
    adj.get(e.from).push(e.to);
    adj.get(e.to).push(e.from);
  }
  for (let iter = 0; iter < 30; iter++) {
    const forces = new Map();
    for (const nd of nodes) forces.set(nd.id, { x: 0, y: 0 });
    // Repulsion
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = pos.get(nodes[i].id), b = pos.get(nodes[j].id);
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 1; }
        const f = 4000 / d2;
        const d = Math.sqrt(d2);
        const fx = (dx / d) * f, fy = (dy / d) * f;
        forces.get(nodes[i].id).x += fx; forces.get(nodes[i].id).y += fy;
        forces.get(nodes[j].id).x -= fx; forces.get(nodes[j].id).y -= fy;
      }
    }
    // Springs
    for (const e of edges) {
      const a = pos.get(e.from), b = pos.get(e.to);
      if (!a || !b) continue;
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - 90) * 0.02;
      const fx = (dx / d) * f, fy = (dy / d) * f;
      forces.get(e.from).x += fx; forces.get(e.from).y += fy;
      forces.get(e.to).x -= fx; forces.get(e.to).y -= fy;
    }
    // Apply with damping + bounds
    for (const nd of nodes) {
      const p = pos.get(nd.id), f = forces.get(nd.id);
      p.x = Math.min(Math.max(p.x + f.x * 0.5, 30), width - 30);
      p.y = Math.min(Math.max(p.y + f.y * 0.5, 30), height - 30);
    }
  }
  return pos;
}

function layoutAndRender(bodyEl) {
  const svg = bodyEl.querySelector('#knGraph');
  const wrap = bodyEl.querySelector('.kn-graph-wrap');
  const width = wrap.clientWidth || 800;
  const height = 480;
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.innerHTML = '';

  const nodes = graphData.nodes || [];
  const edges = graphData.edges || [];
  const emptyBox = bodyEl.querySelector('#knGraphEmpty');
  if (!nodes.length) {
    svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" class="kn-loading">No knowledge yet — chat, upload files, or save memories.</text>`;
    if (emptyBox) {
      emptyBox.innerHTML = `<button type="button" class="btn-primary btn-sm" id="knEmptyAdd">Add your first document</button>`;
      emptyBox.querySelector('#knEmptyAdd').addEventListener('click', () => {
        const input = bodyEl.querySelector('#knIngestUrl');
        input?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        input?.focus();
      });
    }
    return;
  }
  if (emptyBox) emptyBox.innerHTML = '';

  const pos = forceLayout(nodes, edges, width, height);
  const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
  g.setAttribute('id', 'knGraphG');
  svg.appendChild(g);

  // Edges
  for (const e of edges) {
    const a = pos.get(e.from), b = pos.get(e.to);
    if (!a || !b) continue;
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', a.x); line.setAttribute('y1', a.y);
    line.setAttribute('x2', b.x); line.setAttribute('y2', b.y);
    // Phase 7: provenance styling — EXTRACTED solid, INFERRED dashed, AMBIGUOUS dotted
    const prov = (e.provenance || 'EXTRACTED').toUpperCase();
    let cls = 'kn-edge';
    if (prov === 'INFERRED') cls += ' kn-edge-inferred';
    else if (prov === 'AMBIGUOUS') cls += ' kn-edge-ambiguous';
    line.setAttribute('class', cls);
    const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
    title.textContent = `${prov}${e.source ? ` · ${e.source}` : ''}`;
    line.appendChild(title);
    // Click edge to see provenance in the detail panel
    line.style.cursor = 'pointer';
    line.addEventListener('click', (ev) => {
      ev.stopPropagation();
      showEdgeDetail(bodyEl, e);
    });
    g.appendChild(line);
  }

  // Nodes
  const tooltip = bodyEl.querySelector('#knTooltip');
  for (const nd of nodes) {
    const p = pos.get(nd.id);
    const color = TYPE_COLORS[nd.type] || '#888';
    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', p.x); circle.setAttribute('cy', p.y);
    circle.setAttribute('r', 9);
    circle.setAttribute('fill', color);
    circle.setAttribute('class', 'kn-node' + (selectedNode?.id === nd.id ? ' selected' : ''));
    circle.style.cursor = 'pointer';
    circle.addEventListener('click', () => { selectedNode = nd; renderDetail(bodyEl); layoutAndRender(bodyEl); });
    circle.addEventListener('mouseenter', (ev) => {
      tooltip.textContent = nd.label || nd.id;
      tooltip.classList.remove('hidden');
      const r = wrap.getBoundingClientRect();
      tooltip.style.left = `${ev.clientX - r.left + 12}px`;
      tooltip.style.top = `${ev.clientY - r.top - 8}px`;
    });
    circle.addEventListener('mouseleave', () => tooltip.classList.add('hidden'));
    g.appendChild(circle);

    const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', p.x + 13); text.setAttribute('y', p.y + 4);
    text.setAttribute('class', 'kn-label');
    text.textContent = (nd.label || '').slice(0, 28);
    g.appendChild(text);
  }
  applyZoom(bodyEl);
}

function applyZoom(bodyEl) {
  const g = bodyEl.querySelector('#knGraphG');
  if (!g) return;
  const svg = bodyEl.querySelector('#knGraph');
  const vb = svg.viewBox.baseVal;
  const cx = vb.width / 2, cy = vb.height / 2;
  g.setAttribute('transform', `translate(${cx},${cy}) scale(${zoom}) translate(${-cx},${-cy})`);
}

function renderDetail(bodyEl) {
  const panel = bodyEl.querySelector('#knDetail');
  if (!selectedNode) { panel.classList.add('hidden'); return; }
  panel.classList.remove('hidden');
  const nd = selectedNode;
  const meta = nd.metadata || {};
  const related = (graphData.edges || [])
    .filter((e) => e.from === nd.id || e.to === nd.id)
    .map((e) => {
      const otherId = e.from === nd.id ? e.to : e.from;
      return { ...(graphData.nodes || []).find((n) => n.id === otherId), edgeType: e.type };
    })
    .filter((r) => r.id);

  const metaRows = Object.entries(meta)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]) => `<div class="insp-row"><span>${escapeHtml(k)}</span><strong>${escapeHtml(String(v).slice(0, 80))}</strong></div>`)
    .join('');

  panel.innerHTML = `
    <div class="kn-detail-head">
      <span class="kn-chip" style="--chip-color:${TYPE_COLORS[nd.type] || '#888'}">
        <i class="fa-solid fa-circle"></i> ${escapeHtml(nd.type || '')}
      </span>
      <button class="icon-btn" id="knDetailClose" aria-label="Close"><i class="fa-solid fa-xmark"></i></button>
    </div>
    <h4>${escapeHtml(nd.label || nd.id)}</h4>
    ${metaRows ? `<div class="kn-meta">${metaRows}</div>` : ''}
    ${related.length ? `<h5>Related (${related.length})</h5>
      <ul class="kn-related">${related.slice(0, 12).map((r) => `
        <li><button class="kn-related-btn" data-id="${escapeHtml(r.id)}">
          <i class="fa-solid fa-circle" style="color:${TYPE_COLORS[r.type] || '#888'}"></i>
          ${escapeHtml((r.label || r.id).slice(0, 40))}
          <small>${escapeHtml(r.edgeType || '')}</small>
        </button></li>`).join('')}</ul>` : '<p class="settings-hint">No connections.</p>'}`;

  panel.querySelector('#knDetailClose').addEventListener('click', () => {
    selectedNode = null;
    panel.classList.add('hidden');
    layoutAndRender(bodyEl);
  });
  panel.querySelectorAll('.kn-related-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const target = (graphData.nodes || []).find((n) => n.id === btn.dataset.id);
      if (target) { selectedNode = target; renderDetail(bodyEl); layoutAndRender(bodyEl); }
    });
  });
}

/** Phase 7: show edge provenance in the detail panel. */
function showEdgeDetail(bodyEl, edge) {
  const panel = bodyEl.querySelector('#knDetail');
  if (!panel) return;
  panel.classList.remove('hidden');
  const prov = (edge.provenance || 'EXTRACTED').toUpperCase();
  const provClass = prov === 'INFERRED' ? 'kn-prov-inferred' : prov === 'AMBIGUOUS' ? 'kn-prov-ambiguous' : 'kn-prov-extracted';
  panel.innerHTML = `
    <div class="kn-detail-head">
      <span class="kn-chip ${provClass}">${escapeHtml(prov)}</span>
      <button class="icon-btn" id="knDetailClose" aria-label="Close"><i class="fa-solid fa-xmark"></i></button>
    </div>
    <h4>Connection</h4>
    <div class="kn-meta">
      <div class="insp-row"><span>From</span><strong>${escapeHtml(edge.from || '')}</strong></div>
      <div class="insp-row"><span>To</span><strong>${escapeHtml(edge.to || '')}</strong></div>
      <div class="insp-row"><span>Type</span><strong>${escapeHtml(edge.type || edge.label || '')}</strong></div>
      <div class="insp-row"><span>Provenance</span><strong>${escapeHtml(prov)}</strong></div>
      ${edge.source ? `<div class="insp-row"><span>Source</span><strong>${escapeHtml(edge.source)}</strong></div>` : ''}
    </div>
    <p class="settings-hint">${prov === 'EXTRACTED' ? 'Directly extracted from data.' : prov === 'INFERRED' ? 'Inferred by heuristic — may be wrong.' : 'Uncertain — verify before trusting.'}</p>`;
  panel.querySelector('#knDetailClose').addEventListener('click', () => {
    panel.classList.add('hidden');
  });
}

// --- Search -----------------------------------------------------------------

async function doSearch(bodyEl) {
  const q = bodyEl.querySelector('#knSearch').value.trim();
  const box = bodyEl.querySelector('#knSearchResults');
  if (!q) { box.classList.add('hidden'); return; }
  try {
    const data = await (await apiFetch(`/knowledge/search?q=${encodeURIComponent(q)}`)).json();
    const results = data.results || [];
    if (!results.length) {
      box.innerHTML = '<div class="kn-search-empty">No results.</div>';
    } else {
      const byType = {};
      for (const r of results) {
        (byType[r.type] = byType[r.type] || []).push(r);
      }
      box.innerHTML = Object.entries(byType).map(([type, items]) => `
        <div class="kn-search-group">
          <div class="kn-search-type" style="color:${TYPE_COLORS[type] || '#888'}">${escapeHtml(type)}s</div>
          ${items.map((r) => `
            <button class="kn-search-item" data-type="${escapeHtml(r.type)}" data-id="${escapeHtml(r.id)}">
              ${escapeHtml(r.label || r.id)}
            </button>`).join('')}
        </div>`).join('');
      box.querySelectorAll('.kn-search-item').forEach((btn) => {
        btn.addEventListener('click', () => {
          openSearchResult(btn.dataset.type, btn.dataset.id, bodyEl);
          box.classList.add('hidden');
        });
      });
    }
    box.classList.remove('hidden');
  } catch {
    box.classList.add('hidden');
  }
}

async function openSearchResult(type, id, bodyEl) {
  if (type === 'chat') {
    const { openChat } = await import('../sidebar/sidebar.js');
    openChat(id);
  } else if (type === 'memory') {
    // Select the node in the graph if present
    const nd = (graphData.nodes || []).find((n) => n.id === `mem:${id}` || n.id === id);
    if (nd) { selectedNode = nd; renderDetail(bodyEl); layoutAndRender(bodyEl); }
    else showToast({ type: 'info', message: 'Memory found — enable "Include code" or reload to see it in the graph.' });
  } else {
    showToast({ type: 'info', title: `${type}: ${id}` });
  }
}

// --- MCP tools ---------------------------------------------------------------
// Knowledge no longer duplicates Library's enable/disable list: Library →
// MCP Servers is the single home for that. This section is only a link there.

function loadMcp(bodyEl) {
  const box = bodyEl.querySelector('#knMcp');
  if (!box) return;
  box.innerHTML = `<button class="btn-secondary" id="knMcpOpenLibrary" type="button">
    <i class="fa-solid fa-plug"></i> Open MCP Servers in Library
  </button>`;
  box.querySelector('#knMcpOpenLibrary').addEventListener('click', () => {
    import('../tabs/tabs.js').then((m) => m.showToolSection('library', 'mcp')).catch(() => {});
  });
}

// --- Memory browser ------------------------------------------------------------

/** Display labels for memory kinds (backend keys / option values unchanged). */
const KIND_LABELS = { episodic: 'Events', semantic: 'Facts', procedural: 'How-tos' };
function kindLabel(kind) { return KIND_LABELS[kind] || kind || ''; }

/** "Start a chat" button for the "No memories yet" empty states: back to Chat. */
function wireEmptyChatButton(box) {
  box.querySelector('.kn-empty-chat')?.addEventListener('click', () => {
    import('../tabs/tabs.js').then((m) => m.switchTab('main')).catch(() => {});
  });
}

/**
 * Prefill the Update-memory form (inside "Advanced memory tools") from a
 * memory row, so the user never has to type a memory id from elsewhere.
 * Form fields and the backend call in updateMemory() are unchanged.
 */
function prefillUpdateForm(bodyEl, m) {
  const advanced = bodyEl.querySelector('#knMemToolsAdvanced');
  if (advanced) advanced.open = true;
  const set = (id, val) => { const el = bodyEl.querySelector(`#${id}`); if (el) el.value = val ?? ''; };
  set('memv2UpdateId', m.id || '');
  set('memv2UpdateContent', m.content || '');
  set('memv2UpdateImportance', m.importance != null ? String(m.importance) : '');
  set('memv2UpdateRoom', m.room || '');
  set('memv2UpdateDrawer', m.drawer || '');
  const contentEl = bodyEl.querySelector('#memv2UpdateContent');
  contentEl?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  contentEl?.focus();
}

async function loadMemories(bodyEl) {
  const box = bodyEl.querySelector('#knMemories');
  const kind = bodyEl.querySelector('#knMemKind').value;
  const view = bodyEl.querySelector('#knMemView')?.value || 'list';
  box.innerHTML = '<p class="settings-hint">Loading…</p>';
  try {
    if (view === 'rooms') {
      await loadMemoryRooms(bodyEl, box);
      return;
    }
    const url = kind ? `/memory?kind=${kind}&limit=50` : '/memory?limit=50';
    const items = await (await apiFetch(url)).json();
    if (!items.length) {
      box.innerHTML = '<p class="settings-hint">No memories yet.</p><button type="button" class="btn-secondary btn-sm kn-empty-chat">Start a chat</button>';
      wireEmptyChatButton(box);
      return;
    }
    box.innerHTML = items.map((m) => `
      <div class="kn-mem" data-id="${escapeHtml(m.id)}">
        <span class="kn-chip" style="--chip-color:${TYPE_COLORS.memory}">${escapeHtml(kindLabel(m.kind))}</span>
        <span class="kn-mem-content">${escapeHtml((m.content || '').slice(0, 160))}</span>
        ${m.room && m.room !== 'default' ? `<span class="kn-mem-room" title="Group / folder">${escapeHtml(m.room)}/${escapeHtml(m.drawer || 'general')}</span>` : ''}
        ${m.importance != null ? `<span class="kn-mem-imp" title="Importance">${Number(m.importance).toFixed(2)}</span>` : ''}
        <button class="icon-btn kn-mem-edit" title="Edit" aria-label="Edit memory"><i class="fa-solid fa-pen"></i></button>
        <button class="icon-btn kn-mem-move" title="Move to group/folder" aria-label="Move memory"><i class="fa-solid fa-folder-open"></i></button>
        <button class="icon-btn kn-mem-del" title="Forget"><i class="fa-solid fa-trash"></i></button>
      </div>`).join('');
    box.querySelectorAll('.kn-mem-edit').forEach((btn, i) => {
      btn.addEventListener('click', () => prefillUpdateForm(bodyEl, items[i]));
    });
    box.querySelectorAll('.kn-mem-move').forEach((btn) => {
      btn.addEventListener('click', () => openMoveMemory(bodyEl, btn.closest('.kn-mem')));
    });
    box.querySelectorAll('.kn-mem-del').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.closest('.kn-mem').dataset.id;
        if (!confirm('Forget this memory?')) return;
        try {
          await apiFetch(`/memory/${encodeURIComponent(id)}`, { method: 'DELETE' });
          showToast({ type: 'success', title: 'Memory forgotten' });
          loadMemories(bodyEl);
          loadGraph(bodyEl);
        } catch {
          showToast({ type: 'error', title: 'Delete failed' });
        }
      });
    });
  } catch {
    box.innerHTML = '<p class="settings-hint">Could not load memories.</p>';
  }
}

/** Phase 8 D4: move a memory to another room/drawer (PUT /memory/{id}/move). */
async function openMoveMemory(bodyEl, rowEl) {
  const id = rowEl?.dataset.id;
  if (!id) return;
  // Fetch existing rooms for suggestions
  let rooms = [];
  try {
    const data = await (await apiFetch('/memory/rooms')).json();
    rooms = (data.rooms || []).map((r) => r.name);
  } catch { /* ignore */ }
  const room = prompt(`Move memory to group (existing: ${rooms.join(', ') || 'none yet'}):`, 'default');
  if (room == null) return;
  const drawer = prompt('Folder:', 'general');
  if (drawer == null) return;
  try {
    const res = await apiFetch(`/memory/${encodeURIComponent(id)}/move`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ room: room.trim() || 'default', drawer: drawer.trim() || 'general' }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    showToast({ type: 'success', title: 'Memory moved' });
    loadMemories(bodyEl);
  } catch (err) {
    showToast({ type: 'error', title: 'Move failed', message: err?.message || String(err) });
  }
}

/** Phase 7: browsable rooms/drawers hierarchy. */
async function loadMemoryRooms(bodyEl, box) {
  try {
    const data = await (await apiFetch('/memory/rooms')).json();
    const rooms = data.rooms || [];
    if (!rooms.length) {
      box.innerHTML = '<p class="settings-hint">No memories yet.</p><button type="button" class="btn-secondary btn-sm kn-empty-chat">Start a chat</button>';
      wireEmptyChatButton(box);
      return;
    }
    box.innerHTML = rooms.map((room) => `
      <details class="kn-room" ${room.name === 'default' ? 'open' : ''}>
        <summary>
          <i class="fa-solid fa-folder"></i>
          <strong>${escapeHtml(room.name)}</strong>
          <span class="kn-room-count">${room.total} memories</span>
        </summary>
        <div class="kn-drawers">
          ${room.drawers.map((d) => `
            <details class="kn-drawer">
              <summary>
                <i class="fa-solid fa-folder-open"></i>
                ${escapeHtml(d.name)}
                <span class="kn-room-count">${d.count}</span>
              </summary>
              <div class="kn-drawer-mems" data-room="${escapeHtml(room.name)}" data-drawer="${escapeHtml(d.name)}">
                <p class="settings-hint">Loading…</p>
              </div>
            </details>`).join('')}
        </div>
      </details>`).join('');

    // Lazy-load drawer contents on expand
    box.querySelectorAll('.kn-drawer').forEach((drawerEl) => {
      drawerEl.addEventListener('toggle', async () => {
        if (!drawerEl.open) return;
        const memsEl = drawerEl.querySelector('.kn-drawer-mems');
        if (memsEl.dataset.loaded) return;
        memsEl.dataset.loaded = '1';
        const room = memsEl.dataset.room;
        const drawer = memsEl.dataset.drawer;
        try {
          const items = await (await apiFetch(
            `/memory/rooms/${encodeURIComponent(room)}/${encodeURIComponent(drawer)}`
          )).json();
          if (!items.length) {
            memsEl.innerHTML = '<p class="settings-hint">No memories in this folder yet.</p>';
            return;
          }
          memsEl.innerHTML = items.map((m) => `
            <div class="kn-mem" data-id="${escapeHtml(m.id)}">
              <span class="kn-chip" style="--chip-color:${TYPE_COLORS.memory}">${escapeHtml(kindLabel(m.kind))}</span>
              <span class="kn-mem-content">${escapeHtml((m.content || '').slice(0, 120))}</span>
              <button class="icon-btn kn-mem-edit" title="Edit" aria-label="Edit memory"><i class="fa-solid fa-pen"></i></button>
              <button class="icon-btn kn-mem-del" title="Forget"><i class="fa-solid fa-trash"></i></button>
            </div>`).join('');
          memsEl.querySelectorAll('.kn-mem-edit').forEach((btn, i) => {
            btn.addEventListener('click', () => prefillUpdateForm(bodyEl, {
              ...items[i],
              room: items[i].room || room,
              drawer: items[i].drawer || drawer,
            }));
          });
          memsEl.querySelectorAll('.kn-mem-del').forEach((btn) => {
            btn.addEventListener('click', async () => {
              const id = btn.closest('.kn-mem').dataset.id;
              if (!confirm('Forget this memory?')) return;
              await apiFetch(`/memory/${encodeURIComponent(id)}`, { method: 'DELETE' });
              showToast({ type: 'success', title: 'Memory forgotten' });
              delete memsEl.dataset.loaded;
              drawerEl.open = false;
              drawerEl.open = true;
            });
          });
        } catch {
          memsEl.innerHTML = '<p class="settings-hint">Could not load.</p>';
        }
      });
    });
  } catch {
    box.innerHTML = '<p class="settings-hint">Could not load rooms.</p>';
  }
}

async function tidyMemories(bodyEl) {
  if (!confirm('Clean up old memories? This decays stale ones and prunes dead entries.')) return;
  try {
    const data = await (await apiFetch('/memory/consolidate', { method: 'POST' })).json();
    showToast({ type: 'success', title: 'Memories cleaned up', message: JSON.stringify(data).slice(0, 120) });
    loadMemories(bodyEl);
    loadGraph(bodyEl);
  } catch {
    showToast({ type: 'error', title: 'Clean-up failed' });
  }
}

/** Phase 2 remainder: download the user's memories as JSON. */
async function exportMemories() {
  try {
    const data = await (await apiFetch('/memory/export')).json();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'sangam-memories.json';
    a.click();
    URL.revokeObjectURL(a.href);
    showToast({ type: 'success', title: `Exported ${data.length} memories` });
  } catch {
    showToast({ type: 'error', title: 'Export failed' });
  }
}

/** Phase 2 remainder: hybrid retrieval with citations. */
async function retrieveDocuments(bodyEl) {
  const q = bodyEl.querySelector('#knRetrieveQ').value.trim();
  const box = bodyEl.querySelector('#knRetrieveResults');
  if (!q) { box.innerHTML = '<p class="settings-hint">Type a question first.</p>'; return; }
  box.innerHTML = '<p class="settings-hint">Retrieving…</p>';
  try {
    const data = await (await apiFetch(`/knowledge/retrieve?q=${encodeURIComponent(q)}`)).json();
    const results = data.results || [];
    if (!results.length) {
      box.innerHTML = '<p class="settings-hint">No matching documents. Upload a document or ingest a page first.</p>';
      return;
    }
    box.innerHTML = results.map((r) => {
      const c = r.citation || {};
      return `<div class="kn-mem">
        <span class="kn-chip" style="--chip-color:${TYPE_COLORS.document}">${escapeHtml(c.source || 'vector')}</span>
        <span class="kn-mem-content"><strong>${escapeHtml(c.filename || r.filename || '')}</strong>${c.chunk_index != null ? ` · chunk ${c.chunk_index}` : ''}<br>${escapeHtml(c.excerpt || r.text || '')}</span>
      </div>`;
    }).join('');
  } catch {
    box.innerHTML = '<p class="settings-hint">Retrieval failed.</p>';
  }
}

/** Phase 2 remainder: ingest a public page as a document. */
async function ingestPage(bodyEl) {
  const url = bodyEl.querySelector('#knIngestUrl').value.trim();
  const status = bodyEl.querySelector('#knIngestStatus');
  if (!url) { status.textContent = 'Paste a URL first.'; return; }
  status.textContent = 'Fetching page…';
  try {
    const res = await apiFetch('/knowledge/ingest-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    status.textContent = `Ingested ${data.filename} (${data.chunks_indexed} chunks).`;
    showToast({ type: 'success', title: 'Page ingested' });
    loadGraph(bodyEl);
  } catch (err) {
    status.textContent = `Ingest failed: ${err?.message || String(err)}`;
  }
}

// --- Batch 9: Memory & Research ------------------------------------------

function initMemoryResearch(bodyEl) {
  const obsBtn = bodyEl.querySelector('#mrObsAddBtn');
  if (!obsBtn) return;
  obsBtn.addEventListener('click', async () => {
    const claim = bodyEl.querySelector('#mrObsClaim').value.trim();
    if (!claim) return;
    try {
      const res = await apiFetch('/memory/observations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: bodyEl.querySelector('#mrObsKind').value, claim, evidence: [] }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      showToast({ type: 'success', title: data.created ? 'Observation saved' : 'Observation strengthened' });
      loadObservations(bodyEl);
    } catch (err) {
      showToast({ type: 'error', title: `Could not save observation: ${err?.message || String(err)}` });
    }
  });
  bodyEl.querySelector('#mrResearchBtn').addEventListener('click', async () => {
    const q = bodyEl.querySelector('#mrResearchQ').value.trim();
    const box = bodyEl.querySelector('#mrResearchStatus');
    if (!q) return;
    box.innerHTML = '<p class="settings-hint">Starting research…</p>';
    try {
      const job = await (await apiFetch('/research/jobs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: q }),
      })).json();
      box.innerHTML = '<p class="settings-hint">Searching and curating sources…</p>';
      const done = await (await apiFetch(`/research/jobs/${job.id}/run`, { method: 'POST' })).json();
      const sources = (done.sources || []).map((s) => `<li>${escapeHtml(s.title || s.url || s.source_id)} (score ${s.curator_score ?? ''})</li>`).join('');
      box.innerHTML = done.status === 'done'
        ? `<p class="settings-hint">Done — ${done.sources.length} sources curated. Write a cited report from the API, or read sources below.</p><ul>${sources}</ul>`
        : `<p class="settings-hint">Research failed: ${escapeHtml(done.error || 'unknown error')}</p>`;
    } catch {
      box.innerHTML = '<p class="settings-hint">Research could not start.</p>';
    }
  });
  bodyEl.querySelector('#mrCatBtn').addEventListener('click', () => loadCatalogue(bodyEl));
  bodyEl.querySelector('#mrPackBtn').addEventListener('click', async () => {
    const box = bodyEl.querySelector('#mrPackStatus');
    box.innerHTML = '<p class="settings-hint">Packing…</p>';
    try {
      const res = await apiFetch('/knowledge/packs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: bodyEl.querySelector('#mrPackPath').value.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
      box.innerHTML = `<p class="settings-hint">Packed ${data.files.length} files, about ${data.total_tokens_estimate} tokens (estimate) in ${data.chunk_count} chunk(s). ${data.filtered.length} file(s) left out for safety.</p>`;
    } catch (err) {
      box.innerHTML = `<p class="settings-hint">Pack failed: ${escapeHtml(err?.message || String(err))}</p>`;
    }
  });
  loadObservations(bodyEl);
  loadCatalogue(bodyEl);
  loadMemoryNotes(bodyEl);
}

async function loadObservations(bodyEl) {
  const box = bodyEl.querySelector('#mrObsList');
  box.innerHTML = '<p class="settings-hint">Loading…</p>';
  try {
    const data = await (await apiFetch('/memory/observations?limit=20')).json();
    const items = data.observations || [];
    if (!items.length) {
      box.innerHTML = '<p class="settings-hint">No observations yet. Save a belief above with its evidence, and it will appear here with a proof count.</p>';
      return;
    }
    box.innerHTML = items.map((o) => `<div class="kn-mem-row"><span class="kn-chip">${escapeHtml(o.kind)}</span><span class="kn-mem-content">${escapeHtml(o.claim)}<br>Proof: ${o.proof_count} evidence item(s) · strength ${o.strength}</span></div>`).join('');
  } catch {
    box.innerHTML = '<p class="settings-hint">Could not load observations.</p>';
  }
}

async function loadCatalogue(bodyEl) {
  const box = bodyEl.querySelector('#mrCatList');
  const q = bodyEl.querySelector('#mrCatQ').value.trim();
  box.innerHTML = '<p class="settings-hint">Loading…</p>';
  try {
    const data = await (await apiFetch(`/knowledge/catalogue?q=${encodeURIComponent(q)}`)).json();
    const items = data.entries || [];
    if (!items.length) {
      box.innerHTML = `<p class="settings-hint">${escapeHtml(data.empty_state || 'No catalogue entries match.')}</p>`;
      return;
    }
    box.innerHTML = items.map((e) => `<div class="kn-mem-row"><span class="kn-chip">${escapeHtml(e.kind)}</span><span class="kn-mem-content"><strong>${escapeHtml(e.name)}</strong> — ${escapeHtml(e.description)}<br>Risk: ${escapeHtml(e.risk)}${e.sangam_equivalent ? `<br>Sangam equivalent: ${escapeHtml(e.sangam_equivalent)}` : ''}</span></div>`).join('');
  } catch {
    box.innerHTML = '<p class="settings-hint">Could not load the catalogue.</p>';
  }
}

async function loadMemoryNotes(bodyEl) {
  const box = bodyEl.querySelector('#mrNotesList');
  box.innerHTML = '<p class="settings-hint">Loading…</p>';
  try {
    const data = await (await apiFetch('/memory/notes')).json();
    const items = data.notes || [];
    if (!items.length) {
      box.innerHTML = `<p class="settings-hint">${escapeHtml(data.empty_state || 'No memory notes yet.')}</p>`;
      return;
    }
    box.innerHTML = items.map((n) => `<div class="kn-mem-row"><span class="kn-chip">${escapeHtml(n.type)}</span><span class="kn-mem-content"><strong>${escapeHtml(n.title)}</strong> (${escapeHtml(n.created || '')})<br>${escapeHtml(n.preview || '')}</span></div>`).join('');
  } catch {
    box.innerHTML = '<p class="settings-hint">Could not load memory notes.</p>';
  }
}
