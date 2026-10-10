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
  // Navigation via studio rail (core/nav.js) — no per-button wiring needed.
  const studioBtn = document.getElementById('imagesBtn');
  if (studioBtn && !studioBtn.dataset.wired) {
    studioBtn.dataset.wired = '1';
    studioBtn.addEventListener('click', openImageDialog);
  }
  try {
    const data = await (await apiFetch('/features')).json();
    imageGenEnabled = !!(data && data.features && data.features.image_gen);
  } catch {
    imageGenEnabled = false;
  }
  if (!imageGenEnabled) return false;
  window.__sangamImageGen = true;
  btn?.classList.remove('hidden');
  studioBtn?.classList.remove('hidden');
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
  // Composer image button now opens the Image Studio tab (no popup).
  import('../tabs/tabs.js').then(({ openToolTab }) => openToolTab('images'));
  return;
  const existing = document.getElementById('imageGenOverlay');
  if (existing) {
    existing.classList.remove('hidden');
    setTimeout(() => existing.querySelector('#imageGenPrompt')?.focus(), 0);
    return;
  }
  const overlay = document.createElement('div');
  overlay.id = 'imageGenOverlay';
  overlay.className = 'modal-overlay hidden';
  overlay.innerHTML = `
    <div class="modal image-gen-modal" role="dialog" aria-modal="true" aria-labelledby="imageGenTitle">
      <div class="modal-header">
        <h2 id="imageGenTitle"><i class="fa-solid fa-image"></i> Generate image</h2>
        <button class="icon-btn ghost" id="imageGenCancel" aria-label="Close image generator"><i class="fa-solid fa-xmark"></i></button>
      </div>
      <div class="image-gen-body">
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
          <button class="btn-primary" id="imageGenGo" type="button">Generate</button>
        </div>
        <div class="image-gen-status hidden" id="imageGenStatus">Generating… this can take a minute.</div>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  const close = () => overlay.classList.add('hidden');
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

/* ============ Image Studio tab ============ */

function getGallery() {
  try { return JSON.parse(localStorage.getItem('sangam-image-gallery') || '[]'); }
  catch { return []; }
}

function addToGallery(item) {
  const g = getGallery();
  g.unshift({ ...item, ts: Date.now() });
  try { localStorage.setItem('sangam-image-gallery', JSON.stringify(g.slice(0, 60))); } catch {}
}

function renderGallery(bodyEl) {
  const grid = bodyEl.querySelector('#imageGallery');
  const g = getGallery();
  if (!g.length) {
    grid.innerHTML = '<div class="no-results">No images yet — generate one above.</div>';
    return;
  }
  grid.innerHTML = g.map((img, i) => `
    <div class="gallery-item" data-idx="${i}">
      <img src="${escapeHtml(img.url)}" alt="${escapeHtml(img.prompt || 'Generated image')}" loading="lazy">
      <div class="gallery-item-actions">
        <button class="icon-btn" data-act="attach" title="Attach to chat"><i class="fa-solid fa-paperclip"></i></button>
        <button class="icon-btn" data-act="download" title="Download"><i class="fa-solid fa-download"></i></button>
      </div>
    </div>`).join('');
  grid.querySelectorAll('.gallery-item').forEach((el) => {
    const img = g[+el.dataset.idx];
    el.querySelector('[data-act="attach"]')?.addEventListener('click', () => {
      const files = getAttachedFiles();
      files.push({ localId: `img-${img.id}-${Date.now()}`, name: img.filename || 'generated.png', size: 0, ext: 'png', mediaId: img.id, imageUrl: img.url });
      setAttachedFiles([...files]);
      renderFileChips();
      showToast({ type: 'success', title: 'Attached to your next message' });
    });
    el.querySelector('[data-act="download"]')?.addEventListener('click', () => {
      const a = document.createElement('a');
      a.href = img.url; a.download = img.filename || 'generated.png'; a.click();
    });
  });
}

/**
 * Render the Image Studio into a tab body.
 */
export async function renderImageTab(bodyEl) {
  bodyEl.innerHTML = `
    <div class="image-studio">
      <div class="image-studio-form">
        <textarea id="studioPrompt" rows="3" placeholder="Describe the image…" aria-label="Image prompt"></textarea>
        <div class="image-gen-row">
          <select id="studioStyle" class="provider-key-input" aria-label="Style"><option value="none">Loading styles…</option></select>
          <select id="studioSize" class="provider-key-input" aria-label="Size">
            <option value="1024x1024">Square 1024</option>
            <option value="1792x1024">Wide 1792×1024</option>
            <option value="1024x1792">Tall 1024×1792</option>
          </select>
          <button class="btn-primary" id="studioGenerate" type="button">Generate</button>
        </div>
        <div class="image-gen-status hidden" id="studioStatus">Generating… this can take a minute.</div>
      </div>
      <h3 class="gallery-title">Gallery</h3>
      <div class="image-gallery" id="imageGallery"></div>
    </div>`;

  const promptEl = bodyEl.querySelector('#studioPrompt');
  const styleEl = bodyEl.querySelector('#studioStyle');
  const sizeEl = bodyEl.querySelector('#studioSize');
  const goBtn = bodyEl.querySelector('#studioGenerate');
  const statusEl = bodyEl.querySelector('#studioStatus');

  loadStyles().then((styles) => {
    styleEl.innerHTML = styles.length
      ? styles.map((s) => `<option value="${escapeHtml(s.id)}">${escapeHtml(s.name)}</option>`).join('')
      : '<option value="none">No style</option>';
  });
  renderGallery(bodyEl);

  goBtn.addEventListener('click', async () => {
    const prompt = promptEl.value.trim();
    if (!prompt) { showToast({ type: 'info', title: 'Describe the image first' }); return; }
    goBtn.disabled = true;
    statusEl.classList.remove('hidden');
    try {
      const res = await (await apiPost('/image/generate', {
        prompt, style: styleEl.value || 'none', size: sizeEl.value || '1024x1024', n: 1,
      })).json();
      const images = (res && res.images) || [];
      if (!images.length) throw new Error('No images returned');
      images.forEach((img) => addToGallery({ id: img.id, url: img.url, filename: img.filename, prompt }));
      renderGallery(bodyEl);
      showToast({ type: 'success', title: 'Image ready' });
    } catch (err) {
      showToast({ type: 'error', title: 'Generation failed', message: err?.message || String(err) });
    } finally {
      goBtn.disabled = false;
      statusEl.classList.add('hidden');
    }
  });
  setTimeout(() => promptEl.focus(), 0);
}

// Back-compat: composer image button now opens the studio tab