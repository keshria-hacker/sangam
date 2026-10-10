/**
 * Voice Controller — single state machine for all voice I/O (Sangam-native).
 *
 * States:
 *   speech: idle -> fetching -> speaking -> paused -> idle
 *   dictation: idle -> recording -> transcribing -> idle
 *
 * Every entry point goes through here. Stop works in every state:
 * - fetching: AbortController cancels the TTS HTTP request
 * - speaking: audio element paused + released, speechSynthesis cancelled
 * - late responses ignored via request token
 */
import { apiFetch } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { getSetting } from '../../shared/settings_store.js';

console.log('[Module] voice/controller.js loaded');

// --- Speech state ---
let speechState = 'idle'; // idle | fetching | speaking | paused
let speechToken = 0;
let fetchController = null;
let currentAudio = null;
let speakingNode = null; // message node currently being spoken (for UI toggle)
const listeners = new Set();

function setSpeechState(s, node = null) {
  speechState = s;
  if (s === 'idle') speakingNode = null;
  else if (node) speakingNode = node;
  for (const fn of listeners) { try { fn(s); } catch {} }
  document.dispatchEvent(new CustomEvent('sangam:voice-state', { detail: { state: s } }));
}

export function onVoiceState(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
export function getSpeechState() { return speechState; }
export function isSpeaking() { return speechState === 'speaking' || speechState === 'fetching'; }
export function getSpeakingNode() { return speakingNode; }

/** Speak text. If already speaking this node, toggles to stop. */
export async function speak(text, node = null) {
  if (!text || !text.trim()) return;
  // Toggle: clicking speak on the active node stops it
  if (node && node === speakingNode && isSpeaking()) {
    stopSpeaking();
    return;
  }
  stopSpeaking();
  const token = ++speechToken;
  const voiceId = getSetting('voiceId') || null;
  setSpeechState('fetching', node);

  fetchController = new AbortController();
  try {
    const res = await apiFetch('/voice/tts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.slice(0, 4000), voice: voiceId }),
      signal: fetchController.signal,
    });
    if (token !== speechToken) return; // superseded
    if (!res.ok) throw new Error(`TTS ${res.status}`);
    const buf = await res.arrayBuffer();
    if (token !== speechToken) return;
    if (!buf.byteLength) throw new Error('empty audio');
    const blob = new Blob([buf], { type: res.headers.get('content-type') || 'audio/wav' });
    currentAudio = new Audio(URL.createObjectURL(blob));
    setSpeechState('speaking', node);
    currentAudio.onended = () => { if (token === speechToken) setSpeechState('idle'); currentAudio = null; };
    currentAudio.onerror = () => { if (token === speechToken) setSpeechState('idle'); currentAudio = null; };
    await currentAudio.play();
  } catch (err) {
    if (err?.name === 'AbortError' || token !== speechToken) return; // stopped, not a failure
    // Backend TTS unavailable — browser fallback
    browserSpeak(text, token, node);
  } finally {
    fetchController = null;
  }
}

async function browserSpeak(text, token, node) {
  try {
    if (!('speechSynthesis' in window)) {
      showToast({ type: 'error', title: 'No speech engine available' });
      setSpeechState('idle');
      return;
    }
    setSpeechState('speaking', node);
    const utter = new SpeechSynthesisUtterance(text.slice(0, 4000));
    // Phase 8 C: voiceSpeed setting controls speech rate.
    try {
      const { getSetting } = await import('../../shared/settings_store.js');
      const speed = getSetting('voiceSpeed');
      if (typeof speed === 'number' && speed > 0) utter.rate = speed;
    } catch { /* use default rate */ }
    utter.onend = () => { if (token === speechToken) setSpeechState('idle'); };
    utter.onerror = () => { if (token === speechToken) setSpeechState('idle'); };
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utter);
  } catch {
    setSpeechState('idle');
  }
}

/** Stop speech in ANY state. Safe to call when idle. */
export function stopSpeaking() {
  speechToken++; // invalidate in-flight requests
  try {
    fetchController?.abort();
    fetchController = null;
    if (currentAudio) {
      currentAudio.pause();
      currentAudio.src = '';
      currentAudio = null;
    }
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  } catch { /* noop */ }
  if (speechState !== 'idle') setSpeechState('idle');
}

// --- Dictation state ---
let dictState = 'idle'; // idle | recording | transcribing
let recorder = null;
let recordChunks = [];
let recordTimer = null;
let recordStart = 0;
let lastBlob = null; // kept on STT failure for retry

export function getDictState() { return dictState; }

function setDictState(s) {
  dictState = s;
  document.dispatchEvent(new CustomEvent('sangam:dict-state', { detail: { state: s } }));
  const micBtn = document.getElementById('micBtn');
  micBtn?.classList.toggle('recording', s === 'recording');
  const icon = micBtn?.querySelector('i');
  if (icon) {
    icon.classList.toggle('fa-microphone', s !== 'recording');
    icon.classList.toggle('fa-circle', s === 'recording');
  }
  const timerEl = document.getElementById('dictTimer');
  if (timerEl) timerEl.classList.toggle('hidden', s !== 'recording');
}

export async function toggleRecording() {
  if (dictState === 'recording') { stopRecording(false); return; }
  if (dictState !== 'idle') return;
  stopSpeaking(); // mic-start stops speech
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
      clearInterval(recordTimer);
      sendForTranscription();
    };
    recorder.start();
    recordStart = Date.now();
    setDictState('recording');
    recordTimer = setInterval(() => {
      const el = document.getElementById('dictTimer');
      if (el) el.textContent = `${Math.floor((Date.now() - recordStart) / 1000)}s`;
    }, 500);
  } catch (err) {
    showToast({ type: 'error', title: 'Microphone unavailable', message: err?.message || String(err) });
  }
}

/** Stop recording. discard=true throws the audio away. */
export function stopRecording(discard = false) {
  if (dictState !== 'recording' || !recorder) return;
  clearInterval(recordTimer);
  if (discard) {
    const r = recorder;
    recorder = null;
    recordChunks = [];
    r.onstop = () => {};
    try { r.stop(); } catch {}
    setDictState('idle');
  } else {
    recorder.stop();
  }
}

async function sendForTranscription() {
  const blob = new Blob(recordChunks, { type: recorder?.mimeType || 'audio/webm' });
  recordChunks = [];
  recorder = null;
  if (!blob.size) { setDictState('idle'); return; }
  lastBlob = blob; // keep for retry
  setDictState('transcribing');
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
    lastBlob = null; // success — drop the blob
    if (input && text) {
      const needsSpace = input.value && !input.value.endsWith(' ') && !input.value.endsWith('\n');
      input.value = input.value + (needsSpace ? ' ' : '') + text;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus();
    }
  } catch (err) {
    showToast({
      type: 'error', title: 'Transcription failed',
      message: `${err?.message || err} — recording kept, tap mic to retry.`,
    });
  } finally {
    if (input) input.placeholder = prevPlaceholder;
    setDictState('idle');
  }
}

/** Retry the last failed transcription. */
export async function retryTranscription() {
  if (!lastBlob || dictState !== 'idle') return;
  recordChunks = [];
  // Reuse sendForTranscription via a synthetic path
  const blob = lastBlob;
  setDictState('transcribing');
  const input = document.getElementById('messageInput');
  if (input) input.placeholder = 'Retrying transcription…';
  try {
    const form = new FormData();
    form.append('file', blob, 'dictation.webm');
    const res = await fetch('/api/voice/stt', { method: 'POST', body: form, credentials: 'include' });
    if (!res.ok) throw new Error(`Transcription failed (${res.status})`);
    const { text } = await res.json();
    lastBlob = null;
    if (input && text) {
      input.value = (input.value ? input.value + ' ' : '') + text;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus();
    }
  } catch (err) {
    showToast({ type: 'error', title: 'Retry failed', message: err?.message || String(err) });
  } finally {
    if (input) input.placeholder = '';
    setDictState('idle');
  }
}

/** Stop everything voice-related. Call on: Escape, new send, chat switch. */
export function stopAllVoice() {
  stopSpeaking();
  if (dictState === 'recording') stopRecording(true);
}
