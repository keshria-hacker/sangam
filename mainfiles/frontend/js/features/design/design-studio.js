/**
 * Design Studio tab — generate web prototypes with live preview (Sangam-native).
 * Uses the Code Agent backend with a design-focused brief; renders the
 * generated index.html in a sandboxed iframe with live refresh.
 */
import { apiFetch } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] design-studio.js loaded');

let projectId = null;

function stepNode(step) {
  const div = document.createElement('div');
  div.className = `ca-step ca-${step.kind}`;
  if (step.kind === 'thought') {
    div.innerHTML = `<div class="ca-thought">${escapeHtml(step.content).replace(/\n/g, '<br>')}</div>`;
  } else if (step.kind === 'tool_call') {
    div.innerHTML = `<div class="ca-tool"><i class="fa-solid fa-wrench"></i> <code>${escapeHtml(step.tool || '')}</code></div>`;
  } else if (step.kind === 'tool_result') {
    div.innerHTML = `<details class="ca-result"><summary>Result</summary><pre>${escapeHtml(step.content.slice(0, 2000))}</pre></details>`;
  } else if (step.kind === 'done') {
    div.innerHTML = `<div class="ca-done"><i class="fa-solid fa-circle-check"></i> Preview ready.</div>`;
  } else if (step.kind === 'error') {
    div.innerHTML = `<div class="ca-error-msg"><i class="fa-solid fa-triangle-exclamation"></i> ${escapeHtml(step.content)}</div>`;
  }
  return div;
}

function designBrief(userBrief) {
  return `You are building a web prototype in the directory "designs/${projectId}".
User brief: ${userBrief}

Rules:
1. Create designs/${projectId}/index.html as a complete, self-contained page (inline CSS/JS, no external deps except Google Fonts).
2. Make it polished and modern — real content, not lorem ipsum.
3. After writing, verify the file exists with list_files.
4. Keep iterations small. When the page is ready, stop and summarize.`;
}

/**
 * Render the Design Studio into a tab body.
 */
export function renderDesignTab(bodyEl) {
  projectId = 'proj-' + Date.now().toString(36);
  bodyEl.innerHTML = `
    <div class="design-studio">
      <div class="ds-main">
        <div class="ds-brief-row">
          <textarea id="dsBrief" rows="2" placeholder="Describe the page — e.g. 'A landing page for a coffee subscription with pricing tiers'…" aria-label="Design brief"></textarea>
          <button class="btn-primary" id="dsGenerate" type="button"><i class="fa-solid fa-wand-magic-sparkles"></i> Generate</button>
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
            logEl.appendChild(stepNode(step));
            logEl.scrollTop = logEl.scrollHeight;
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
        logEl.appendChild(stepNode({ kind: 'error', content: String(err?.message || err) }));
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
    logEl.innerHTML = '';
    runAgent(designBrief(brief));
  });
  bodyEl.querySelector('#dsRefineBtn').addEventListener('click', () => {
    const refine = bodyEl.querySelector('#dsRefine').value.trim();
    if (!refine) return;
    bodyEl.querySelector('#dsRefine').value = '';
    runAgent(`Refine the existing prototype in designs/${projectId}: ${refine}. Edit index.html, keep everything else working.`);
  });
  stopBtn.addEventListener('click', () => abort?.abort());
  bodyEl.querySelector('#dsRefresh').addEventListener('click', refreshPreview);
  bodyEl.querySelector('#dsOpen').addEventListener('click', () => window.open(frame.src, '_blank'));
  bodyEl.querySelector('#dsDownload').addEventListener('click', () => {
    const a = document.createElement('a');
    a.href = frame.src; a.download = 'index.html'; a.click();
  });
  setTimeout(() => briefEl.focus(), 0);
}
