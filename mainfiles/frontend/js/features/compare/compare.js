/**
 * Model Compare + Arena UI.
 *
 * - Pick 2–4 models, enter a prompt, watch side-by-side streaming responses.
 * - "Pick winner" on any model card records an Arena vote.
 * - Arena leaderboard (win rates) shown below.
 */
import { apiFetch, apiPost } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
import { renderMarkdown } from '../../shared/markdown.js';
console.log('[Module] compare.js loaded');

export async function renderCompareTab(bodyEl) {
  bodyEl.innerHTML = `
    <div class="compare-tab">
      <div class="compare-controls">
        <textarea id="cmpPrompt" rows="3" placeholder="Enter a prompt to compare across models…" aria-label="Compare prompt"></textarea>
        <div class="cmp-model-row">
          <div id="cmpModels" class="cmp-models"></div>
          <button class="btn-secondary btn-sm" id="cmpAddModel" type="button">+ Add model</button>
        </div>
        <div class="cmp-actions">
          <button class="btn-primary" id="cmpRun" type="button">Compare</button>
          <button class="btn-secondary hidden" id="cmpStop" type="button">Stop</button>
        </div>
      </div>
      <div class="cmp-results hidden" id="cmpResults"></div>
      <div class="cmp-arena">
        <h4>Arena Leaderboard</h4>
        <div id="cmpLeaderboard"><p class="cmp-muted">Loading…</p></div>
      </div>
    </div>`;

  const promptEl = bodyEl.querySelector('#cmpPrompt');
  const modelsEl = bodyEl.querySelector('#cmpModels');
  const addBtn = bodyEl.querySelector('#cmpAddModel');
  const runBtn = bodyEl.querySelector('#cmpRun');
  const stopBtn = bodyEl.querySelector('#cmpStop');
  const resultsEl = bodyEl.querySelector('#cmpResults');

  // Load available models
  let allModels = [];
  try {
    const data = await (await apiFetch('/models')).json();
    allModels = data.models || data || [];
  } catch {
    allModels = [];
  }
  const modelOptions = allModels.map((m) => {
    const id = m.id || m;
    const label = m.name || m.id || m;
    return `<option value="${escapeHtml(id)}">${escapeHtml(label)}</option>`;
  }).join('');

  const selected = [];

  function renderModelPickers() {
    modelsEl.innerHTML = '';
    selected.forEach((modelId, idx) => {
      const wrap = document.createElement('div');
      wrap.className = 'cmp-model-picker';
      wrap.innerHTML = `
        <select aria-label="Model ${idx + 1}">${modelOptions}</select>
        <button class="btn-secondary btn-sm" type="button" aria-label="Remove">×</button>`;
      const sel = wrap.querySelector('select');
      sel.value = modelId;
      sel.addEventListener('change', () => { selected[idx] = sel.value; });
      wrap.querySelector('button').addEventListener('click', () => {
        selected.splice(idx, 1);
        renderModelPickers();
      });
      modelsEl.appendChild(wrap);
    });
    addBtn.disabled = selected.length >= 4;
  }

  // Start with 2 pickers
  if (allModels.length >= 2) {
    selected.push(allModels[0].id || allModels[0], allModels[1].id || allModels[1]);
  } else if (allModels.length === 1) {
    selected.push(allModels[0].id || allModels[0]);
  }
  renderModelPickers();

  addBtn.addEventListener('click', () => {
    if (selected.length >= 4) return;
    const unused = allModels.find((m) => !selected.includes(m.id || m));
    selected.push(unused ? (unused.id || unused) : (allModels[0]?.id || ''));
    renderModelPickers();
  });

  let abort = null;
  runBtn.addEventListener('click', () => runCompare());
  stopBtn.addEventListener('click', () => abort?.abort());

  async function runCompare() {
    const prompt = promptEl.value.trim();
    const models = selected.filter(Boolean);
    if (!prompt) {
      showToast({ type: 'info', title: 'Enter a prompt first' });
      return;
    }
    if (models.length < 2) {
      showToast({ type: 'info', title: 'Pick at least 2 models' });
      return;
    }

    runBtn.classList.add('hidden');
    stopBtn.classList.remove('hidden');
    resultsEl.classList.remove('hidden');
    resultsEl.innerHTML = `<div class="cmp-grid">${models.map((m) => `
      <div class="cmp-card" data-model="${escapeHtml(m)}">
        <div class="cmp-card-head">
          <strong>${escapeHtml(m)}</strong>
          <span class="cmp-status" data-status>waiting…</span>
        </div>
        <div class="cmp-card-body" data-body></div>
        <div class="cmp-card-foot hidden" data-foot>
          <button class="btn-primary btn-sm" data-winner type="button">Pick winner</button>
        </div>
      </div>`).join('')}</div>`;

    abort = new AbortController();
    const outputs = new Map(models.map((m) => [m, '']));
    const cardFor = (m) => resultsEl.querySelector(`[data-model="${CSS.escape(m)}"]`);

    const vote = async (winner) => {
      const losers = models.filter((m) => m !== winner);
      if (!losers.length) return;
      // For simplicity, record winner vs first loser (Arena is pairwise)
      try {
        await apiPost('/arena/vote', {
          prompt: prompt.slice(0, 500),
          winner_model: winner,
          loser_model: losers[0],
          models_compared: models,
        });
        showToast({ type: 'success', title: `Voted for ${winner}` });
        loadLeaderboard();
      } catch (err) {
        showToast({ type: 'error', title: 'Vote failed', message: String(err?.message || err) });
      }
    };

    try {
      const res = await apiFetch('/compare/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, models, max_tokens: 500 }),
        signal: abort.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
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
            const ev = JSON.parse(line.slice(5).trim());
            const card = ev.model ? cardFor(ev.model) : null;
            switch (ev.type) {
              case 'model_start':
                if (card) card.querySelector('[data-status]').textContent = 'streaming…';
                break;
              case 'model_chunk':
                if (card) {
                  outputs.set(ev.model, outputs.get(ev.model) + (ev.text || ''));
                  card.querySelector('[data-body]').textContent = outputs.get(ev.model);
                }
                break;
              case 'model_done':
                if (card) {
                  card.querySelector('[data-status]').textContent = `done (${ev.elapsed_s}s)`;
                  card.querySelector('[data-body]').innerHTML = renderMarkdown(outputs.get(ev.model));
                  const foot = card.querySelector('[data-foot]');
                  foot.classList.remove('hidden');
                  foot.querySelector('[data-winner]').addEventListener('click', () => vote(ev.model));
                }
                break;
              case 'model_error':
                if (card) {
                  card.querySelector('[data-status]').textContent = 'failed';
                  card.querySelector('[data-body]').innerHTML = `<p class="team-error">${escapeHtml(ev.error || 'Error')}</p>`;
                }
                break;
              case 'compare_done':
                break;
              default:
                break;
            }
          } catch { /* partial */ }
        }
      }
    } catch (err) {
      if (err?.name !== 'AbortError') {
        showToast({ type: 'error', title: 'Compare failed', message: String(err?.message || err) });
      }
    } finally {
      runBtn.classList.remove('hidden');
      stopBtn.classList.add('hidden');
      abort = null;
    }
  }

  async function loadLeaderboard() {
    const lbEl = bodyEl.querySelector('#cmpLeaderboard');
    try {
      const data = await (await apiFetch('/arena/leaderboard')).json();
      const board = data.leaderboard || [];
      if (!board.length) {
        lbEl.innerHTML = '<p class="cmp-muted">No votes yet. Run a comparison and pick a winner.</p>';
        return;
      }
      lbEl.innerHTML = `
        <table class="cmp-lb">
          <thead><tr><th>Model</th><th>Wins</th><th>Losses</th><th>Win rate</th></tr></thead>
          <tbody>${board.map((r) => `
            <tr><td>${escapeHtml(r.model)}</td><td>${r.wins}</td><td>${r.losses}</td>
            <td>${(r.win_rate * 100).toFixed(1)}%</td></tr>`).join('')}
          </tbody>
        </table>
        <p class="cmp-muted">${data.total_votes} votes total</p>`;
    } catch {
      lbEl.innerHTML = '<p class="cmp-muted">Could not load leaderboard.</p>';
    }
  }

  loadLeaderboard();
  setTimeout(() => promptEl.focus(), 0);
}
