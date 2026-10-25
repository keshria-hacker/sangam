// features/studio/a6-studio.js — A6 Studio/Skills/Integrations hooks.
//
// Destination-agnostic helpers for the Studio destination. The shell
// agent (A1) mounts these under Studio; this module has no imports and
// no DOM side effects at import time, so it is safe to load anywhere.
//
// The server is authoritative: these helpers mirror the wording of
// POST /api/providers/preflight and POST /api/providers/cost-ranked
// for instant UI feedback, and the caller must still use the server
// response before blocking an action.

export const A6_CAPABILITY_LABELS = {
  streaming: 'streaming responses',
  tools: 'tool calls',
  reasoning: 'reasoning output',
  vision: 'vision (image input)',
  documents: 'document input',
  citations: 'citations',
  structured_output: 'structured output',
};

export const A6_STUDIO_FAMILIES = [
  'documents',
  'design',
  'diagrams',
  'image',
  'voice',
  'classroom',
];

// Mirror of the server preflight warning: one string per wanted
// capability the model is known NOT to support. capabilities === null
// means unknown — the UI must say "unknown", never "supported".
export function a6PreflightWarnings(capabilities, wanted) {
  if (!capabilities) {
    return ['Capabilities for this model are not in the registry: support is unknown — do not assume this model can do them.'];
  }
  const warnings = [];
  for (const want of wanted || []) {
    if (!capabilities[want]) {
      const label = A6_CAPABILITY_LABELS[want] || want;
      warnings.push(`This model can't do ${label} (${want}).`);
    }
  }
  return warnings;
}

// Mirror of server cost-ranked routing: known prices cheapest-first,
// unknown prices last with cost_known: false (never presented as cheap).
export function a6CostRanked(candidates) {
  const ranked = (candidates || []).map((cand) => {
    const price = cand.price_per_1k_usd;
    const known = typeof price === 'number' && price >= 0;
    return {
      provider: cand.provider,
      model: cand.model,
      price_per_1k_usd: known ? price : null,
      cost_known: known,
    };
  });
  ranked.sort((a, b) => {
    if (a.cost_known !== b.cost_known) return a.cost_known ? -1 : 1;
    if (!a.cost_known) return 0;
    return a.price_per_1k_usd - b.price_per_1k_usd;
  });
  return ranked;
}
