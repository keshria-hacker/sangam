/**
 * Knowledge view — unified knowledge graph, MCP tools, memory browser (Sangam-native, Phase 3).
 *
 * Sections:
 *   1. Header: search (debounced), stats chips, "Include code" toggle
 *   2. Graph: SVG with simple force simulation (no external libs)
 *   3. Detail panel: node metadata + related nodes
 *   4. MCP tools manager
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
          <input type="text" id="knSearch" placeholder="Search memories, documents, chats…" autocomplete="off">
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
      <section class="kn-section">
        <h3><i class="fa-solid fa-plug"></i> MCP tools</h3>
        <div id="knMcp"></div>
      </section>
      <section class="kn-section">
        <h3><i class="fa-solid fa-brain"></i> Memories</h3>
        <div class="kn-mem-controls">
          <select id="knMemView" class="provider-key-input" aria-label="Memory view">
            <option value="list">List</option>
            <option value="rooms">Rooms</option>
          </select>
          <select id="knMemKind" class="provider-key-input">
            <option value="">All kinds</option>
            <option value="episodic">Episodic</option>
            <option value="semantic">Semantic</option>
            <option value="procedural">Procedural</option>
          </select>
          <button class="btn-secondary" id="knTidy"><i class="fa-solid fa-broom"></i> Tidy</button>
        </div>
        <div id="knMemories" class="kn-mem-list"></div>
      </section>
    </div>`;

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

  // Wire memory browser
  bodyEl.querySelector('#knMemKind').addEventListener('change', () => loadMemories(bodyEl));
  bodyEl.querySelector('#knMemView').addEventListener('change', () => loadMemories(bodyEl));
  bodyEl.querySelector('#knTidy').addEventListener('click', () => tidyMemories(bodyEl));

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
  if (!nodes.length) {
    svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" class="kn-loading">No knowledge yet — chat, upload files, or save memories.</text>`;
    return;
  }

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

async function loadMcp(bodyEl) {
  const box = bodyEl.querySelector('#knMcp');
  box.innerHTML = '<p class="settings-hint">Loading…</p>';
  try {
    const data = await (await apiFetch('/extensions')).json();
    const servers = (data.extensions || []).filter((e) => e.kind === 'mcp_server');
    if (!servers.length) {
      box.innerHTML = `<p class="settings-hint">No MCP servers configured. Add one via the extensions system.</p>`;
      return;
    }
    box.innerHTML = servers.map((s) => `
      <div class="kn-mcp-server">
        <span class="kn-mcp-name"><i class="fa-solid fa-plug"></i> ${escapeHtml(s.name)}</span>
        <span class="kn-mcp-desc">${escapeHtml(s.description || '')}</span>
        <span class="kn-mcp-status ${s.enabled ? 'on' : ''}">${s.enabled ? 'Connected' : 'Off'}</span>
        <button class="btn-secondary btn-sm" data-name="${escapeHtml(s.name)}" data-action="${s.enabled ? 'disable' : 'enable'}">
          ${s.enabled ? 'Disconnect' : 'Connect'}
        </button>
      </div>`).join('');
    box.querySelectorAll('button[data-name]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        try {
          await apiFetch(`/extensions/${encodeURIComponent(btn.dataset.name)}/${btn.dataset.action}`, { method: 'POST' });
          showToast({ type: 'success', title: `MCP server ${btn.dataset.action}d` });
          loadMcp(bodyEl);
        } catch {
          showToast({ type: 'error', title: 'Action failed' });
        }
      });
    });
  } catch {
    box.innerHTML = '<p class="settings-hint">Could not load MCP servers.</p>';
  }
}

// --- Memory browser ------------------------------------------------------------

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
      box.innerHTML = '<p class="settings-hint">No memories yet.</p>';
      return;
    }
    box.innerHTML = items.map((m) => `
      <div class="kn-mem" data-id="${escapeHtml(m.id)}">
        <span class="kn-chip" style="--chip-color:${TYPE_COLORS.memory}">${escapeHtml(m.kind || '')}</span>
        <span class="kn-mem-content">${escapeHtml((m.content || '').slice(0, 160))}</span>
        ${m.room && m.room !== 'default' ? `<span class="kn-mem-room" title="Room / drawer">${escapeHtml(m.room)}/${escapeHtml(m.drawer || 'general')}</span>` : ''}
        ${m.importance != null ? `<span class="kn-mem-imp" title="Importance">${Number(m.importance).toFixed(2)}</span>` : ''}
        <button class="icon-btn kn-mem-del" title="Forget"><i class="fa-solid fa-trash"></i></button>
      </div>`).join('');
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

/** Phase 7: browsable rooms/drawers hierarchy. */
async function loadMemoryRooms(bodyEl, box) {
  try {
    const data = await (await apiFetch('/memory/rooms')).json();
    const rooms = data.rooms || [];
    if (!rooms.length) {
      box.innerHTML = '<p class="settings-hint">No memories yet.</p>';
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
            memsEl.innerHTML = '<p class="settings-hint">Empty.</p>';
            return;
          }
          memsEl.innerHTML = items.map((m) => `
            <div class="kn-mem" data-id="${escapeHtml(m.id)}">
              <span class="kn-chip" style="--chip-color:${TYPE_COLORS.memory}">${escapeHtml(m.kind || '')}</span>
              <span class="kn-mem-content">${escapeHtml((m.content || '').slice(0, 120))}</span>
              <button class="icon-btn kn-mem-del" title="Forget"><i class="fa-solid fa-trash"></i></button>
            </div>`).join('');
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
  if (!confirm('Consolidate memories? This decays stale ones and prunes dead entries.')) return;
  try {
    const data = await (await apiFetch('/memory/consolidate', { method: 'POST' })).json();
    showToast({ type: 'success', title: 'Memories tidied', message: JSON.stringify(data).slice(0, 120) });
    loadMemories(bodyEl);
    loadGraph(bodyEl);
  } catch {
    showToast({ type: 'error', title: 'Consolidation failed' });
  }
}
