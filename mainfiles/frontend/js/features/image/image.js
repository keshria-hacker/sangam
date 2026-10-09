/**
 * Image generation UI — prompt dialog, style presets, attach to composer.
 *
 * Shown only when the backend `image_gen` feature flag is on. Generated
 * images are saved server-side as media attachments; their ids ride along
 * as `media_ids` on the next chat message so they persist in history.
 */

import { apiFetch, apiPost } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
import { getAttachedFiles, setAttachedFiles } from '../../core/state.js';
import { renderFileChips } from '../chat/chat.js';
console.log('[Module] image.js loaded');

let imageGenEnabled = false;
let cachedStyles = [];

export function isImageGenEnabled() {
  return imageGenEnabled;
}

export async function initImage() {
  try {
    const data = await (await apiFetch('/features')).json();
    imageGenEnabled = !!(data && data.features && data.features.image_gen);
  } catch {
    imageGenEnabled = false;
  }
  if (!imageGenEnabled) return false;
  window.__sangamImageGen = true;
  const btn = document.getElementById('imageBtn');
  if (btn) {
    btn.classList.remove('hidden');
    btn.addEventListener('click', openImageDialog);
  }
  return true;
}

async function loadStyles() {
  if (cachedStyles.length) return cachedStyles;
  try {
    const status = await (await apiFetch('/image/status')).json();
    cachedStyles = status && Array.isArray(status.styles) ? status.styles : [];
  } catch {
    cachedStyles = [];
  }
  return cachedStyles;
}

function openImageDialog() {
  if (document.getElementById('imageGenOverlay')) return;
  const overlay = document.createElement('div');
  overlay.id = 'imageGenOverlay';
  overlay.className = 'image-gen-overlay';
  overlay.innerHTML = `
    <div class="image-gen-dialog" role="dialog" aria-modal="true" aria-labelledby="imageGenTitle">
      <h3 id="imageGenTitle">Generate image</h3>
      <textarea id="imageGenPrompt" rows="3" placeholder="Describe the image…" aria-label="Image prompt"></textarea>
      <div class="image-gen-row">
        <select id="imageGenStyle" class="provider-key-input" aria-label="Style"><option value="none">Loading styles…</option></select>
        <select id="imageGenSize" class="provider-key-input" aria-label="Size">
          <option value="1024x1024">Square 1024</option>
          <option value="1792x1024">Wide 1792×1024</option>
          <option value="1024x1792">Tall 1024×1792</option>
        </select>
      </div>
      <div class="image-gen-actions">
        <button class="btn-secondary" id="imageGenCancel" type="button">Cancel</button>
        <button class="btn-primary" id="imageGenGo" type="button">Generate</button>
      </div>
      <div class="image-gen-status hidden" id="imageGenStatus">Generating… this can take a minute.</div>
    </div>`;
  document.body.appendChild(overlay);

  const close = () => overlay.remove();
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  overlay.querySelector('#imageGenCancel').addEventListener('click', close);
  const promptEl = overlay.querySelector('#imageGenPrompt');
  const styleEl = overlay.querySelector('#imageGenStyle');
  const sizeEl = overlay.querySelector('#imageGenSize');
  const goBtn = overlay.querySelector('#imageGenGo');
  const statusEl = overlay.querySelector('#imageGenStatus');

  loadStyles().then((styles) => {
    styleEl.innerHTML = styles.length
      ? styles.map((s) => `<option value="${escapeHtml(s.id)}">${escapeHtml(s.name)}</option>`).join('')
      : '<option value="none">No style</option>';
  });
  setTimeout(() => promptEl.focus(), 0);

  goBtn.addEventListener('click', async () => {
    const prompt = promptEl.value.trim();
    if (!prompt) {
      showToast({ type: 'info', title: 'Describe the image first' });
      return;
    }
    goBtn.disabled = true;
    statusEl.classList.remove('hidden');
    try {
      const res = await (await apiPost('/image/generate', {
        prompt,
        style: styleEl.value || 'none',
        size: sizeEl.value || '1024x1024',
        n: 1,
      })).json();
      const images = (res && res.images) || [];
      if (!images.length) throw new Error('No images returned');
      const files = getAttachedFiles();
      images.forEach((img, i) => {
        files.push({
          localId: `img-${img.id}-${Date.now()}-${i}`,
          name: img.filename || 'generated.png',
          size: img.size_bytes || 0,
          ext: 'png',
          mediaId: img.id,
          imageUrl: img.url,
        });
      });
      setAttachedFiles([...files]);
      renderFileChips();
      showToast({ type: 'success', title: 'Image ready', message: 'Attached to your next message.' });
      close();
      document.getElementById('messageInput')?.focus();
    } catch (err) {
      showToast({ type: 'error', title: 'Generation failed', message: err?.message || String(err) });
    } finally {
      goBtn.disabled = false;
      statusEl.classList.add('hidden');
    }
  });
}
