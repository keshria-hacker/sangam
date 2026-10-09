/**
 * Voice Studio — text-to-speech and speech-to-text playground.
 *
 * Separate entry from the Create Hub templates. Uses /api/voice/* endpoints.
 */
import { apiFetch } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
console.log('[Module] voice/studio.js loaded');

export async function renderVoiceStudio(bodyEl) {
  bodyEl.innerHTML = `
    <div class="voice-studio">
      <h3><i class="fa-solid fa-microphone"></i> Voice Studio</h3>

      <section class="vs-section">
        <h4>Text to Speech</h4>
        <textarea id="vsTtsText" rows="4" placeholder="Enter text to synthesize…"></textarea>
        <div class="vs-controls">
          <select id="vsVoice" class="provider-key-input" aria-label="Voice"></select>
          <button class="btn-primary" id="vsSpeak" type="button">Speak</button>
          <button class="btn-secondary" id="vsStop" type="button">Stop</button>
        </div>
        <audio id="vsAudio" controls class="hidden"></audio>
      </section>

      <section class="vs-section">
        <h4>Speech to Text</h4>
        <div class="vs-controls">
          <button class="btn-secondary" id="vsRecord" type="button">
            <i class="fa-solid fa-circle-dot"></i> Record
          </button>
          <span id="vsRecStatus" class="vs-status"></span>
        </div>
        <textarea id="vsSttOut" rows="4" readonly placeholder="Transcription appears here…"></textarea>
      </section>
    </div>`;

  // Load voices
  const voiceSel = bodyEl.querySelector('#vsVoice');
  try {
    const data = await (await apiFetch('/voice/voices')).json();
    const voices = data.voices || [];
    voiceSel.innerHTML = voices.map((v) =>
      `<option value="${escapeHtml(v.id)}">${escapeHtml(v.name || v.id)}</option>`
    ).join('') || '<option value="">Default</option>';
  } catch {
    voiceSel.innerHTML = '<option value="">Default</option>';
  }

  // TTS
  const audioEl = bodyEl.querySelector('#vsAudio');
  bodyEl.querySelector('#vsSpeak').addEventListener('click', async () => {
    const text = bodyEl.querySelector('#vsTtsText').value.trim();
    if (!text) {
      showToast({ type: 'info', title: 'Enter text first' });
      return;
    }
    try {
      const res = await apiFetch('/voice/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, voice: voiceSel.value || undefined }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      audioEl.src = URL.createObjectURL(blob);
      audioEl.classList.remove('hidden');
      audioEl.play();
    } catch (err) {
      showToast({ type: 'error', title: 'TTS failed', message: String(err?.message || err) });
    }
  });
  bodyEl.querySelector('#vsStop').addEventListener('click', () => {
    audioEl.pause();
    audioEl.currentTime = 0;
  });

  // STT (MediaRecorder)
  let recorder = null;
  let chunks = [];
  const recBtn = bodyEl.querySelector('#vsRecord');
  const recStatus = bodyEl.querySelector('#vsRecStatus');
  recBtn.addEventListener('click', async () => {
    if (recorder) {
      recorder.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      recorder = new MediaRecorder(stream);
      chunks = [];
      recorder.ondataavailable = (e) => chunks.push(e.data);
      recorder.onstop = async () => {
        recBtn.innerHTML = '<i class="fa-solid fa-circle-dot"></i> Record';
        recStatus.textContent = 'Transcribing…';
        const blob = new Blob(chunks, { type: 'audio/webm' });
        const form = new FormData();
        form.append('audio', blob, 'recording.webm');
        try {
          const res = await apiFetch('/voice/stt', { method: 'POST', body: form });
          const data = await res.json();
          bodyEl.querySelector('#vsSttOut').value = data.text || data.transcript || '';
          recStatus.textContent = '';
        } catch (err) {
          recStatus.textContent = 'Transcription failed';
        }
        recorder = null;
        stream.getTracks().forEach((t) => t.stop());
      };
      recorder.start();
      recBtn.innerHTML = '<i class="fa-solid fa-stop"></i> Stop';
      recStatus.textContent = 'Recording…';
    } catch {
      showToast({ type: 'error', title: 'Microphone access denied' });
    }
  });
}
