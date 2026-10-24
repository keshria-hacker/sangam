/**
 * Work destination — Batch 1 UX consolidation.
 *
 * One destination for everything that *does* work: Agents (incl. Teams,
 * Compare, Automations inside the Agents page), Code, Workflows, and the
 * Activity feed (the old Runs centre, plus media jobs and workflow runs).
 * The four sections are mount-once and reuse the existing page renderers,
 * so no behaviour is rewritten here — only the navigation is consolidated.
 * Old ids (agents, code, workflows, runs, teams, compare) resolve here via
 * tabs.js ALIASES; this module registers the section activator for them.
 */
import { registerSectionActivator } from '../tabs/tabs.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] work.js loaded');

const SECTIONS = [
  { id: 'agents',    label: 'Agents',    desc: 'Run agents and teams, compare models, schedule automations.' },
  { id: 'code',      label: 'Code',      desc: 'The code agent: describe a task, review the diff.' },
  { id: 'workflows', label: 'Workflows', desc: 'Build and run DAG workflows; replay and inspect nodes.' },
  { id: 'activity',  label: 'Activity',  desc: 'Live runs, run history, media jobs, workflow runs, artifacts.' },
];

const LOADERS = {
  agents: async () => (await import('../agents/hub.js')).renderAgentsPage,
  code: async () => (await import('../code-agent/code-agent.js')).renderCodePage,
  workflows: async () => (await import('../workflows/workflows.js')).renderWorkflowsTab,
  activity: async () => (await import('../runs/runs.js')).renderRunsTab,
};

export async function renderWorkPage(bodyEl) {
  bodyEl.innerHTML = `
    <div class="work-page">
      <div class="library-tabs" role="tablist" aria-label="Work sections">
        ${SECTIONS.map((s, i) => `
          <button class="library-tab${i === 0 ? ' active' : ''}" role="tab"
            data-worksection="${s.id}" aria-selected="${i === 0}">
            ${escapeHtml(s.label)}
          </button>`).join('')}
      </div>
      <p class="settings-hint" id="workSectionDesc">${escapeHtml(SECTIONS[0].desc)}</p>
      <div class="work-subbody" id="workSubBody"></div>
    </div>`;
  const subBody = bodyEl.querySelector('#workSubBody');
  const descEl = bodyEl.querySelector('#workSectionDesc');
  const mounted = new Map(); // section -> container

  async function show(id) {
    const section = SECTIONS.find((s) => s.id === id) || SECTIONS[0];
    bodyEl.querySelectorAll('[data-worksection]').forEach((b) => {
      const on = b.dataset.worksection === section.id;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', String(on));
    });
    descEl.textContent = section.desc;
    let container = mounted.get(section.id);
    if (!container) {
      container = document.createElement('div');
      container.className = 'work-section-body';
      subBody.appendChild(container);
      mounted.set(section.id, container);
      const render = await LOADERS[section.id]();
      await render(container);
    }
    subBody.querySelectorAll('.work-section-body').forEach((el) => {
      el.classList.toggle('hidden', el !== container);
    });
  }

  bodyEl.querySelectorAll('[data-worksection]').forEach((b) => {
    b.addEventListener('click', () => show(b.dataset.worksection));
  });
  registerSectionActivator('work', (section) => show(section));
  await show('agents');
}
