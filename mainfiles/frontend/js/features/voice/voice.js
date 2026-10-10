/**
 * Voice feature — compatibility layer over ./controller.js.
 *
 * All voice I/O goes through the Voice Controller state machine.
 * This module keeps the existing exports (initVoice, speakText,
 * stopSpeaking, maybeAutoSpeak, refreshVoiceSettings) so callers
 * don't change.
 */
import { apiFetch } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
import { getSetting, setSetting } from '../../shared/settings_store.js';
import {
  speak, stopSpeaking as controllerStop, stopAllVoice,
  toggleRecording, onVoiceState, getSpeakingNode,
} from './controller.js';

console.log('[Module] voice.js loaded');

let voiceEnabled = false;
let voiceStatus = null;

export function isVoiceEnabled() { return voiceEnabled; }
export function getVoiceStatus() { return voiceStatus; }

/** Called once at app startup. Returns true when voice UI should show. */
export async function initVoice() {
  const micBtn = document.getElementById('micBtn');
  if (micBtn && !micBtn.dataset.wired) {
    micBtn.dataset.wired = '1';
    micBtn.addEventListener('click', toggleRecording);
  }
  try {
    const data = await (await apiFetch('/features')).json();
    voiceEnabled = !!(data && data.features && data.features.voice);
  } catch {
    voiceEnabled = false;
  }
  if (!voiceEnabled) return false;
  window.__sangamVoice = true;
  try {
    voiceStatus = await (await apiFetch('/voice/status')).json();
  } catch {
    voiceStatus = null;
  }
  micBtn?.classList.remove('hidden');

  // Cancel button discards the recording
  const cancelBtn = document.getElementById('dictCancelBtn');
  if (cancelBtn && !cancelBtn.dataset.wired) {
    cancelBtn.dataset.wired = '1';
    cancelBtn.addEventListener('click', async () => {
      const { stopRecording } = await import('./controller.js');
      stopRecording(true);
    });
  }
  // Show/hide cancel button with dictation state
  document.addEventListener('sangam:dict-state', (e) => {
    cancelBtn?.classList.toggle('hidden', e.detail.state !== 'recording');
  });

  wireGlobalStops();
  return true;
}

/** Stop voice on Escape, before sending, and on chat switch. */
function wireGlobalStops() {
  if (window.__sangamVoiceStops) return;
  window.__sangamVoiceStops = true;
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') stopAllVoice();
  });
  document.addEventListener('sangam:before-send', () => stopAllVoice());
  document.addEventListener('sangam:chat-switched', () => stopAllVoice());
}

// --- Re-exports over the controller ---

/** Speak text aloud (toggle if the same node is speaking). */
export async function speakText(text, node = null) {
  return speak(text, node);
}

export function stopSpeaking() {
  controllerStop();
}

/** Auto-speak hook for completed assistant messages (setting-gated). */
export function maybeAutoSpeak(text) {
  if (!voiceEnabled) return;
  try {
    if (getSetting('voiceAutoSpeak')) speak(text);
  } catch { /* noop */ }
}

export { onVoiceState, stopAllVoice, toggleRecording, getSpeakingNode };

// --- Settings UI (container-scoped; the legacy modal is gone) ---

/**
 * Phase 8 B2: container-scoped voice settings for the Settings page.
 * Builds the same UI as refreshVoiceSettings but inside `host`.
 */
export async function renderVoiceSettings(host) {
  if (!host || host.dataset.voiceWired) return;
  host.dataset.voiceWired = '1';
  host.innerHTML = '<p class="settings-hint">Loading voice settings…</p>';
  const settings = null; // legacy
  const status = voiceStatus || {};
  const ttsEngine = status.tts_engine;
  const sttEngine = status.stt_engine;

  let voicesHtml = '<span class="memory-stat">default voice</span>';
  try {
    const voices = await (await apiFetch('/voice/voices')).json();
    if (Array.isArray(voices) && voices.length) {
      voicesHtml = `<select data-voice-select class="provider-key-input" aria-label="TTS voice">` +
        `<option value="">Default voice</option>` +
        voices.map((v) => `<option value="${escapeHtml(v.id)}"${voiceId === v.id ? ' selected' : ''}>${escapeHtml(v.name)} (${escapeHtml(v.engine)})</option>`).join('') +
        `</select>`;
    }
  } catch { /* keep default */ }

  host.innerHTML = `
    <div class="memory-stats">
      <span class="memory-stat"><strong>TTS</strong>${escapeHtml(ttsEngine || 'unavailable')}</span>
      <span class="memory-stat"><strong>STT</strong>${escapeHtml(sttEngine || 'unavailable')}</span>
    </div>
    <div class="memory-controls">${voicesHtml}</div>
    <div class="voice-settings-row">
      <span class="switch-label">Read responses aloud automatically</span>
      <label class="switch">
        <input type="checkbox" data-voice-autospeak${voiceAutoSpeak ? ' checked' : ''}>
        <span class="switch-track"><span class="switch-thumb"></span></span>
      </label>
    </div>
    ${!ttsEngine && !sttEngine ? '<p class="settings-hint">No voice engine installed. Install <code>kokoro</code> + <code>faster-whisper</code>, or point VOICE_OPENAI_BASE_URL at an OpenAI-compatible voice server.</p>' : ''}`;

  host.querySelector('[data-voice-autospeak]')?.addEventListener('change', (e) => {
    setSetting('voiceAutoSpeak', e.target.checked);
    if (!e.target.checked) controllerStop();
  });
  host.querySelector('[data-voice-select]')?.addEventListener('change', (e) => {
    setSetting('voiceId', e.target.value || '');
  });
}
