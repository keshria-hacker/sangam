/**
 * Skills feature - Skills browser modal and execution.
 */

import { getApiBaseUrl, apiFetch, apiPost } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] skills.js loaded');

let elements = {};
let state = { skills: [], filtered: [], selected: null, query: '', category: 'all', invocation: 'all' };

/**
 * Initialize DOM references.
 */
export function initElements(overlay) {
  elements = {
    list: overlay?.querySelector('#skillsList'),
    detail: overlay?.querySelector('#skillsDetail'),
    search: overlay?.querySelector('#skillsSearch'),
    categories: overlay?.querySelector('#skillsCategories'),
    invocations: overlay?.querySelector('#skillsInvocations'),
  };
}

/**
 * Apply filters to skills list.
 */
function applyFilters() {
  const query = state.query.trim().toLowerCase();
  state.filtered = state.skills.filter((skill) => {
    const searchable = [skill.name, skill.desc, ...(skill.tags || [])].join(' ').toLowerCase();
    return (!query || searchable.includes(query))
      && (state.category === 'all' || skill.cat === state.category)
      && (state.invocation === 'all' || skill.inv === state.invocation || skill.inv === 'both');
  });
}

/**
 * Render skills list grouped by category.
 */
function renderList() {
  if (!elements.list) return;
  if (!state.filtered.length) {
    elements.list.innerHTML = '<div class="no-results">No skills match these filters.</div>';
    return;
  }

  const groups = state.filtered.reduce((result, skill) => {
    (result[skill.cat] ||= []).push(skill);
    return result;
  }, {});

  elements.list.innerHTML = Object.entries(groups).map(([category, skills]) => `
    <section class="skill-category">
      <h4>${escapeHtml(category)}</h4>
      <div class="skill-grid">${skills.map((skill) => `
        <button class="skill-card ${state.selected?.id === skill.id ? 'selected' : ''}" type="button"
                data-skill-id="${escapeHtml(skill.id)}" title="${escapeHtml(skill.desc)}">
          <span>${escapeHtml(skill.name)}</span>
          <span>${escapeHtml(skill.src)}</span>
          <span class="inv-${escapeHtml(skill.inv)}">${escapeHtml(skill.inv)}</span>
        </button>`).join('')}
      </div>
    </section>`).join('');

  elements.list.querySelectorAll('[data-skill-id]').forEach((button) => {
    button.addEventListener('click', () => selectSkill(button.dataset.skillId));
  });
}

/**
 * Render skill detail panel.
 */
function renderDetail(skill) {
  if (!elements.detail) return;
  const parameters = skill.params || [];
  const dependencies = skill.deps || [];

  elements.detail.innerHTML = `
    <h3>${escapeHtml(skill.name)}</h3>
    <div class="badges">
      <span class="badge cat-${escapeHtml(skill.cat)}">${escapeHtml(skill.cat)}</span>
      <span class="badge inv-${escapeHtml(skill.inv)}">${escapeHtml(skill.inv)}</span>
      <span class="badge src">${escapeHtml(skill.src)}</span>
    </div>
    <p>${escapeHtml(skill.desc)}</p>
    ${parameters.length ? `<div><h4>Parameters</h4>${parameters.map((parameter) => `
      <div class="pi">
        <label for="skill-param-${escapeHtml(parameter.n)}">${escapeHtml(parameter.n)} <span>${escapeHtml(parameter.t)}${parameter.r ? ' · required' : ''}</span></label>
        <p>${escapeHtml(parameter.d)}</p>
        <input id="skill-param-${escapeHtml(parameter.n)}" data-param="${escapeHtml(parameter.n)}" data-required="${Boolean(parameter.r)}" placeholder="${parameter.r ? 'Required' : 'Optional'}" ${parameter.def ? `value="${escapeHtml(parameter.def)}"` : ''}>
      </div>`).join('')}</div>` : '<p>No parameters required.</p>'}
    ${dependencies.length ? `<div><h4>Dependencies</h4><p>${dependencies.map(escapeHtml).join(' → ')}</p></div>` : ''}
    <div class="skill-actions">
      <button id="executeSkillBtn" type="button">Execute</button>
      <button id="copySkillBtn" type="button">Copy command</button>
    </div>`;

  elements.detail.querySelector('#executeSkillBtn').addEventListener('click', executeSkill);
  elements.detail.querySelector('#copySkillBtn').addEventListener('click', copyCommand);
}

/**
 * Select a skill and load its details.
 */
async function selectSkill(id) {
  try {
    const skillRes = await apiFetch(`/skills/${encodeURIComponent(id)}`);
    const skill = await skillRes.json();
    state.selected = skill;
    renderList();
    renderDetail(skill);
  } catch (error) {
    elements.detail.innerHTML = `<div class="no-results">Could not load this skill: ${escapeHtml(error.message)}</div>`;
  }
}

/**
 * Execute the selected skill.
 */
async function executeSkill() {
  if (!state.selected) return;
  const button = elements.detail.querySelector('#executeSkillBtn');
  const params = {};
  const missing = [];

  elements.detail.querySelectorAll('[data-param]').forEach((input) => {
    const value = input.value.trim();
    if (value) params[input.dataset.param] = value;
    else if (input.dataset.required === 'true') missing.push(input.dataset.param);
  });

  if (missing.length) {
    elements.detail.insertAdjacentHTML('beforeend', `<div class="no-results">Required: ${escapeHtml(missing.join(', '))}</div>`);
    return;
  }

  button.disabled = true;
  button.textContent = 'Running…';
  try {
    const exeRes = await apiPost('/skills/execute', { skill_id: state.selected.id, params });
    const result = await exeRes.json();
    elements.detail.insertAdjacentHTML('beforeend', `<div class="skill-result"><h4>Result</h4><pre>${escapeHtml(result.result || 'Completed without output.')}</pre></div>`);
  } catch (error) {
    elements.detail.insertAdjacentHTML('beforeend', `<div class="no-results">Could not execute skill: ${escapeHtml(error.message)}</div>`);
  } finally {
    button.disabled = false;
    button.textContent = 'Execute';
  }
}

/**
 * Copy skill command to clipboard.
 */
async function copyCommand() {
  if (!state.selected) return;
  const button = elements.detail.querySelector('#copySkillBtn');
  try {
    await navigator.clipboard.writeText(`/skill ${state.selected.src}:${state.selected.id}`);
    button.textContent = 'Copied';
  } catch (_) {
    button.textContent = 'Copy unavailable';
  }
  setTimeout(() => { button.textContent = 'Copy command'; }, 1600);
}

/**
 * Load skills from backend.
 */
async function loadSkills() {
  elements.list.innerHTML = '<div class="loading">Loading skills…</div>';
  try {
    const skillsRes = await apiFetch('/skills');
    state.skills = await skillsRes.json();
    applyFilters();
    renderList();
  } catch (error) {
    elements.list.innerHTML = `<div class="no-results">Could not load skills: ${escapeHtml(error.message)}</div>`;
  }
}

/**
 * Open the skills modal.
 */
export function openSkillsModal(overlay) {
  if (!overlay) return;
  overlay.classList.remove('hidden');
  loadSkills();
}
/**
 * Close the skills modal.
 */
export function closeSkillsModal() {
  const overlay = document.getElementById('skillsOverlay');
  if (overlay) overlay.classList.add('hidden');
}

/**
 * Public initialization function for the skills modal.
 */
export function init(overlay) {
  initElements(overlay);
  if (!elements.list || !elements.detail) return;

  elements.search.oninput = (event) => { state.query = event.target.value; applyFilters(); renderList(); };
  elements.categories.onclick = (event) => {
    const button = event.target.closest('[data-category]');
    if (!button) return;
    state.category = button.dataset.category;
    elements.categories.querySelectorAll('button').forEach((item) => item.classList.toggle('active', item === button));
    applyFilters(); renderList();
  };
  elements.invocations.onclick = (event) => {
    const button = event.target.closest('[data-invocation]');
    if (!button) return;
    state.invocation = button.dataset.invocation;
    elements.invocations.querySelectorAll('button').forEach((item) => item.classList.toggle('active', item === button));
    applyFilters(); renderList();
  };
}