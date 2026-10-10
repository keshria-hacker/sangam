/**
 * Design Studio tab — generate web prototypes with live preview (Sangam-native).
 * Uses the Code Agent backend with a design-focused brief; renders the
 * generated index.html in a sandboxed iframe with live refresh.
 */
import { apiFetch } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { appendStep, clearLog } from '../../shared/runlog.js';

console.log('[Module] design-studio.js loaded');

let projectId = null;

/**
 * Render the Design Studio into a tab body.
 */
export function renderDesignTab(bodyEl) {
  // Stable project ID: reuse the last one so reopening the tab keeps the preview
  projectId = localStorage.getItem('sangam:design-project') || ('proj-' + Date.now().toString(36));
  localStorage.setItem('sangam:design-project', projectId);
  bodyEl.innerHTML = `
    <div class="design-studio">
      <div class="ds-main">
        <div class="ds-brief-row">
          <textarea id="dsBrief" rows="2" placeholder="Describe the page — e.g. 'A landing page for a coffee subscription with pricing tiers'…" aria-label="Design brief"></textarea>
          <button class="btn-primary" id="dsGenerate" type="button"><i class="fa-solid fa-wand-magic-sparkles"></i> Generate</button>
          <button class="btn-secondary" id="dsNew" type="button" title="Start a new design project"><i class="fa-solid fa-plus"></i> New</button>
          <button class="btn-secondary hidden" id="dsStop" type="button"><i class="fa-solid fa-stop"></i> Stop</button>
        </div>
        <div class="ds-log" id="dsLog"><div class="no-results">Describe a page above and press Generate. The preview appears on the right.</div></div>
        <div class="ds-refine-row hidden" id="dsRefineRow">
          <input type="text" id="dsRefine" class="provider-key-input" placeholder="Refine — e.g. 'make the header sticky and darker'…">
          <button class="btn-secondary" id="dsRefineBtn" type="button">Refine</button>
        </div>
      </div>
      <div class="ds-preview">
        <div class="ds-preview-bar">
          <span><i class="fa-solid fa-eye"></i> Preview</span>
          <div>
            <button class="icon-btn" id="dsRefresh" title="Refresh preview"><i class="fa-solid fa-rotate"></i></button>
            <button class="icon-btn" id="dsOpen" title="Open in new window"><i class="fa-solid fa-up-right-from-square"></i></button>
            <button class="icon-btn" id="dsDownload" title="Download HTML"><i class="fa-solid fa-download"></i></button>
          </div>
        </div>
        <iframe id="dsFrame" class="ds-frame" sandbox="allow-scripts" title="Design preview"></iframe>
      </div>
    </div>`;

  const briefEl = bodyEl.querySelector('#dsBrief');
  const genBtn = bodyEl.querySelector('#dsGenerate');
  const stopBtn = bodyEl.querySelector('#dsStop');
  const logEl = bodyEl.querySelector('#dsLog');
  const frame = bodyEl.querySelector('#dsFrame');
  const refineRow = bodyEl.querySelector('#dsRefineRow');
  let abort = null;

  function refreshPreview() {
    frame.src = `/api/designs/${projectId}/index.html?t=${Date.now()}`;
  }

  async function runAgent(prompt) {
    genBtn.classList.add('hidden');
    stopBtn.classList.remove('hidden');
    abort = new AbortController();
    try {
      const res = await apiFetch('/code-agent/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task: prompt, max_iterations: 15 }),
        signal: abort.signal,
      });
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split('\n\n');
        buf = parts.pop();
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith('data:')) continue;
          try {
            const step = JSON.parse(line.slice(5).trim());
            if (step.kind === 'end') continue;
            appendStep(logEl, step);
            if (step.kind === 'tool_result' && (step.tool === 'write_file' || step.tool === 'edit_file')) {
              setTimeout(refreshPreview, 800);
            }
          } catch { /* partial */ }
        }
      }
      refreshPreview();
      refineRow.classList.remove('hidden');
    } catch (err) {
      if (err?.name !== 'AbortError') {
        appendStep(logEl, { kind: 'error', content: String(err?.message || err) });
      }
    } finally {
      genBtn.classList.remove('hidden');
      stopBtn.classList.add('hidden');
      abort = null;
    }
  }

  genBtn.addEventListener('click', () => {
    const brief = briefEl.value.trim();
    if (!brief) { showToast({ type: 'info', message: 'Describe the page first.' }); return; }
    clearLog(logEl);
    runAgent(designBrief(brief));
  });
  bodyEl.querySelector('#dsRefineBtn').addEventListener('click', () => {
    const refine = bodyEl.querySelector('#dsRefine').value.trim();
    if (!refine) return;
    bodyEl.querySelector('#dsRefine').value = '';
    runAgent(`Refine the existing prototype in designs/${projectId}: ${refine}. Edit index.html, keep everything else working.`);
  });
  stopBtn.addEventListener('click', () => abort?.abort());
  bodyEl.querySelector('#dsNew').addEventListener('click', () => {
    projectId = 'proj-' + Date.now().toString(36);
    localStorage.setItem('sangam:design-project', projectId);
    clearLog(logEl);
    frame.src = 'about:blank';
    refineRow.classList.add('hidden');
    showToast({ type: 'info', message: 'New design project started.' });
  });
  bodyEl.querySelector('#dsRefresh').addEventListener('click', refreshPreview);
  bodyEl.querySelector('#dsOpen').addEventListener('click', () => window.open(frame.src, '_blank'));
  bodyEl.querySelector('#dsDownload').addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = frame.src; a.download = 'index.html'; a.click();
  });
  setTimeout(() => briefEl.focus(), 0);
}
