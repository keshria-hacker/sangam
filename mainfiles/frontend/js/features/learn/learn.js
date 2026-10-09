/**
 * Learning mode UI — interactive classroom (OpenMAIC pattern).
 *
 * Flow: topic -> teacher lesson -> learner answers the check question ->
 * tutor gives Socratic feedback -> repeat. Shown only when the backend
 * `learning` feature flag is on.
 */

import { apiFetch, apiPost } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
import { renderMarkdown } from '../../shared/markdown.js';
console.log('[Module] learn.js loaded');

let currentLesson = '';

export async function initLearn() {
  // Navigation via studio rail (core/nav.js) — no per-button wiring needed.
  let enabled = false;
  try {
    const data = await (await apiFetch('/features')).json();
    enabled = !!(data && data.features && data.features.learning);
  } catch {
    enabled = false;
  }
  if (!enabled) return false;
  btn?.classList.remove('hidden');
  return true;
}

/**
 * Render the Learn UI into a tab body (replaces the old modal).
 */
export function renderLearnTab(bodyEl) {
  bodyEl.innerHTML = `
    <div class="learn-tab">
      <div class="learn-controls">
        <input id="learnTopic" class="provider-key-input" placeholder="What do you want to learn?" aria-label="Topic">
        <button class="btn-primary" id="learnStart" type="button">Start lesson</button>
      </div>
      <div class="learn-lesson hidden" id="learnLesson"></div>
      <div class="learn-answer hidden" id="learnAnswerWrap">
        <textarea id="learnAnswer" rows="3" placeholder="Your answer to the check question…" aria-label="Your answer"></textarea>
        <button class="btn-secondary" id="learnCheck" type="button">Check my answer</button>
      </div>
      <div class="learn-feedback hidden" id="learnFeedback"></div>
    </div>`;
  bodyEl.querySelector('#learnStart').addEventListener('click', () => startLesson(bodyEl));
  bodyEl.querySelector('#learnTopic').addEventListener('keydown', (e) => { if (e.key === 'Enter') startLesson(bodyEl); });
  bodyEl.querySelector('#learnCheck').addEventListener('click', () => checkAnswer(bodyEl));
  setTimeout(() => bodyEl.querySelector('#learnTopic')?.focus(), 0);
}

// Back-compat: old modal entry point now opens the tab
export function openLearnModal() {
  import('../tabs/tabs.js').then(({ openToolTab }) => openToolTab('learn'));
}

function setBusy(busy, label, root) {
  const scope = root || document;
  const btn = scope.querySelector('#learnStart');
  if (btn) { btn.disabled = busy; if (label) btn.textContent = label; }
  const check = scope.querySelector('#learnCheck');
  if (check) check.disabled = busy;
}

async function startLesson(container) {
  const overlay = container || document.getElementById('toolViewBody') || document;
  const topic = overlay.querySelector('#learnTopic').value.trim();
  if (!topic) return;
  const lessonEl = overlay.querySelector('#learnLesson');
  const answerWrap = overlay.querySelector('#learnAnswerWrap');
  const feedbackEl = overlay.querySelector('#learnFeedback');
  setBusy(true, 'Teaching…', overlay);
  lessonEl.classList.add('hidden');
  answerWrap.classList.add('hidden');
  feedbackEl.classList.add('hidden');
  try {
    const data = await (await apiPost('/learn/lesson', { topic })).json();
    currentLesson = data.lesson || '';
    lessonEl.innerHTML = renderMarkdown(currentLesson);
    lessonEl.classList.remove('hidden');
    answerWrap.classList.remove('hidden');
    overlay.querySelector('#learnAnswer').value = '';
    setTimeout(() => overlay.querySelector('#learnAnswer')?.focus(), 0);
  } catch (err) {
    showToast({ type: 'error', title: 'Lesson failed', message: err?.message || String(err) });
  } finally {
    setBusy(false, 'Start lesson', overlay);
  }
}

async function checkAnswer(container) {
  const overlay = container || document.getElementById('toolViewBody') || document;
  const topic = overlay.querySelector('#learnTopic').value.trim();
  const answer = overlay.querySelector('#learnAnswer').value.trim();
  if (!answer || !currentLesson) return;
  const feedbackEl = overlay.querySelector('#learnFeedback');
  setBusy(true, null, overlay);
  try {
    const data = await (await apiPost('/learn/feedback', { topic, lesson: currentLesson, answer })).json();
    feedbackEl.innerHTML = `<h4>Tutor</h4>${renderMarkdown(data.feedback || '')}`;
    feedbackEl.classList.remove('hidden');
    feedbackEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (err) {
    showToast({ type: 'error', title: 'Feedback failed', message: err?.message || String(err) });
  } finally {
    setBusy(false);
  }
}
