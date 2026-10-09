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
  const btn = document.getElementById('learnBtn');
  if (btn && !btn.dataset.wired) {
    btn.dataset.wired = '1';
    btn.addEventListener('click', openLearnModal);
  }
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

function ensureModal() {
  let overlay = document.getElementById('learnOverlay');
  if (overlay) return overlay;
  overlay = document.createElement('div');
  overlay.id = 'learnOverlay';
  overlay.className = 'modal-overlay hidden';
  overlay.innerHTML = `
    <div class="modal learn-modal" role="dialog" aria-modal="true" aria-labelledby="learnModalTitle">
      <div class="modal-header">
        <h2 id="learnModalTitle"><i class="fa-solid fa-graduation-cap"></i> Learn</h2>
        <button class="icon-btn ghost" id="closeLearn" aria-label="Close learn"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div class="learn-body">
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
      </div>
    </div>`;
  document.body.appendChild(overlay);
  overlay.querySelector('#closeLearn').addEventListener('click', () => overlay.classList.add('hidden'));
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.classList.add('hidden'); });
  overlay.querySelector('#learnStart').addEventListener('click', startLesson);
  overlay.querySelector('#learnTopic').addEventListener('keydown', (e) => { if (e.key === 'Enter') startLesson(); });
  overlay.querySelector('#learnCheck').addEventListener('click', checkAnswer);
  return overlay;
}

export function openLearnModal() {
  const overlay = ensureModal();
  overlay.classList.remove('hidden');
  setTimeout(() => overlay.querySelector('#learnTopic')?.focus(), 0);
}

function setBusy(busy, label) {
  const btn = document.getElementById('learnStart');
  if (btn) { btn.disabled = busy; if (label) btn.textContent = label; }
  const check = document.getElementById('learnCheck');
  if (check) check.disabled = busy;
}

async function startLesson() {
  const overlay = document.getElementById('learnOverlay');
  const topic = overlay.querySelector('#learnTopic').value.trim();
  if (!topic) return;
  const lessonEl = overlay.querySelector('#learnLesson');
  const answerWrap = overlay.querySelector('#learnAnswerWrap');
  const feedbackEl = overlay.querySelector('#learnFeedback');
  setBusy(true, 'Teaching…');
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
    setBusy(false, 'Start lesson');
  }
}

async function checkAnswer() {
  const overlay = document.getElementById('learnOverlay');
  const topic = overlay.querySelector('#learnTopic').value.trim();
  const answer = overlay.querySelector('#learnAnswer').value.trim();
  if (!answer || !currentLesson) return;
  const feedbackEl = overlay.querySelector('#learnFeedback');
  setBusy(true);
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
