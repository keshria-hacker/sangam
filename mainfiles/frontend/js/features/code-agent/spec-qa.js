// spec-qa.js — A5 frontend module (Code destination, unmounted).
// Renders the spec-pipeline v2 + QA status for a pipeline using only
// the A5 API surface (/api/spec-v2/*, /api/qa/*, /api/code-graph/*).
// This module is NOT mounted by the shell yet: the coordinator (A1)
// owns shell/tab wiring and mounts it in the Code destination at
// merge time, so this file only provides the panel renderer + API
// helpers and must parse/link standalone (no imports).
console.log('[Module] spec-qa.js loaded');

export const SPEC_V2_STAGES = [
  'constitution', 'spec', 'clarify', 'plan', 'checklist', 'tasks',
  'analyze', 'implement', 'verify', 'converge',
];

export function specQaPanelHtml(pipeline) {
  const stages = (pipeline && pipeline.stage_artifacts) || [];
  const done = new Set(stages.map((s) => s.stage));
  const rows = SPEC_V2_STAGES.map((stage) => {
    const mark = done.has(stage) ? 'done' : 'pending';
    return `<li data-stage="${stage}" data-state="${mark}">${stage}: ${mark}</li>`;
  }).join('');
  const title = pipeline && pipeline.title ? pipeline.title : 'Spec pipeline';
  return `<section class="spec-qa-panel" aria-label="Spec pipeline status">`
    + `<h2>${title}</h2><ol>${rows}</ol>`
    + `<p>TDD evidence (RED + GREEN) is required before the implement stage; `
    + `GreenContract verification starts at the targeted level.</p></section>`;
}

export async function fetchSpecPipeline(apiFetch, pipelineId) {
  const res = await apiFetch(`/spec-v2/${pipelineId}`);
  return res;
}

export async function fetchQaLevels(apiFetch) {
  return apiFetch('/qa/levels');
}
