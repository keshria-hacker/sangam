/**
 * Diagrams section — Create > Diagrams (Batch 7, diagram-design analogue).
 *
 * Catalogue picker -> template inserted into an editor -> live Mermaid
 * preview -> lint results -> brand select -> import file input -> export
 * buttons. Export is frontend-only: Export SVG serializes the rendered
 * Mermaid SVG element; Export PNG draws it onto a canvas. If Mermaid has
 * not rendered (CDN missing, invalid source), the buttons show a plain
 * "diagram not rendered yet" state instead of failing silently.
 *
 * Honest limits, stated in the UI: lint covers only what is statically
 * checkable (accent count, node count, label length, title). Overlap and
 * clipping checks are visual. Import is best-effort (see backend).
 */
import { apiGet, apiPost } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] create/diagrams.js loaded');

let catalogue = [];
let brands = [];
let renderSeq = 0;
let lastSvg = null;

async function loadCatalogue() {
  if (catalogue.length) return catalogue;
  const data = await (await apiGet('/diagrams/catalogue')).json();
  catalogue = (data && data.diagrams) || [];
  return catalogue;
}

async function loadBrands() {
  try {
    const data = await (await apiGet('/diagrams/brands')).json();
    brands = (data && data.brands) || [];
  } catch { brands = []; }
  return brands;
}

function download(filename, blob) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

async function renderPreview(root) {
  const editor = root.querySelector('[data-diag-editor]');
  const preview = root.querySelector('[data-diag-preview]');
  const code = editor.value;
  lastSvg = null;
  if (!window.mermaid) {
    preview.innerHTML = '<p class="settings-hint">Mermaid is not loaded yet (CDN) — the source below is still editable and lint still runs.</p>';
    return;
  }
  const seq = ++renderSeq;
  try {
    if (typeof window.mermaid.initialize === 'function') {
      window.mermaid.initialize({ startOnLoad: false, theme: 'base' });
    }
    const { svg } = await window.mermaid.render(`batch7-diag-${seq}`, code);
    if (seq !== renderSeq) return;
    preview.innerHTML = svg;
    lastSvg = preview.querySelector('svg');
  } catch (err) {
    if (seq !== renderSeq) return;
    preview.innerHTML = `<p class="team-error">Mermaid could not render this diagram: ${escapeHtml(err?.message || String(err))}</p>`;
  }
}

function renderBrandOptions(root) {
  const sel = root.querySelector('[data-diag-brand]');
  sel.innerHTML = '<option value="">Default style</option>' + brands.map((b) =>
    `<option value="${escapeHtml(b.id)}">${escapeHtml(b.name)} (${escapeHtml(b.accent)})</option>`).join('');
}

export async function renderDiagramsSection(bodyEl) {
  bodyEl.innerHTML = `
    <div class="diagrams-section">
      <h3>Diagrams</h3>
      <div class="settings-hint diagrams-onboarding">
        <strong>Style guide:</strong> one accent color for the one or two things that matter,
        1px hairlines, no shadows, coordinates on a 4px grid. Lint checks only what is
        statically checkable (accent count, node count, label length, title) — overlap and
        clipping are visual checks on the rendered diagram. Imports are best-effort:
        only basic shapes and connectors convert; the rest becomes warnings, never invented nodes.
        <span data-diag-brand-form></span>
      </div>
      <details class="advanced-section"><summary>Advanced: brand style</summary>
      <div class="diagrams-brand-row">
        <input type="text" class="provider-key-input" data-diag-brand-name placeholder="Brand name" aria-label="Brand name">
        <input type="text" class="provider-key-input" data-diag-brand-accent placeholder="#3A7BD5" aria-label="Brand accent color">
        <button class="btn-secondary btn-sm" type="button" data-diag-brand-create>Create your brand</button>
      </div>
      </details>
      <div class="diagrams-picker" data-diag-picker><p class="settings-hint">Loading catalogue…</p></div>
      <div class="diagrams-editor-row">
        <textarea class="provider-key-input" data-diag-editor rows="12" style="width:100%;box-sizing:border-box;font-family:monospace" placeholder="Pick a diagram type to load its template…" aria-label="Diagram source"></textarea>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin:8px 0">
        <select class="provider-key-input" data-diag-brand aria-label="Brand"><option value="">Default style</option></select>
        <button class="btn-secondary btn-sm" type="button" data-diag-apply-brand>Apply brand</button>
        <button class="btn-secondary btn-sm" type="button" data-diag-lint>Run lint</button>
        <button class="btn-secondary btn-sm" type="button" data-diag-export-svg>Export SVG</button>
        <button class="btn-secondary btn-sm" type="button" data-diag-export-png>Export PNG</button>
        <label class="btn-secondary btn-sm" style="cursor:pointer">Import file
          <input type="file" data-diag-import hidden accept=".mmd,.mermaid,.drawio,.xml,.excalidraw,.json">
        </label>
      </div>
      <div data-diag-lint-out></div>
      <div data-diag-import-out></div>
      <div class="diagrams-preview" data-diag-preview><p class="settings-hint">Live preview appears here.</p></div>
    </div>`;

  const picker = bodyEl.querySelector('[data-diag-picker]');
  const editor = bodyEl.querySelector('[data-diag-editor]');
  const lintOut = bodyEl.querySelector('[data-diag-lint-out]');
  const importOut = bodyEl.querySelector('[data-diag-import-out]');

  try {
    const cats = await loadCatalogue();
    picker.innerHTML = cats.map((c) =>
      `<button class="btn-secondary btn-sm" type="button" data-diag-type="${escapeHtml(c.id)}">${escapeHtml(c.name)}</button>`).join('') +
      `<p class="settings-hint">${cats.map((c) => `${escapeHtml(c.name)} — ${escapeHtml(c.use)}`).join(' · ')}</p>`;
    picker.querySelectorAll('[data-diag-type]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const entry = cats.find((c) => c.id === btn.dataset.diagType);
        if (entry) { editor.value = entry.template; renderPreview(bodyEl); }
      });
    });
  } catch {
    picker.innerHTML = '<p class="team-error">Catalogue unavailable.</p>';
  }

  await loadBrands();
  renderBrandOptions(bodyEl);

  let debounce = null;
  editor.addEventListener('input', () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => renderPreview(bodyEl), 400);
  });

  bodyEl.querySelector('[data-diag-brand-create]').addEventListener('click', async () => {
    const name = bodyEl.querySelector('[data-diag-brand-name]').value.trim();
    const accent = bodyEl.querySelector('[data-diag-brand-accent]').value.trim() || '#3A7BD5';
    if (!name) { showToast({ type: 'info', title: 'Name your brand first' }); return; }
    try {
      await (await apiPost('/diagrams/brands', { name, accent })).json();
      await loadBrands();
      renderBrandOptions(bodyEl);
      showToast({ type: 'success', title: 'Brand saved' });
    } catch (err) {
      showToast({ type: 'error', title: 'Could not save brand', message: err?.message || String(err) });
    }
  });

  bodyEl.querySelector('[data-diag-apply-brand]').addEventListener('click', async () => {
    const brandId = bodyEl.querySelector('[data-diag-brand]').value;
    if (!brandId) { showToast({ type: 'info', title: 'Pick a brand first' }); return; }
    try {
      const data = await (await apiPost('/diagrams/brands/apply', { template: editor.value, brand_id: brandId })).json();
      editor.value = data.mermaid || editor.value;
      renderPreview(bodyEl);
      showToast({ type: 'success', title: 'Brand applied' });
    } catch (err) {
      showToast({ type: 'error', title: 'Could not apply brand', message: err?.message || String(err) });
    }
  });

  bodyEl.querySelector('[data-diag-lint]').addEventListener('click', async () => {
    try {
      const data = await (await apiPost('/diagrams/lint', { mermaid: editor.value })).json();
      const issues = data.issues || [];
      lintOut.innerHTML = issues.length
        ? `<ul>${issues.map((i) => `<li>[${escapeHtml(i.level)}] ${escapeHtml(i.rule)}: ${escapeHtml(i.message)}</li>`).join('')}</ul>`
        : '<p class="settings-hint">Lint passed — no statically checkable issues. Overlap/clipping still need a visual check.</p>';
      if (data.note) lintOut.innerHTML += `<p class="settings-hint">${escapeHtml(data.note)}</p>`;
    } catch (err) {
      lintOut.innerHTML = `<p class="team-error">Lint failed: ${escapeHtml(err?.message || String(err))}</p>`;
    }
  });

  bodyEl.querySelector('[data-diag-import]').addEventListener('change', async (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const content = await file.text();
    const name = file.name.toLowerCase();
    const format = name.endsWith('.drawio') || name.endsWith('.xml') ? 'drawio'
      : (name.endsWith('.excalidraw') ? 'excalidraw' : 'mermaid');
    try {
      const data = await (await apiPost('/diagrams/import', { format, content })).json();
      editor.value = data.mermaid || '';
      importOut.innerHTML = (data.warnings || []).map((w) => `<p class="settings-hint">${escapeHtml(w)}</p>`).join('');
      renderPreview(bodyEl);
    } catch (err) {
      importOut.innerHTML = `<p class="team-error">Import failed: ${escapeHtml(err?.message || String(err))}</p>`;
    }
  });

  bodyEl.querySelector('[data-diag-export-svg]').addEventListener('click', () => {
    if (!lastSvg) { showToast({ type: 'info', title: 'Diagram not rendered yet' }); return; }
    const text = new XMLSerializer().serializeToString(lastSvg);
    download('diagram.svg', new Blob([text], { type: 'image/svg+xml' }));
  });

  bodyEl.querySelector('[data-diag-export-png]').addEventListener('click', () => {
    if (!lastSvg) { showToast({ type: 'info', title: 'Diagram not rendered yet' }); return; }
    const text = new XMLSerializer().serializeToString(lastSvg);
    const url = URL.createObjectURL(new Blob([text], { type: 'image/svg+xml;charset=utf-8' }));
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = img.naturalWidth || 800;
      canvas.height = img.naturalHeight || 600;
      canvas.getContext('2d').drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      canvas.toBlob((blob) => { if (blob) download('diagram.png', blob); });
    };
    img.onerror = () => { URL.revokeObjectURL(url); showToast({ type: 'error', title: 'PNG export failed' }); };
    img.src = url;
  });
}
