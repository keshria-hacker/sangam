/**
 * Agent mode — tool-using chat loop (Sangam-native).
 * Streams POST /api/agent/run SSE into an assistant message node:
 * thought/tool steps as cards, final answer as the message body.
 * Stop works via the shared AbortController.
 */
import { apiFetch } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
import { appendStep } from '../../shared/runlog.js';
import {
  getAbortController, setAbortController,
  getSelectedModel, getActiveChatId,
} from '../../core/state.js';

console.log('[Module] agent_mode.js loaded');

// Use shared RunLog (includes approval cards)
function stepCard(step) {
  const div = document.createElement('div');
  // appendStep returns the element and handles all kinds including approval_needed
  const tmp = document.createElement('div');
  appendStep(tmp, step);
  if (tmp.firstChild) div.appendChild(tmp.firstChild);
  return div;
}

/**
 * Run agent mode for a user message. Appends an assistant node with
 * live step cards, then the final answer. Returns the answer text.
 */
export async function runAgentGeneration({ content, messagesEl, scrollToBottom, onDone }) {
  const model = getSelectedModel();
  const node = document.createElement('div');
  node.className = 'msg assistant agent-mode-msg';
  node.setAttribute('role', 'article');
  node.innerHTML = `
    <div class="msg-avatar" aria-hidden="true"><i class="fa-solid fa-robot"></i></div>
    <div class="msg-body">
      <div class="msg-meta"><span class="msg-author">${escapeHtml(model?.name || 'Agent')}</span>
      <span class="msg-agent-badge"><i class="fa-solid fa-robot"></i> agent mode</span></div>
      <div class="agent-steps"></div>
      <article class="assistant-response" aria-live="polite"></article>
    </div>`;
  messagesEl.appendChild(node);
  scrollToBottom(true);
  const stepsEl = node.querySelector('.agent-steps');
  const bodyEl = node.querySelector('.assistant-response');

  const controller = new AbortController();
  setAbortController(controller);
  let answer = '';
  let stopped = false;

  try {
    const res = await apiFetch('/agent/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: content,
        model: model?.id || '',
        max_steps: 8,
      }),
      signal: controller.signal,
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
        let step;
        try { step = JSON.parse(line.slice(5).trim()); } catch { continue; }
        if (step.kind === 'end' || step.kind === 'done') continue;
        if (step.kind === 'answer') {
          answer = step.content;
          bodyEl.innerHTML = `<p>${escapeHtml(answer).replace(/\n/g, '<br>')}</p>`;
        } else {
          const card = stepCard(step);
          if (card.innerHTML) { stepsEl.appendChild(card); scrollToBottom(true); }
        }
      }
    }
  } catch (err) {
    if (err?.name === 'AbortError') {
      stopped = true;
    } else {
      stepsEl.appendChild(stepCard({ kind: 'error', content: String(err?.message || err) }));
      showToast({ type: 'warning', title: 'Agent mode', message: 'Agent run failed.' });
    }
  } finally {
    setAbortController(null);
  }
  if (stopped && !answer) {
    bodyEl.innerHTML = `<p class="msg-stopped"><i>Stopped.</i></p>`;
  }
  onDone?.(answer, stopped);
  return answer;
}

/** Abort the running agent loop (wired to the stop button). */
export function stopAgent() {
  getAbortController()?.abort();
}
