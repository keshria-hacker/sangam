/**
 * Workspace presets — one-click configurations (Sangam-native, Phase 2).
 *
 * Minimal: chat only. Standard: balanced. Studio: everything on.
 * Focus: minimal distractions. Developer: code-first. Student: learning-first.
 */
import { setSetting } from '../../shared/settings_store.js';
import { showToast } from '../../shared/toast.js';

console.log('[Module] presets.js loaded');

export const PRESETS = {
  minimal: {
    label: 'Minimal', icon: 'fa-minus', desc: 'Just chat. Nothing else.',
    settings: { density: 'compact', showThinking: false, voiceAutoSpeak: false },
    features: {},
  },
  standard: {
    label: 'Standard', icon: 'fa-circle', desc: 'Balanced defaults.',
    settings: { density: 'comfortable', showThinking: true },
    features: {},
  },
  studio: {
    label: 'Studio', icon: 'fa-table-columns', desc: 'Everything on.',
    settings: { density: 'comfortable', showThinking: true, notifyOnDone: true },
    features: { voice: true, image_gen: true, multi_agent: true, learning: true, analytics: true },
  },
  focus: {
    label: 'Focus', icon: 'fa-crosshairs', desc: 'Minimal distractions, writing-first.',
    settings: { density: 'comfortable', showThinking: false, notifyOnDone: false, outputStyle: 'concise' },
    features: {},
  },
  developer: {
    label: 'Developer', icon: 'fa-code', desc: 'Code-first with agent tools.',
    settings: { defaultMode: 'code', showThinking: true, agentMaxSteps: 12 },
    features: { multi_agent: true },
  },
  student: {
    label: 'Student', icon: 'fa-graduation-cap', desc: 'Learning-first.',
    settings: { defaultMode: 'chat', outputStyle: 'teacher', showThinking: true },
    features: { learning: true },
  },
};

export async function applyPreset(presetId) {
  const preset = PRESETS[presetId];
  if (!preset) return false;
  // Apply settings
  for (const [k, v] of Object.entries(preset.settings || {})) {
    setSetting(k, v);
  }
  // Apply feature flags
  if (Object.keys(preset.features || {}).length) {
    try {
      const { apiFetch } = await import('../shared/http.js');
      for (const [name, on] of Object.entries(preset.features)) {
        await apiFetch(`/features/${name}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: on }),
        });
      }
      const { refreshFeatureButtons } = await import('./settings/settings.js');
      const data = await (await apiFetch('/features')).json();
      refreshFeatureButtons(data.features || {});
    } catch (e) {
      console.warn('[presets] feature flags failed', e);
    }
  }
  try { localStorage.setItem('sangam:preset', presetId); } catch {}
  showToast({ type: 'success', title: `Preset applied: ${preset.label}` });
  document.dispatchEvent(new CustomEvent('sangam:preset-applied', { detail: { preset: presetId } }));
  return true;
}

export function getActivePreset() {
  try { return localStorage.getItem('sangam:preset') || 'standard'; } catch { return 'standard'; }
}
