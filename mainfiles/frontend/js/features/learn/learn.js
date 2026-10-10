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
import { trapFocus } from '../../shared/focus_trap.js';
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
  // Navigation via studio rail — nothing to unhide.
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
        <button class="btn-secondary" id="learnOutline" type="button" title="Generate editable outline">
          <i class="fa-solid fa-list"></i> Outline
        </button>
        <button class="btn-secondary" id="learnImportSkill" type="button" title="Import a SKILL.md">
          <i class="fa-solid fa-file-import"></i> Import skill
        </button>
      </div>
      <div class="learn-outline hidden" id="learnOutlineWrap"></div>
      <div class="learn-lesson hidden" id="learnLesson"></div>
      <div class="learn-scenes hidden" id="learnScenes"></div>
      <div class="learn-answer hidden" id="learnAnswerWrap">
        <textarea id="learnAnswer" rows="3" placeholder="Your answer to the check question…" aria-label="Your answer"></textarea>
        <button class="btn-secondary" id="learnCheck" type="button">Check my answer</button>
        <button class="btn-secondary" id="learnQuiz" type="button">Take quiz</button>
      </div>
      <div class="learn-feedback hidden" id="learnFeedback"></div>
      <div class="learn-quiz hidden" id="learnQuizWrap"></div>
    </div>`;
  bodyEl.querySelector('#learnStart').addEventListener('click', () => startLesson(bodyEl));
  bodyEl.querySelector('#learnTopic').addEventListener('keydown', (e) => { if (e.key === 'Enter') startLesson(bodyEl); });
  bodyEl.querySelector('#learnCheck').addEventListener('click', () => checkAnswer(bodyEl));
  bodyEl.querySelector('#learnOutline').addEventListener('click', () => generateOutline(bodyEl));
  bodyEl.querySelector('#learnQuiz').addEventListener('click', () => generateQuiz(bodyEl));
  bodyEl.querySelector('#learnImportSkill').addEventListener('click', () => openSkillImporter(bodyEl));
  setTimeout(() => bodyEl.querySelector('#learnTopic')?.focus(), 0);
}

// Back-compat: old modal entry point now opens the tab
export function openLearnModal() {
  import('../tabs/tabs.js').then(({ showTool }) => showTool('learn'));
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
  overlay.querySelector('#learnScenes')?.classList.add('hidden');
  try {
    const data = await (await apiPost('/learn/lesson', { topic })).json();
    currentLesson = data.lesson || '';
    lessonEl.innerHTML = renderMarkdown(currentLesson)
      + `<div class="learn-lesson-actions">
           <button class="btn-secondary btn-sm" id="learnScenesBtn" type="button">
             <i class="fa-solid fa-scissors"></i> Break into scenes
           </button>
         </div>`;
    lessonEl.classList.remove('hidden');
    overlay.querySelector('#learnScenes').classList.add('hidden');
    overlay.querySelector('#learnScenes').innerHTML = '';
    lessonEl.querySelector('#learnScenesBtn')?.addEventListener('click', () => breakIntoScenes(overlay));
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

/** Phase 7: Generate an editable outline from the backend. */
async function generateOutline(container) {
  const root = container || document.getElementById('toolViewBody') || document;
  const topic = root.querySelector('#learnTopic').value.trim();
  if (!topic) {
    showToast({ type: 'info', title: 'Enter a topic first' });
    return;
  }
  const wrap = root.querySelector('#learnOutlineWrap');
  wrap.classList.remove('hidden');
  wrap.innerHTML = '<p class="settings-hint">Generating outline…</p>';
  try {
    const data = await (await apiPost('/learn/outline', { topic })).json();
    const outline = data.outline || [];
    wrap.innerHTML = `
      <h4>Outline: ${escapeHtml(data.topic)}</h4>
      <div class="learn-outline-list">
        ${outline.map((s, i) => `
          <div class="learn-outline-sec" data-idx="${i}">
            <input class="provider-key-input" data-title value="${escapeHtml(s.title || '')}" aria-label="Section title">
            <textarea rows="3" data-points aria-label="Key points">${escapeHtml((s.points || []).join('\n'))}</textarea>
            <div class="learn-outline-meta">
              <label>Minutes: <input type="number" data-duration value="${s.duration_min || 5}" min="1" max="60" style="width:60px"></label>
              <button class="icon-btn" data-del aria-label="Remove section"><i class="fa-solid fa-trash"></i></button>
            </div>
          </div>`).join('')}
      </div>
      <div class="learn-outline-actions">
        <button class="btn-secondary btn-sm" id="learnOutlineAdd" type="button">+ Add section</button>
        <button class="btn-primary btn-sm" id="learnOutlineUse" type="button">Use this outline</button>
      </div>`;
    // Wire delete buttons
    wrap.querySelectorAll('[data-del]').forEach((btn) => {
      btn.addEventListener('click', () => btn.closest('.learn-outline-sec').remove());
    });
    // Add section
    wrap.querySelector('#learnOutlineAdd').addEventListener('click', () => {
      const list = wrap.querySelector('.learn-outline-list');
      const div = document.createElement('div');
      div.className = 'learn-outline-sec';
      div.innerHTML = `
        <input class="provider-key-input" data-title placeholder="Section title" aria-label="Section title">
        <textarea rows="3" data-points placeholder="Key points (one per line)" aria-label="Key points"></textarea>
        <div class="learn-outline-meta">
          <label>Minutes: <input type="number" data-duration value="5" min="1" max="60" style="width:60px"></label>
          <button class="icon-btn" data-del aria-label="Remove section"><i class="fa-solid fa-trash"></i></button>
        </div>`;
      div.querySelector('[data-del]').addEventListener('click', () => div.remove());
      list.appendChild(div);
    });
    // Use outline → start lesson with outline context
    wrap.querySelector('#learnOutlineUse').addEventListener('click', () => {
      const sections = [...wrap.querySelectorAll('.learn-outline-sec')].map((sec) => ({
        title: sec.querySelector('[data-title]').value,
        points: sec.querySelector('[data-points]').value.split('\n').filter((p) => p.trim()),
        duration_min: parseInt(sec.querySelector('[data-duration]').value, 10) || 5,
      })).filter((s) => s.title.trim());
      if (!sections.length) {
        showToast({ type: 'info', title: 'Add at least one section' });
        return;
      }
      // Store outline and start lesson
      window.__learnOutline = sections;
      showToast({ type: 'success', title: `Outline saved (${sections.length} sections)` });
      startLesson(root);
    });
  } catch (err) {
    wrap.innerHTML = `<p class="team-error">Outline failed: ${escapeHtml(err?.message || String(err))}</p>`;
  }
}

/** Phase 7: Generate a quiz and grade answers. */
async function generateQuiz(container) {
  const root = container || document.getElementById('toolViewBody') || document;
  const topic = root.querySelector('#learnTopic').value.trim();
  if (!topic || !currentLesson) {
    showToast({ type: 'info', title: 'Start a lesson first' });
    return;
  }
  const wrap = root.querySelector('#learnQuizWrap');
  wrap.classList.remove('hidden');
  wrap.innerHTML = '<p class="settings-hint">Generating quiz…</p>';
  try {
    const data = await (await apiPost('/learn/quiz', { topic, lesson: currentLesson, num_questions: 5 })).json();
    const questions = data.questions || [];
    if (!questions.length) {
      wrap.innerHTML = '<p class="settings-hint">No questions generated.</p>';
      return;
    }
    wrap.innerHTML = `
      <h4>Quiz: ${escapeHtml(topic)}</h4>
      <div class="learn-quiz-list">
        ${questions.map((q, i) => `
          <div class="learn-quiz-q" data-idx="${i}">
            <p><strong>Q${i + 1}.</strong> ${escapeHtml(q.question)}</p>
            <div class="learn-quiz-opts">
              ${(q.options || []).map((opt) => `
                <label><input type="radio" name="q${i}" value="${escapeHtml(opt)}"> ${escapeHtml(opt)}</label>
              `).join('')}
            </div>
          </div>`).join('')}
      </div>
      <button class="btn-primary" id="learnQuizSubmit" type="button">Submit answers</button>
      <div id="learnQuizResult" class="hidden"></div>`;
    wrap.querySelector('#learnQuizSubmit').addEventListener('click', async () => {
      const answers = questions.map((_, i) => {
        const sel = wrap.querySelector(`input[name="q${i}"]:checked`);
        return sel ? sel.value : '';
      });
      if (answers.some((a) => !a)) {
        showToast({ type: 'info', title: 'Answer all questions first' });
        return;
      }
      try {
        const result = await (await apiPost('/learn/grade', { topic, questions, answers })).json();
        const resEl = wrap.querySelector('#learnQuizResult');
        resEl.classList.remove('hidden');
        resEl.innerHTML = `
          <h4>Score: ${result.score}/${result.total} (${result.percentage}%)</h4>
          ${result.results.map((r, i) => `
            <div class="learn-quiz-r ${r.correct ? 'correct' : 'wrong'}">
              <p><strong>Q${i + 1}.</strong> ${escapeHtml(r.question)}</p>
              <p>Your answer: ${escapeHtml(r.your_answer)} ${r.correct ? '✓' : '✗'}</p>
              ${!r.correct ? `<p>Correct: ${escapeHtml(r.correct_answer)}</p>` : ''}
              ${r.explanation ? `<p class="settings-hint">${escapeHtml(r.explanation)}</p>` : ''}
            </div>`).join('')}`;
        resEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      } catch (err) {
        showToast({ type: 'error', title: 'Grading failed', message: String(err?.message || err) });
      }
    });
    wrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (err) {
    wrap.innerHTML = `<p class="team-error">Quiz failed: ${escapeHtml(err?.message || String(err))}</p>`;
  }
}

// --- Outline → scenes --------------------------------------------------------
// No /api/learn/scenes endpoint exists, so scenes are split client-side on
// H2 (##) headers, falling back to H3 (###).

function splitScenes(markdown) {
  const lines = (markdown || '').split('\n');
  const scenes = [];
  let cur = null;
  let level = 2; // split on H2; fall back to H3 if no H2 found
  const push = () => { if (cur && cur.body.trim()) scenes.push(cur); };
  for (const line of lines) {
    const h2 = line.match(/^##\s+(.*)/);
    const h3 = line.match(/^###\s+(.*)/);
    if (h2) { level = 2; push(); cur = { title: h2[1].trim(), body: '' }; }
    else if (h3 && (level === 3 || scenes.length === 0)) {
      if (scenes.length === 0 && !cur) level = 3; // no H2s at all — use H3
      if (level === 3) { push(); cur = { title: h3[1].trim(), body: '' }; }
      else if (cur) cur.body += line + '\n';
    }
    else if (cur) { cur.body += line + '\n'; }
  }
  push();
  // If no headers at all, chunk by paragraphs into up to 4 scenes
  if (!scenes.length) {
    const paras = (markdown || '').split(/\n\s*\n/).filter((p) => p.trim());
    const per = Math.max(1, Math.ceil(paras.length / 4));
    for (let i = 0; i < paras.length; i += per) {
      scenes.push({ title: `Part ${scenes.length + 1}`, body: paras.slice(i, i + per).join('\n\n') });
    }
  }
  return scenes.slice(0, 6);
}

function breakIntoScenes(container) {
  const overlay = container || document.getElementById('toolViewBody') || document;
  const wrap = overlay.querySelector('#learnScenes');
  if (!wrap || !currentLesson) return;
  const scenes = splitScenes(currentLesson);
  if (!scenes.length) {
    showToast({ type: 'info', title: 'No scenes found', message: 'The lesson has no clear sections to split.' });
    return;
  }
  wrap.innerHTML = `<h4 class="learn-scenes-title">
      <i class="fa-solid fa-film"></i> ${scenes.length} scenes
      <span class="settings-hint">— teach each one separately</span></h4>
    <div class="learn-scene-grid">` + scenes.map((s, i) => `
      <div class="learn-scene-card" data-scene="${i}">
        <div class="learn-scene-title">${escapeHtml(s.title)}</div>
        <div class="learn-scene-excerpt">${escapeHtml(s.body.replace(/[#*`_>\-]/g, '').slice(0, 180).trim())}…</div>
        <button class="btn-secondary btn-sm" type="button" data-teach="${i}">
          <i class="fa-solid fa-person-chalkboard"></i> Teach me
        </button>
      </div>`).join('') + `</div>`;
  wrap.classList.remove('hidden');
  wrap.querySelectorAll('[data-teach]').forEach((btn) => {
    btn.addEventListener('click', () => teachScene(overlay, scenes[Number(btn.dataset.teach)]));
  });
  wrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function teachScene(container, scene) {
  const overlay = container || document.getElementById('toolViewBody') || document;
  if (!scene) return;
  currentLesson = `## ${scene.title}\n\n${scene.body}`;
  const lessonEl = overlay.querySelector('#learnLesson');
  lessonEl.innerHTML = renderMarkdown(currentLesson)
    + `<div class="learn-lesson-actions">
         <button class="btn-secondary btn-sm" id="learnScenesBtn" type="button">
           <i class="fa-solid fa-scissors"></i> Break into scenes
         </button>
       </div>`;
  lessonEl.querySelector('#learnScenesBtn')?.addEventListener('click', () => breakIntoScenes(overlay));
  const answerEl = overlay.querySelector('#learnAnswer');
  if (answerEl) answerEl.value = '';
  overlay.querySelector('#learnAnswerWrap')?.classList.remove('hidden');
  lessonEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
  showToast({ type: 'info', title: `Scene: ${scene.title}`, message: 'Answer the check question when ready.' });
}

// --- Skill importer ----------------------------------------------------------
// No /api/skills/import or POST /api/skills endpoint exists (frontend-only
// task), so imported skills are validated + previewed, then saved as local
// drafts until a backend install endpoint lands.

const SKILL_DRAFTS_KEY = 'sangam:skill-drafts';

export function getSkillDrafts() {
  try { return JSON.parse(localStorage.getItem(SKILL_DRAFTS_KEY) || '[]'); }
  catch { return []; }
}

function saveSkillDraft(draft) {
  const drafts = getSkillDrafts().filter((d) => d.name !== draft.name);
  drafts.unshift({ ...draft, savedAt: new Date().toISOString() });
  try { localStorage.setItem(SKILL_DRAFTS_KEY, JSON.stringify(drafts.slice(0, 50))); } catch {}
}

function parseSkillName(content) {
  const fm = (content || '').match(/^---\s*\n([\s\S]*?)\n---/);
  if (fm) {
    const nameLine = fm[1].split('\n').find((l) => /^\s*name\s*:/i.test(l));
    if (nameLine) return nameLine.split(':').slice(1).join(':').trim().replace(/^['"]|['"]$/g, '');
  }
  const h1 = (content || '').match(/^#\s+(.+)$/m);
  if (h1) return h1[1].trim();
  return '';
}

export function openSkillImporter(hostEl) {
  const host = hostEl || document.body;
  const old = document.getElementById('skillImportModal');
  if (old) old.remove();
  const modal = document.createElement('div');
  modal.id = 'skillImportModal';
  modal.className = 'modal-overlay';
  modal.innerHTML = `
    <div class="modal skill-import-modal" role="dialog" aria-label="Import skill">
      <div class="modal-header">
        <h3><i class="fa-solid fa-file-import"></i> Import skill</h3>
        <button class="icon-btn" data-close aria-label="Close"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div class="modal-body">
        <label class="settings-label">From URL <span class="settings-hint">(best effort — some sites block cross-origin fetch)</span></label>
        <div class="skill-import-urlrow">
          <input id="skillUrl" class="provider-key-input" placeholder="https://…/SKILL.md" aria-label="Skill URL">
          <button class="btn-secondary" id="skillFetch" type="button">Fetch</button>
        </div>
        <label class="settings-label">Or pick a file</label>
        <input type="file" id="skillFile" accept=".md,.markdown,text/markdown" class="skill-file-input">
        <label class="settings-label">Or pick a skill folder <span class="settings-hint">(looks for SKILL.md inside)</span></label>
        <input type="file" id="skillFolder" webkitdirectory directory class="skill-file-input" aria-label="Skill folder">
        <label class="settings-label">Or paste SKILL.md content</label>
        <textarea id="skillContent" rows="10" class="provider-key-input skill-textarea"
          placeholder="# my-skill&#10;&#10;Instructions for the agent…"></textarea>
        <div class="skill-preview hidden" id="skillPreview"></div>
        <div class="skill-risk hidden" id="skillRisk"></div>
        <div class="skill-version hidden" id="skillVersion"></div>
        <p class="settings-hint">No backend install endpoint exists yet — imports are saved as
          <strong>local drafts</strong> on this device until then.</p>
      </div>
      <div class="modal-footer">
        <button class="btn-secondary" data-close type="button">Cancel</button>
        <button class="btn-primary" id="skillInstall" type="button" disabled>Save draft</button>
      </div>
    </div>`;
  host.appendChild(modal);
  let releaseTrap = null;
  const close = () => { releaseTrap?.(); modal.remove(); };
  modal.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', close));
  modal.addEventListener('click', (e) => { if (e.target === modal) close(); });
  modal.setAttribute('aria-modal', 'true');
  releaseTrap = trapFocus(modal);

  const contentEl = modal.querySelector('#skillContent');
  const previewEl = modal.querySelector('#skillPreview');
  const installBtn = modal.querySelector('#skillInstall');

  const refreshPreview = () => {
    const content = contentEl.value.trim();
    if (content.length < 20) {
      previewEl.classList.add('hidden');
      installBtn.disabled = true;
      return;
    }
    const name = parseSkillName(content) || '(unnamed skill)';
    const lines = content.split('\n').length;
    previewEl.innerHTML = `<i class="fa-solid fa-wand-magic-sparkles"></i>
      <strong>${escapeHtml(name)}</strong>
      <span class="settings-hint">${lines} lines · ${content.length} chars</span>`;
    previewEl.classList.remove('hidden');
    installBtn.disabled = false;
  };
  contentEl.addEventListener('input', refreshPreview);

  modal.querySelector('#skillFetch').addEventListener('click', async () => {
    const url = modal.querySelector('#skillUrl').value.trim();
    if (!url) return;
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      contentEl.value = await res.text();
      refreshPreview();
      showToast({ type: 'success', title: 'Fetched skill' });
    } catch (err) {
      showToast({ type: 'error', title: 'Fetch failed', message: `${err?.message || err} — paste the content instead.` });
    }
  });

  modal.querySelector('#skillFile').addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => { contentEl.value = String(reader.result || ''); refreshPreview(); };
    reader.readAsText(file);
  });

  // Folder import: find SKILL.md in selected folder
  modal.querySelector('#skillFolder').addEventListener('change', (e) => {
    const files = Array.from(e.target.files || []);
    const skillFile = files.find((f) => f.name.toLowerCase() === 'skill.md');
    if (!skillFile) {
      showToast({ type: 'error', title: 'No SKILL.md found', message: 'The selected folder does not contain a SKILL.md file.' });
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      contentEl.value = String(reader.result || '');
      refreshPreview();
      showToast({ type: 'success', title: 'Folder imported', message: `Found ${skillFile.name} (${files.length} files total).` });
    };
    reader.readAsText(skillFile);
  });

  // Risk scan: check for dangerous patterns
  const scanRisks = (content) => {
    const risks = [];
    const patterns = [
      [/rm\s+-rf\s+\//i, 'Deletes files recursively from root'],
      [/curl.*\|\s*bash/i, 'Downloads and executes remote script'],
      [/wget.*\|\s*sh/i, 'Downloads and executes remote script'],
      [/eval\s*\(/i, 'Uses eval() — arbitrary code execution'],
      [/exec\s*\(/i, 'Uses exec() — arbitrary code execution'],
      [/\bpassword\b.*[:=]/i, 'May contain hardcoded password'],
      [/\bapi[_-]?key\b.*[:=]\s*['"][^'"]+['"]/i, 'May contain hardcoded API key'],
    ];
    for (const [pattern, desc] of patterns) {
      if (pattern.test(content)) risks.push(desc);
    }
    return risks;
  };

  // Version pin: extract from frontmatter
  const parseVersion = (content) => {
    const fm = (content || '').match(/^---\s*\n([\s\S]*?)\n---/);
    if (fm) {
      const verLine = fm[1].split('\n').find((l) => /^\s*version\s*:/i.test(l));
      if (verLine) return verLine.split(':').slice(1).join(':').trim().replace(/^['"]|['"]$/g, '');
    }
    return null;
  };

  // Enhanced refreshPreview with risk scan + version
  const origRefresh = refreshPreview;
  const enhancedRefresh = () => {
    origRefresh();
    const content = contentEl.value.trim();
    if (content.length < 20) return;

    // Risk scan
    const riskEl = modal.querySelector('#skillRisk');
    const risks = scanRisks(content);
    if (risks.length) {
      riskEl.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i>
        <strong>Security risks detected:</strong>
        <ul>${risks.map((r) => `<li>${escapeHtml(r)}</li>`).join('')}</ul>`;
      riskEl.classList.remove('hidden');
    } else {
      riskEl.classList.add('hidden');
    }

    // Version pin
    const verEl = modal.querySelector('#skillVersion');
    const version = parseVersion(content);
    if (version) {
      verEl.innerHTML = `<i class="fa-solid fa-tag"></i> Version <strong>${escapeHtml(version)}</strong> detected — will be pinned.`;
      verEl.classList.remove('hidden');
    } else {
      verEl.classList.add('hidden');
    }
  };
  contentEl.removeEventListener('input', refreshPreview);
  contentEl.addEventListener('input', enhancedRefresh);

  installBtn.addEventListener('click', () => {
    const content = contentEl.value.trim();
    const name = parseSkillName(content) || `skill-${Date.now().toString(36)}`;
    const version = parseVersion(content);
    const risks = scanRisks(content);
    saveSkillDraft({ name, content, version, risks, pinnedAt: new Date().toISOString() });
    showToast({ type: 'success', title: 'Skill draft saved', message: `${name}${version ? ` v${version}` : ''} — stored locally.` });
    close();
  });
}
