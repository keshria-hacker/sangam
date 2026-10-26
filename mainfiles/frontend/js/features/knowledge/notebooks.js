/**
 * Notebooks + Memory V2 UI for the Knowledge tab (Batch 4).
 *
 * Wired from knowledge.js the same way the Study section wires learn.js:
 * a dynamic import that calls initNotebooks/initMemoryTools with the
 * tab body element. All API calls go through apiFetch (raw Response —
 * .json() is always awaited before reading fields) and all toasts use
 * the object form showToast({ message }).
 */
import { apiFetch } from '../../shared/http.js';
import { escapeHtml } from '../../shared/utils.js';
import { showToast } from '../../shared/toast.js';

console.log('[Module] notebooks.js loaded');

let currentNotebookId = null;

function el(bodyEl, id) {
  return bodyEl.querySelector(`#${id}`);
}

function errMessage(err) {
  return err?.message || String(err);
}

// ---------------------------------------------------------------- notebooks

export function initNotebooks(bodyEl) {
  const createBtn = el(bodyEl, 'nbCreateBtn');
  if (!createBtn || createBtn.dataset.wired) return;
  createBtn.dataset.wired = '1';
  createBtn.addEventListener('click', () => createNotebook(bodyEl));
  loadNotebooks(bodyEl);
}

async function loadNotebooks(bodyEl) {
  const box = el(bodyEl, 'nbList');
  if (!box) return;
  box.innerHTML = '<p class="settings-hint">Loading notebooks…</p>';
  try {
    const data = await (await apiFetch('/notebooks')).json();
    const items = data.notebooks || [];
    if (!items.length) {
      box.innerHTML = '<p class="settings-hint">No notebooks yet. Create one above to group sources, notes, and transforms.</p>';
      return;
    }
    box.innerHTML = items.map((n) => `
      <div class="nb-row">
        <strong>${escapeHtml(n.name)}</strong>
        <span class="settings-hint">${escapeHtml(n.description || '')}</span>
        <button class="btn-secondary btn-sm" data-nb-open="${escapeHtml(n.id)}">Open</button>
        <button class="icon-btn" data-nb-del="${escapeHtml(n.id)}" title="Delete notebook" aria-label="Delete notebook"><i class="fa-solid fa-trash"></i></button>
      </div>`).join('');
    box.querySelectorAll('[data-nb-open]').forEach((btn) => {
      btn.addEventListener('click', () => openNotebook(bodyEl, btn.dataset.nbOpen));
    });
    box.querySelectorAll('[data-nb-del]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        if (!confirm('Delete this notebook and its sources, notes, and transforms?')) return;
        try {
          await apiFetch(`/notebooks/${encodeURIComponent(btn.dataset.nbDel)}`, { method: 'DELETE' });
          showToast({ type: 'success', message: 'Notebook deleted' });
          if (currentNotebookId === btn.dataset.nbDel) {
            currentNotebookId = null;
            const detail = el(bodyEl, 'nbDetail');
            if (detail) detail.innerHTML = '';
          }
          loadNotebooks(bodyEl);
        } catch (err) {
          showToast({ type: 'error', message: `Delete failed: ${errMessage(err)}` });
        }
      });
    });
  } catch {
    box.innerHTML = '<p class="settings-hint">Could not load notebooks.</p>';
  }
}

async function createNotebook(bodyEl) {
  const name = el(bodyEl, 'nbName').value.trim();
  const description = el(bodyEl, 'nbDesc').value.trim();
  if (!name) { showToast({ type: 'error', message: 'Give the notebook a name first.' }); return; }
  try {
    const nb = await (await apiFetch('/notebooks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description }),
    })).json();
    showToast({ type: 'success', message: `Notebook "${nb.name}" created` });
    el(bodyEl, 'nbName').value = '';
    el(bodyEl, 'nbDesc').value = '';
    await loadNotebooks(bodyEl);
    openNotebook(bodyEl, nb.id);
  } catch (err) {
    showToast({ type: 'error', message: `Create failed: ${errMessage(err)}` });
  }
}

async function openNotebook(bodyEl, nbId) {
  currentNotebookId = nbId;
  const detail = el(bodyEl, 'nbDetail');
  if (!detail) return;
  detail.innerHTML = `
    <div class="nb-detail">
      <h4>Notebook</h4>
      <section>
        <h5>Sources</h5>
        <p class="settings-hint">Context mode controls what retrieval sees: excluded sources are skipped, summary uses a short summary, full uses the whole source.</p>
        <div class="kn-mem-controls">
          <select id="nbSourceKind" class="provider-key-input" aria-label="Source kind">
            <option value="url">Web link</option>
            <option value="note">Note in this notebook</option>
            <option value="file">Uploaded file</option>
            <option value="chat">Chat</option>
          </select>
          <input type="text" id="nbSourceRef" class="provider-key-input" placeholder="URL, file id, note id, or chat id" aria-label="Source reference" style="flex:1">
          <select id="nbSourceMode" class="provider-key-input" aria-label="Context mode">
            <option value="full">Full</option>
            <option value="summary">Summary</option>
            <option value="excluded">Excluded</option>
          </select>
          <button class="btn-secondary" id="nbAddSourceBtn">Add source</button>
        </div>
        <div id="nbSources" class="kn-mem-list"></div>
      </section>
      <section>
        <h5>Retrieve</h5>
        <div class="kn-mem-controls">
          <input type="text" id="nbRetrieveQ" class="provider-key-input" placeholder="Ask about this notebook…" aria-label="Notebook retrieve query" style="flex:1">
          <button class="btn-secondary" id="nbRetrieveBtn">Retrieve</button>
        </div>
        <div id="nbRetrieveResults" class="kn-mem-list"></div>
      </section>
      <section>
        <h5>Notes</h5>
        <div class="kn-mem-controls">
          <input type="text" id="nbNoteTitle" class="provider-key-input" placeholder="Note title" aria-label="Note title">
          <input type="text" id="nbNoteContent" class="provider-key-input" placeholder="Note content — use [[Other title]] to link" aria-label="Note content" style="flex:1">
          <button class="btn-secondary" id="nbNoteBtn">Add note</button>
        </div>
        <details class="advanced-section">
          <summary>Advanced: import from a chat</summary>
          <div class="kn-mem-controls">
            <input type="text" id="nbFromChatId" class="provider-key-input" placeholder="Chat id" aria-label="Chat id for note">
            <input type="text" id="nbFromChatMsg" class="provider-key-input" placeholder="Message id (optional — latest used)" aria-label="Message id">
            <button class="btn-secondary" id="nbFromChatBtn">Save chat message as note</button>
          </div>
        </details>
        <div id="nbNotes" class="kn-mem-list"></div>
        <div id="nbNoteDetail"></div>
      </section>
      <section>
        <h5>Transforms</h5>
        <p class="settings-hint">Run a custom prompt over this notebook's sources. The output is saved as a transform and as a note.</p>
        <div class="kn-mem-controls">
          <input type="text" id="nbTransformName" class="provider-key-input" placeholder="Transform name" aria-label="Transform name">
          <input type="text" id="nbTransformPrompt" class="provider-key-input" placeholder="Prompt, e.g. Summarize the key insights" aria-label="Transform prompt" style="flex:1">
          <button class="btn-secondary" id="nbTransformBtn">Run transform</button>
        </div>
        <div id="nbTransforms" class="kn-mem-list"></div>
      </section>
    </div>`;
  detail.querySelector('#nbAddSourceBtn').addEventListener('click', () => addSource(bodyEl));
  detail.querySelector('#nbRetrieveBtn').addEventListener('click', () => retrieveNotebook(bodyEl));
  detail.querySelector('#nbRetrieveQ').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') retrieveNotebook(bodyEl);
  });
  detail.querySelector('#nbNoteBtn').addEventListener('click', () => addNote(bodyEl));
  detail.querySelector('#nbFromChatBtn').addEventListener('click', () => noteFromChat(bodyEl));
  detail.querySelector('#nbTransformBtn').addEventListener('click', () => runTransform(bodyEl));
  await Promise.all([loadSources(bodyEl), loadNotes(bodyEl), loadTransforms(bodyEl)]);
}

async function loadSources(bodyEl) {
  const box = el(bodyEl, 'nbSources');
  if (!box || !currentNotebookId) return;
  try {
    const data = await (await apiFetch(`/notebooks/${encodeURIComponent(currentNotebookId)}/sources`)).json();
    const items = data.sources || [];
    box.innerHTML = items.length ? items.map((s) => `
      <div class="nb-row">
        <span class="kn-chip">${escapeHtml(s.kind)}</span>
        <span class="kn-mem-content">${escapeHtml(s.ref)}</span>
        <select class="provider-key-input" data-nb-mode="${escapeHtml(s.id)}" aria-label="Context mode">
          ${['full', 'summary', 'excluded'].map((m) => `<option value="${m}" ${s.context_mode === m ? 'selected' : ''}>${m}</option>`).join('')}
        </select>
      </div>`).join('') : '<p class="settings-hint">No sources yet.</p>';
    box.querySelectorAll('[data-nb-mode]').forEach((sel) => {
      sel.addEventListener('change', async () => {
        try {
          await apiFetch(`/notebooks/${encodeURIComponent(currentNotebookId)}/sources/${encodeURIComponent(sel.dataset.nbMode)}/context`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ context_mode: sel.value }),
          });
          showToast({ type: 'success', message: `Context mode set to ${sel.value}` });
        } catch (err) {
          showToast({ type: 'error', message: `Mode change failed: ${errMessage(err)}` });
        }
      });
    });
  } catch {
    box.innerHTML = '<p class="settings-hint">Could not load sources.</p>';
  }
}

async function addSource(bodyEl) {
  const kind = el(bodyEl, 'nbSourceKind').value;
  const ref = el(bodyEl, 'nbSourceRef').value.trim();
  const contextMode = el(bodyEl, 'nbSourceMode').value;
  if (!ref) { showToast({ type: 'error', message: 'Enter a source reference first.' }); return; }
  try {
    await apiFetch(`/notebooks/${encodeURIComponent(currentNotebookId)}/sources`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, ref, context_mode: contextMode }),
    });
    showToast({ type: 'success', message: 'Source added' });
    el(bodyEl, 'nbSourceRef').value = '';
    loadSources(bodyEl);
  } catch (err) {
    showToast({ type: 'error', message: `Add source failed: ${errMessage(err)}` });
  }
}

async function retrieveNotebook(bodyEl) {
  const q = el(bodyEl, 'nbRetrieveQ').value.trim();
  const box = el(bodyEl, 'nbRetrieveResults');
  if (!q) { box.innerHTML = '<p class="settings-hint">Type a question first.</p>'; return; }
  box.innerHTML = '<p class="settings-hint">Retrieving…</p>';
  try {
    const data = await (await apiFetch(`/notebooks/${encodeURIComponent(currentNotebookId)}/retrieve?q=${encodeURIComponent(q)}`)).json();
    const entries = data.context || [];
    if (!entries.length) {
      box.innerHTML = '<p class="settings-hint">Nothing in this notebook matches (excluded sources are skipped).</p>';
      return;
    }
    box.innerHTML = entries.map((e) => `
      <div class="nb-row">
        <span class="kn-chip">${escapeHtml(e.kind)} · ${escapeHtml(e.mode)}</span>
        <span class="kn-mem-content">${e.text ? escapeHtml(e.text.slice(0, 400)) : escapeHtml(e.note || e.ref || '')}</span>
      </div>`).join('');
  } catch {
    box.innerHTML = '<p class="settings-hint">Retrieval failed.</p>';
  }
}

async function loadNotes(bodyEl) {
  const box = el(bodyEl, 'nbNotes');
  if (!box || !currentNotebookId) return;
  try {
    const data = await (await apiFetch(`/notebooks/${encodeURIComponent(currentNotebookId)}/notes`)).json();
    const items = data.notes || [];
    box.innerHTML = items.length ? items.map((n) => `
      <div class="nb-row">
        <strong>${escapeHtml(n.title)}</strong>
        <span class="kn-mem-content">${escapeHtml((n.content || '').slice(0, 120))}</span>
        <button class="btn-secondary btn-sm" data-nb-note-view="${escapeHtml(n.id)}">View</button>
      </div>`).join('') : '<p class="settings-hint">No notes yet.</p>';
    box.querySelectorAll('[data-nb-note-view]').forEach((btn) => {
      btn.addEventListener('click', () => viewNote(bodyEl, btn.dataset.nbNoteView));
    });
  } catch {
    box.innerHTML = '<p class="settings-hint">Could not load notes.</p>';
  }
}

async function addNote(bodyEl) {
  const title = el(bodyEl, 'nbNoteTitle').value.trim();
  const content = el(bodyEl, 'nbNoteContent').value.trim();
  if (!title) { showToast({ type: 'error', message: 'Give the note a title first.' }); return; }
  try {
    await apiFetch(`/notebooks/${encodeURIComponent(currentNotebookId)}/notes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, content }),
    });
    showToast({ type: 'success', message: 'Note added' });
    el(bodyEl, 'nbNoteTitle').value = '';
    el(bodyEl, 'nbNoteContent').value = '';
    loadNotes(bodyEl);
  } catch (err) {
    showToast({ type: 'error', message: `Add note failed: ${errMessage(err)}` });
  }
}

async function noteFromChat(bodyEl) {
  const chatId = el(bodyEl, 'nbFromChatId').value.trim();
  const messageId = el(bodyEl, 'nbFromChatMsg').value.trim();
  if (!chatId) { showToast({ type: 'error', message: 'Enter a chat id first.' }); return; }
  try {
    await apiFetch(`/notebooks/${encodeURIComponent(currentNotebookId)}/notes/from-chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: chatId, message_id: messageId || null }),
    });
    showToast({ type: 'success', message: 'Chat message saved as note' });
    loadNotes(bodyEl);
  } catch (err) {
    showToast({ type: 'error', message: `Save from chat failed: ${errMessage(err)}` });
  }
}

async function viewNote(bodyEl, noteId) {
  const box = el(bodyEl, 'nbNoteDetail');
  if (!box) return;
  box.innerHTML = '<p class="settings-hint">Loading note…</p>';
  try {
    const note = await (await apiFetch(`/notebooks/${encodeURIComponent(currentNotebookId)}/notes/${encodeURIComponent(noteId)}`)).json();
    const backs = await (await apiFetch(`/notebooks/${encodeURIComponent(currentNotebookId)}/notes/${encodeURIComponent(noteId)}/backlinks`)).json();
    const links = backs.backlinks || [];
    box.innerHTML = `
      <div class="nb-note-detail">
        <h5>${escapeHtml(note.title)}</h5>
        <p>${escapeHtml(note.content || '')}</p>
        <div id="nbBacklinks">
          <strong>Backlinks (${links.length})</strong>
          ${links.length ? `<ul>${links.map((b) => `<li>${escapeHtml(b.title)}</li>`).join('')}</ul>` : '<p class="settings-hint">No notes link here yet.</p>'}
        </div>
      </div>`;
  } catch {
    box.innerHTML = '<p class="settings-hint">Could not load note.</p>';
  }
}

async function loadTransforms(bodyEl) {
  const box = el(bodyEl, 'nbTransforms');
  if (!box || !currentNotebookId) return;
  try {
    const data = await (await apiFetch(`/notebooks/${encodeURIComponent(currentNotebookId)}/transforms`)).json();
    const items = data.transforms || [];
    box.innerHTML = items.length ? items.map((t) => `
      <div class="nb-row">
        <strong>${escapeHtml(t.name)}</strong>
        <span class="kn-mem-content">${escapeHtml((t.output || '').slice(0, 200))}</span>
      </div>`).join('') : '<p class="settings-hint">No transforms yet.</p>';
  } catch {
    box.innerHTML = '<p class="settings-hint">Could not load transforms.</p>';
  }
}

async function runTransform(bodyEl) {
  const name = el(bodyEl, 'nbTransformName').value.trim();
  const prompt = el(bodyEl, 'nbTransformPrompt').value.trim();
  if (!name || !prompt) { showToast({ type: 'error', message: 'Enter a transform name and prompt.' }); return; }
  try {
    await apiFetch(`/notebooks/${encodeURIComponent(currentNotebookId)}/transforms`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, prompt }),
    });
    showToast({ type: 'success', message: 'Transform saved as a note' });
    loadTransforms(bodyEl);
    loadNotes(bodyEl);
  } catch (err) {
    showToast({ type: 'error', message: `Transform failed: ${errMessage(err)}` });
  }
}

// ------------------------------------------------------------- memory tools

export function initMemoryTools(bodyEl) {
  const extractBtn = el(bodyEl, 'memv2ExtractBtn');
  if (!extractBtn || extractBtn.dataset.wired) return;
  extractBtn.dataset.wired = '1';
  extractBtn.addEventListener('click', () => runExtract(bodyEl));
  el(bodyEl, 'memv2ReflectBtn').addEventListener('click', () => runReflect(bodyEl));
  el(bodyEl, 'memv2TimelineBtn').addEventListener('click', () => loadTimeline(bodyEl));
  el(bodyEl, 'memv2TranscriptBtn').addEventListener('click', () => loadTranscripts(bodyEl));
  el(bodyEl, 'memv2UpdateBtn').addEventListener('click', () => updateMemory(bodyEl));
}

async function runExtract(bodyEl) {
  const text = el(bodyEl, 'memv2ExtractText').value.trim();
  const box = el(bodyEl, 'memv2ExtractResults');
  if (!text) { box.innerHTML = '<p class="settings-hint">Paste text first.</p>'; return; }
  box.innerHTML = '<p class="settings-hint">Extracting…</p>';
  try {
    const data = await (await apiFetch('/memory/extract', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    })).json();
    if (!data.model_used) {
      box.innerHTML = '<p class="settings-hint">No model is configured, so AI fact-finding is unavailable. Facts already stored by the chat loop still show in Memories above.</p>';
      return;
    }
    const facts = data.facts || [];
    box.innerHTML = facts.length
      ? `<ul>${facts.map((f) => `<li>${escapeHtml(f)}</li>`).join('')}</ul>`
      : '<p class="settings-hint">No durable facts found in that text.</p>';
  } catch (err) {
    box.innerHTML = `<p class="settings-hint">Extraction failed: ${escapeHtml(errMessage(err))}</p>`;
  }
}

async function runReflect(bodyEl) {
  const query = el(bodyEl, 'memv2ReflectQ').value.trim();
  const box = el(bodyEl, 'memv2ReflectResults');
  if (!query) { box.innerHTML = '<p class="settings-hint">Type a question first.</p>'; return; }
  box.innerHTML = '<p class="settings-hint">Reflecting…</p>';
  try {
    const data = await (await apiFetch('/memory/reflect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
    })).json();
    box.innerHTML = `
      <p><strong>Mental model:</strong> ${escapeHtml(data.mental_model || '')}</p>
      ${(data.observations || []).map((o) => `<p>· ${escapeHtml(o.text)} <small>(evidence: ${escapeHtml((o.evidence || []).join(', '))})</small></p>`).join('')}
      ${(data.open_questions || []).length ? `<p><strong>Open questions:</strong> ${escapeHtml(data.open_questions.join(' · '))}</p>` : ''}`;
  } catch (err) {
    box.innerHTML = `<p class="settings-hint">Reflection unavailable: ${escapeHtml(errMessage(err))}</p>`;
  }
}

async function loadTimeline(bodyEl) {
  const name = el(bodyEl, 'memv2EntityName').value.trim();
  const box = el(bodyEl, 'memv2Timeline');
  if (!name) { box.innerHTML = '<p class="settings-hint">Enter an entity name first.</p>'; return; }
  try {
    const data = await (await apiFetch(`/memory/entities/${encodeURIComponent(name)}/timeline`)).json();
    const rels = data.relations || [];
    box.innerHTML = rels.length
      ? rels.map((r) => `<p>${escapeHtml(r.subject)} ${escapeHtml(r.predicate)} ${escapeHtml(r.object)} <small>(${escapeHtml(r.valid_from || '')} → ${escapeHtml(r.valid_to || 'open')})</small></p>`).join('')
      : '<p class="settings-hint">No relations for this entity.</p>';
  } catch (err) {
    box.innerHTML = `<p class="settings-hint">Timeline failed: ${escapeHtml(errMessage(err))}</p>`;
  }
}

async function loadTranscripts(bodyEl) {
  const chatId = el(bodyEl, 'memv2TranscriptChat').value.trim();
  const box = el(bodyEl, 'memv2TranscriptList');
  try {
    const url = chatId ? `/memory/transcripts?chat_id=${encodeURIComponent(chatId)}` : '/memory/transcripts';
    const data = await (await apiFetch(url)).json();
    const rows = data.transcripts || [];
    box.innerHTML = rows.length
      ? rows.map((t) => `<p><strong>${escapeHtml(t.role)}:</strong> ${escapeHtml((t.text || '').slice(0, 300))}</p>`).join('')
      : '<p class="settings-hint">No transcripts yet — transcripts appear after chats that save memories.</p>';
  } catch {
    box.innerHTML = '<p class="settings-hint">Could not load transcripts.</p>';
  }
}

async function updateMemory(bodyEl) {
  const id = el(bodyEl, 'memv2UpdateId').value.trim();
  const status = el(bodyEl, 'memv2UpdateStatus');
  if (!id) { status.textContent = 'Enter a memory id first.'; return; }
  const payload = {};
  const content = el(bodyEl, 'memv2UpdateContent').value.trim();
  const importance = el(bodyEl, 'memv2UpdateImportance').value.trim();
  const room = el(bodyEl, 'memv2UpdateRoom').value.trim();
  const drawer = el(bodyEl, 'memv2UpdateDrawer').value.trim();
  if (content) payload.content = content;
  if (importance !== '') payload.importance = Number(importance);
  if (room) payload.room = room;
  if (drawer) payload.drawer = drawer;
  try {
    await apiFetch(`/memory/${encodeURIComponent(id)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    status.textContent = 'Memory updated.';
    showToast({ type: 'success', message: 'Memory updated' });
  } catch (err) {
    status.textContent = `Update failed: ${errMessage(err)}`;
  }
}
