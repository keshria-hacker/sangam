/**
 * Model Fit section — Settings > Models & Routing (Batch 7, llmfit analogue).
 *
 * Hardware summary, recommend form + ranked results, benchmark button +
 * results, Ollama pull/delete. Rendered by settings_page.js into the
 * models category via safeRender. All API calls go through apiGet/apiPost/
 * apiDelete (RAW Response -> .json()), and state-changing POSTs carry the
 * CSRF token via apiFetch. Never shows a VRAM number the backend did not
 * report: "unknown" stays "unknown".
 */
import { apiGet, apiPost, apiDelete } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] create/fit.js loaded');

function renderRows(recs) {
  if (!recs.length) return '<p class="settings-hint">No models match that use case.</p>';
  return `<div class="fit-ranked">${recs.map((r) => `
    <div class="fit-row">
      <strong>${escapeHtml(r.name)}</strong>
      <span>${escapeHtml(r.quant)} · ${escapeHtml(String(r.est_memory_gb))} GB est.</span>
      <span class="fit-label ${r.fits ? 'fit-ok' : 'fit-no'}">${escapeHtml(r.fits_label)}</span>
      <span>speed: ${escapeHtml(r.speed_class)} · quality: ${escapeHtml(r.quality_class)} · context: ${escapeHtml(String(r.context))}</span>
      ${r.bottleneck && r.bottleneck !== 'none' ? `<span>bottleneck: ${escapeHtml(r.bottleneck)}</span>` : ''}
      ${r.runnable === false ? '<span>Embeddings model — not runnable as a chat model.</span>' : ''}
    </div>`).join('')}</div>`;
}

export function renderModelFitSection(container) {
  const wrap = document.createElement('div');
  wrap.className = 'sp-custom-section fit-section';
  wrap.innerHTML = `
    <h3 class="sp-section-title"><i class="fa-solid fa-microchip"></i> Model Fit</h3>
    <p class="settings-hint">Which model will actually run well on this machine? Memory figures are estimates from public model-card sizes, not live measurements. VRAM shows "unknown" unless nvidia-smi answers — it is never guessed.</p>
    <div class="sp-section-body">
      <div data-fit-hardware><p class="settings-hint">Loading hardware…</p></div>
      <div class="fit-form">
        <label>Use case
          <select class="provider-key-input" data-fit-usecase aria-label="Use case">
            <option value="">Any (chat models)</option>
            <option value="chat">Chat</option>
            <option value="code">Code</option>
            <option value="reasoning">Reasoning</option>
            <option value="embeddings">Embeddings</option>
          </select>
        </label>
        <label>Max context
          <input class="provider-key-input" type="number" data-fit-context value="8192" min="1024" max="131072" aria-label="Max context">
        </label>
        <button class="btn-primary btn-sm" type="button" data-fit-recommend>Recommend models</button>
      </div>
      <div data-fit-recommend-out></div>
      <hr>
      <div class="fit-form">
        <label>Benchmark model
          <input class="provider-key-input" type="text" data-fit-bench-model placeholder="ollama:llama3.1 (blank = default model)" aria-label="Benchmark model">
        </label>
        <label><input type="checkbox" data-fit-allow-remote> Allow remote model (cloud models cost tokens)</label>
        <button class="btn-secondary btn-sm" type="button" data-fit-bench>Benchmark</button>
      </div>
      <div data-fit-bench-out></div>
      <hr>
      <div class="fit-form">
        <label>Ollama model
          <input class="provider-key-input" type="text" data-fit-ollama-model placeholder="llama3.1" aria-label="Ollama model">
        </label>
        <button class="btn-secondary btn-sm" type="button" data-fit-pull>Pull model</button>
        <button class="btn-secondary btn-sm" type="button" data-fit-delete>Delete model</button>
      </div>
      <div data-fit-ollama-out></div>
    </div>`;
  container.appendChild(wrap);

  const hwEl = wrap.querySelector('[data-fit-hardware]');
  apiGet('/models/hardware').then(async (r) => {
    const hw = await r.json();
    hwEl.innerHTML = `<p><strong>Hardware:</strong> ${escapeHtml(String(hw.cpu_count ?? '?'))} CPUs · ${escapeHtml(hw.cpu_model || 'unknown CPU')} · RAM ${escapeHtml(String(hw.ram_gb ?? 'unknown'))} GB · VRAM ${hw.vram_gb ? `${escapeHtml(String(hw.vram_gb))} GB (${escapeHtml(hw.vram_status)})` : `unknown (${escapeHtml(hw.vram_status || 'unknown')})`}</p>`;
  }).catch(() => { hwEl.innerHTML = '<p class="settings-hint">Hardware unavailable.</p>'; });

  wrap.querySelector('[data-fit-recommend]').addEventListener('click', async () => {
    const out = wrap.querySelector('[data-fit-recommend-out]');
    const useCase = wrap.querySelector('[data-fit-usecase]').value || null;
    const maxContext = parseInt(wrap.querySelector('[data-fit-context]').value, 10) || null;
    out.innerHTML = '<p class="settings-hint">Ranking…</p>';
    try {
      const data = await (await apiPost('/models/recommend', { use_case: useCase, max_context: maxContext })).json();
      out.innerHTML = renderRows(data.recommendations || []);
    } catch (err) {
      out.innerHTML = `<p class="team-error">Recommend failed: ${escapeHtml(err?.message || String(err))}</p>`;
    }
  });

  wrap.querySelector('[data-fit-bench]').addEventListener('click', async () => {
    const out = wrap.querySelector('[data-fit-bench-out]');
    const modelId = wrap.querySelector('[data-fit-bench-model]').value.trim() || null;
    const allowRemote = wrap.querySelector('[data-fit-allow-remote]').checked;
    out.innerHTML = '<p class="settings-hint">Benchmarking…</p>';
    try {
      const data = await (await apiPost('/models/benchmark', { model_id: modelId, allow_remote: allowRemote })).json();
      out.innerHTML = `<p>TTFT ${escapeHtml(String(data.ttft_s))}s · ${escapeHtml(String(data.tok_per_s))} tok/s · ${escapeHtml(String(data.tokens))} tokens (${escapeHtml(data.token_source_note || data.token_source || '')})</p>`;
    } catch (err) {
      out.innerHTML = `<p class="team-error">Benchmark failed: ${escapeHtml(err?.message || String(err))}</p>`;
    }
  });

  wrap.querySelector('[data-fit-pull]').addEventListener('click', async () => {
    const out = wrap.querySelector('[data-fit-ollama-out]');
    const model = wrap.querySelector('[data-fit-ollama-model]').value.trim();
    if (!model) { showToast({ type: 'info', title: 'Enter a model name first' }); return; }
    try {
      const data = await (await apiPost('/models/ollama/pull', { model })).json();
      out.innerHTML = `<p>Pull started for ${escapeHtml(model)} (id ${escapeHtml(data.id)}). Polling…</p>`;
      const timer = setInterval(async () => {
        try {
          const st = await (await apiGet(`/models/ollama/pulls/${data.id}`)).json();
          out.innerHTML = `<p>Pull ${escapeHtml(model)}: ${escapeHtml(st.status)}${st.detail ? ` — ${escapeHtml(st.detail)}` : ''}</p>`;
          if (st.status === 'success' || st.status === 'error') clearInterval(timer);
        } catch { clearInterval(timer); }
      }, 3000);
    } catch (err) {
      out.innerHTML = `<p class="team-error">Pull failed: ${escapeHtml(err?.message || String(err))}</p>`;
    }
  });

  wrap.querySelector('[data-fit-delete]').addEventListener('click', async () => {
    const out = wrap.querySelector('[data-fit-ollama-out]');
    const model = wrap.querySelector('[data-fit-ollama-model]').value.trim();
    if (!model) { showToast({ type: 'info', title: 'Enter a model name first' }); return; }
    try {
      await apiDelete(`/models/ollama/${encodeURIComponent(model)}`);
      showToast({ type: 'success', title: `Deleted ${model}` });
      out.innerHTML = `<p>Deleted ${escapeHtml(model)}.</p>`;
    } catch (err) {
      out.innerHTML = `<p class="team-error">Delete failed: ${escapeHtml(err?.message || String(err))}</p>`;
    }
  });
}
