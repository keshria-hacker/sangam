/**
 * Voice feature — mic dictation (STT) and spoken responses (TTS).
 *
 * Shown only when the backend `voice` feature flag is on. TTS prefers the
 * backend engine (/api/voice/tts) and falls back to the browser's
 * speechSynthesis when no backend engine is available.
 */

import { apiFetch } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
import { getSettings, setSettings } from '../../core/state.js';
console.log('[Module] voice.js loaded');

let voiceEnabled = false;
let voiceStatus = null;   // {tts_engine, stt_engine, engines:[...]}
let recorder = null;
let recordChunks = [];
let currentAudio = null;

export function isVoiceEnabled() {
  return voiceEnabled;
}

export function getVoiceStatus() {
  return voiceStatus;
}

/** Called once at app startup. Returns true when voice UI should show. */
export async function initVoice() {
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
  const micBtn = document.getElementById('micBtn');
  if (micBtn) {
    micBtn.classList.remove('hidden');
    micBtn.addEventListener('click', toggleRecording);
  }
  return true;
}

// --- Dictation (mic -> STT -> composer) --------------------------------------

async function toggleRecording() {
  const micBtn = document.getElementById('micBtn');
  if (recorder && recorder.state === 'recording') {
    recorder.stop();
    return;
  }
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    showToast({ type: 'error', title: 'Recording not supported in this browser' });
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordChunks = [];
    const mime = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : '';
    recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    recorder.ondataavailable = (e) => { if (e.data.size) recordChunks.push(e.data); };
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      micBtn?.classList.remove('recording');
      micBtn?.querySelector('i')?.classList.replace('fa-circle', 'fa-microphone');
      sendForTranscription();
    };
    recorder.start();
    micBtn?.classList.add('recording');
    micBtn?.querySelector('i')?.classList.replace('fa-microphone', 'fa-circle');
    showToast({ type: 'info', title: 'Recording… tap the mic to stop' });
  } catch (err) {
    showToast({ type: 'error', title: 'Microphone unavailable', message: err?.message || String(err) });
  }
}

async function sendForTranscription() {
  const blob = new Blob(recordChunks, { type: recorder?.mimeType || 'audio/webm' });
  recordChunks = [];
  if (!blob.size) return;
  const input = document.getElementById('messageInput');
  const prevPlaceholder = input ? input.placeholder : '';
  if (input) input.placeholder = 'Transcribing…';
  try {
    const form = new FormData();
    form.append('file', blob, 'dictation.webm');
    const res = await fetch('/api/voice/stt', { method: 'POST', body: form, credentials: 'include' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Transcription failed (${res.status})`);
    }
    const { text } = await res.json();
    if (input && text) {
      const needsSpace = input.value && !input.value.endsWith(' ') && !input.value.endsWith('\n');
      input.value = input.value + (needsSpace ? ' ' : '') + text;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus();
    }
  } catch (err) {
    showToast({ type: 'error', title: 'Transcription failed', message: err?.message || String(err) });
  } finally {
    if (input) input.placeholder = prevPlaceholder;
  }
}

// --- Speech (TTS) ------------------------------------------------------------

/** Speak text aloud: backend TTS first, browser fallback when unavailable. */
export async function speakText(text) {
  if (!text || !text.trim()) return;
  stopSpeaking();
  const settings = getSettings();
  const voiceId = settings.voiceId || null;
  try {
    const res = await fetch('/api/voice/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ text: text.slice(0, 4000), voice: voiceId }),
    });
    if (!res.ok) throw new Error(`TTS ${res.status}`);
    const buf = await res.arrayBuffer();
    if (!buf.byteLength) throw new Error('empty audio');
    const blob = new Blob([buf], { type: res.headers.get('content-type') || 'audio/wav' });
    currentAudio = new Audio(URL.createObjectURL(blob));
    currentAudio.onended = () => { currentAudio = null; };
    await currentAudio.play();
  } catch (err) {
    // Backend TTS unavailable — fall back to the browser's voices.
    browserSpeak(text);
  }
}

function browserSpeak(text) {
  try {
    if (!('speechSynthesis' in window)) {
      showToast({ type: 'error', title: 'No speech engine available' });
      return;
    }
    const utter = new SpeechSynthesisUtterance(text.slice(0, 4000));
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utter);
  } catch (err) {
    showToast({ type: 'error', title: 'Speech failed', message: err?.message || String(err) });
  }
}

export function stopSpeaking() {
  try {
    if (currentAudio) { currentAudio.pause(); currentAudio = null; }
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  } catch { /* noop */ }
}

/** Auto-speak hook for completed assistant messages (setting-gated). */
export function maybeAutoSpeak(text) {
  if (!voiceEnabled) return;
  try {
    if (getSettings().voiceAutoSpeak) speakText(text);
  } catch { /* noop */ }
}

// --- Settings UI -------------------------------------------------------------

export async function refreshVoiceSettings() {
  const section = document.getElementById('voiceSettingsSection');
  if (!section) return;
  const settings = getSettings();
  const status = voiceStatus || {};
  const ttsEngine = status.tts_engine;
  const sttEngine = status.stt_engine;

  let voicesHtml = '<span class="memory-stat">default voice</span>';
  try {
    const voices = await (await apiFetch('/voice/voices')).json();
    if (Array.isArray(voices) && voices.length) {
      voicesHtml = `<select id="voiceSelect" class="provider-key-input" aria-label="TTS voice">` +
        `<option value="">Default voice</option>` +
        voices.map((v) => `<option value="${escapeHtml(v.id)}"${settings.voiceId === v.id ? ' selected' : ''}>${escapeHtml(v.name)} (${escapeHtml(v.engine)})</option>`).join('') +
        `</select>`;
    }
  } catch { /* keep default */ }

  section.innerHTML = `
    <div class="memory-stats">
      <span class="memory-stat"><strong>TTS</strong>${escapeHtml(ttsEngine || 'unavailable')}</span>
      <span class="memory-stat"><strong>STT</strong>${escapeHtml(sttEngine || 'unavailable')}</span>
    </div>
    <div class="memory-controls">${voicesHtml}</div>
    <div class="voice-settings-row">
      <span class="switch-label">Read responses aloud automatically</span>
      <label class="switch">
        <input type="checkbox" id="voiceAutoSpeakToggle"${settings.voiceAutoSpeak ? ' checked' : ''}>
        <span class="switch-track"><span class="switch-thumb"></span></span>
      </label>
    </div>
    ${!ttsEngine && !sttEngine ? '<p class="settings-hint">No voice engine installed. Install <code>kokoro</code> + <code>faster-whisper</code>, or point VOICE_OPENAI_BASE_URL at a VoiceStudio server.</p>' : ''}`;

  section.querySelector('#voiceAutoSpeakToggle')?.addEventListener('change', (e) => {
    setSettings({ ...getSettings(), voiceAutoSpeak: e.target.checked });
    if (!e.target.checked) stopSpeaking();
  });
  section.querySelector('#voiceSelect')?.addEventListener('change', (e) => {
    setSettings({ ...getSettings(), voiceId: e.target.value || null });
  });
}
