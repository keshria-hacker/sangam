/*
message_view.js — message DOM construction for the chat feature.

Pure rendering: builds assistant/user message nodes and the in-stream
status widgets (thinking phase, reasoning, tool calls, citations,
artifacts). No streaming or event logic lives here — that is chat.js.
*/
import { escapeHtml, formatTime } from '../../shared/utils.js';
import { showToast } from '../../shared/toast.js';
import { apiFetch } from '../../shared/http.js';
import { renderMarkdown } from '../../shared/markdown.js';
import { PROVIDER_COLORS } from '../../shared/constants.js';
import {
  getMessages, setMessages, getSelectedModel, setLastUserText, getIsGenerating,
} from '../../core/state.js';

// Set by chat.js to break the circular dependency (render -> generate).
let _regenerate = null;
let _rerender = null;
let _runGeneration = null;

export function bindChatActions({ regenerate, rerender, runGeneration }) {
  _regenerate = regenerate;
  _rerender = rerender;
  _runGeneration = runGeneration;
}

export function getProviderInfo(model) {
  const providerId = model?.provider;
  if (!providerId) return { label: 'Unknown', state: 'offline', color: '#9AA1AC' };
  return {
    label: providerId,
    state: 'online',
    color: PROVIDER_COLORS[providerId] || '#9AA1AC',
  };
}


export function setThinkingPhase(node, phase, elapsedSec = null) {
  let statusEl = node.querySelector('.msg-phase-status');
  if (!statusEl) {
    statusEl = document.createElement('div');
    statusEl.className = 'msg-phase-status';
    const body = node.querySelector('.msg-body');
    // .typing-indicator is inside <article class="assistant-response">, so use that as reference
    const ref = body.querySelector('.msg-content') || body.querySelector('article.assistant-response');
    if (ref) {
      body.insertBefore(statusEl, ref);
    } else {
      body.appendChild(statusEl);
    }
  }

  const phases = {
    connecting: { text: 'Connecting…', icon: 'fa-solid fa-plug-circle-bolt' },
    thinking:   { text: 'Thinking…',   icon: 'fa-solid fa-brain' },
    writing:    { text: 'Writing…',    icon: 'fa-solid fa-pen-to-square' },
    done:       { text: 'Done',        icon: 'fa-solid fa-check' },
  };

  const p = phases[phase] || phases.connecting;
  let displayText = p.text;
  if (phase === 'done' && elapsedSec !== null) {
    displayText = `Done — ${elapsedSec}s`;
  }
  statusEl.className = `msg-phase-status ${phase}`;
  statusEl.innerHTML = `<i class="${p.icon}"></i><span>${displayText}</span>`;
  statusEl.setAttribute('aria-live', 'polite');
}

/**
 * Show or update the reasoning/thinking section inside an assistant message node.
 * Reasoning content is rendered as a collapsible <details> block above the
 * content area. It is ephemeral — not stored in message history.
 * Supports markdown rendering within reasoning blocks (§31).
 */
export function showReasoningInNode(node, text, opts = {}) {
  const { getThinkingDisplay } = opts.thinkingState || {};
  const displayPref = getThinkingDisplay ? getThinkingDisplay() : 'collapse';
  if (displayPref === 'hide') return;
  let section = node.querySelector('.msg-reasoning');
  if (!section) {
    section = document.createElement('div');
    section.className = 'msg-reasoning';
    section.dataset.thinkStart = String(Date.now());
    section.innerHTML = `<details${displayPref === 'expand' ? ' open' : ''}>
      <summary><i class="fa-solid fa-brain"></i> Thinking <span class="think-elapsed"></span></summary>
      <div class="msg-reasoning-content"></div>
    </details>`;
    const body = node.querySelector('.msg-body');
    // .typing-indicator is inside <article class="assistant-response">, so use that as reference
    const ref = body.querySelector('.msg-content') || body.querySelector('article.assistant-response');
    if (ref) {
      body.insertBefore(section, ref);
    } else {
      body.appendChild(section);
    }
  }
  const elapsedEl = section.querySelector('.think-elapsed');
  if (elapsedEl && section.dataset.thinkStart) {
    const secs = Math.floor((Date.now() - Number(section.dataset.thinkStart)) / 1000);
    elapsedEl.textContent = secs > 0 ? `· ${secs}s` : '';
  }
  const contentEl = section.querySelector('.msg-reasoning-content');
  if (contentEl) {
    // Render markdown for reasoning content
    contentEl.innerHTML = renderMarkdown(text || '');
    // Apply syntax highlighting if hljs is available
    import('../../shared/markdown.js').then(mod => {
      mod.enhanceCodeBlocks(contentEl);
    }).catch(() => {});
  }
}


/**
 * Show or update a tool call section inside an assistant message node.
 * Tool calls are rendered as collapsible blocks with function name and arguments.
 */
export function showToolCallInNode(node, toolCall) {
  let container = node.querySelector(".msg-tool-calls");
  if (!container) {
    container = document.createElement("div");
    container.className = "msg-tool-calls";
    const body = node.querySelector(".msg-body");
    // .typing-indicator is inside <article class="assistant-response">, so use that as reference
    const ref = body.querySelector(".msg-content") || body.querySelector("article.assistant-response");
    if (ref) {
      body.insertBefore(container, ref);
    } else {
      body.appendChild(container);
    }
  }

  let toolEl = container.querySelector('[data-tool-id="' + toolCall.id + '"]');
  if (!toolEl) {
    toolEl = document.createElement("div");
    toolEl.className = "tool-call";
    toolEl.dataset.toolId = toolCall.id;
    toolEl.innerHTML = '<details open><summary><i class="fa-solid fa-wrench"></i> ' + escapeHtml(toolCall.name) + ' <span class="tool-call-status"></span></summary><div class="tool-call-args"><pre><code>' + escapeHtml(toolCall.arguments || "") + '</code></pre></div><div class="tool-call-result" style="display:none;"></div></details>';
    container.appendChild(toolEl);
  }

  if (toolCall.arguments !== undefined) {
    const argsEl = toolEl.querySelector(".tool-call-args code");
    if (argsEl) argsEl.textContent = toolCall.arguments;
  }

  if (toolCall.status !== undefined) {
    const statusEl = toolEl.querySelector(".tool-call-status");
    if (statusEl) statusEl.textContent = toolCall.status;
  }

  if (toolCall.result !== undefined) {
    const resultEl = toolEl.querySelector(".tool-call-result");
    if (resultEl) {
      resultEl.style.display = "block";
      resultEl.innerHTML = "<pre><code>" + escapeHtml(toolCall.result) + "</code></pre>";
    }
    const statusEl = toolEl.querySelector(".tool-call-status");
    if (statusEl) statusEl.textContent = " ✓";
    toolEl.classList.add("completed");
  }
}


/**
 * Show || update a citation inside an assistant message node.
 * Citations are rendered as inline numbered references with a references list.
 */
export function showCitationInNode(node, citation) {
  let container = node.querySelector(".msg-citations");
  if (!container) {
    container = document.createElement("div");
    container.className = "msg-citations";
    const body = node.querySelector(".msg-body");
    // .msg-actions doesn't exist during streaming, use article.assistant-response as reference
    const ref = body.querySelector(".msg-actions") || body.querySelector("article.assistant-response");
    if (ref) {
      body.insertBefore(container, ref);
    } else {
      body.appendChild(container);
    }
  }

  const idx = citation.index ?? container.querySelectorAll(".citation-item").length + 1;
  let citeEl = container.querySelector('[data-citation-index="' + idx + '"]');
  if (!citeEl) {
    citeEl = document.createElement("div");
    citeEl.className = "citation-item";
    citeEl.dataset.citationIndex = idx;
    citeEl.innerHTML = '<span class="citation-badge">[' + idx + ']</span><span class="citation-title">' + escapeHtml(citation.title || "Source") + '</span>' + (citation.url ? '<a href="' + escapeHtml(citation.url) + '" target="_blank" rel="noopener noreferrer" class="citation-link"><i class="fa-solid fa-external-link-alt"></i></a>' : "");
    container.appendChild(citeEl);
  }

  if (citation.content) {
    citeEl.setAttribute("data-content", escapeHtml(citation.content));
  }
}


/**
 * Show || update an artifact inside an assistant message node.
 * Artifacts are rendered as separate content blocks (e.g., files, images, code).
 */
export function showArtifactInNode(node, artifact) {
  let container = node.querySelector(".msg-artifacts");
  if (!container) {
    container = document.createElement("div");
    container.className = "msg-artifacts";
    const body = node.querySelector(".msg-body");
    // .msg-actions doesn't exist during streaming, use article.assistant-response as reference
    const ref = body.querySelector(".msg-actions") || body.querySelector("article.assistant-response");
    if (ref) {
      body.insertBefore(container, ref);
    } else {
      body.appendChild(container);
    }
  }

  let artifactEl = container.querySelector('[data-artifact-id="' + artifact.id + '"]');
  if (!artifactEl) {
    artifactEl = document.createElement("div");
    artifactEl.className = "artifact";
    artifactEl.dataset.artifactId = artifact.id;
    artifactEl.innerHTML = '<div class="artifact-header"><span class="artifact-type"><i class="fa-solid fa-file-code"></i> ' + escapeHtml(artifact.type || "artifact") + '</span><span class="artifact-title">' + escapeHtml(artifact.title || "Untitled") + '</span></div><div class="artifact-content"></div>';
    container.appendChild(artifactEl);
  }

  const contentEl = artifactEl.querySelector(".artifact-content");
  if (contentEl && artifact.content !== undefined) {
    if (artifact.mime?.startsWith("text/") || artifact.type === "code") {
      contentEl.innerHTML = "<pre><code>" + escapeHtml(artifact.content) + "</code></pre>";
      import("../../shared/markdown.js").then(mod => { mod.enhanceCodeBlocks(contentEl); }).catch(() => {});
    } else if (artifact.mime?.startsWith("image/")) {
      contentEl.innerHTML = '<img src="' + escapeHtml(artifact.content) + '" alt="' + escapeHtml(artifact.title) + '" loading="lazy">';
    } else {
      contentEl.textContent = artifact.content;
    }
  }
}

/**
 * Media attachments (image/audio) — foundation for voice + image-gen.
 *
 * Streamed via MEDIA_START / MEDIA_DELTA / MEDIA_END: deltas carry base64 or
 * data-URI chunks, media_end carries the final served URL. Persisted messages
 * render from msg.media (see mediaHtml / buildMessageNode).
 */
export function showMediaInNode(node, media) {
  let container = node.querySelector(".msg-media");
  if (!container) {
    container = document.createElement("div");
    container.className = "msg-media";
    const body = node.querySelector(".msg-body");
    const ref = body.querySelector(".msg-actions") || body.querySelector("article.assistant-response") || body.querySelector(".msg-content");
    if (ref) {
      body.insertBefore(container, ref);
    } else {
      body.appendChild(container);
    }
  }

  const mediaId = media.id || "stream";
  let mediaEl = container.querySelector('[data-media-id="' + mediaId + '"]');
  if (!mediaEl) {
    mediaEl = document.createElement("div");
    mediaEl.className = "media-item";
    mediaEl.dataset.mediaId = mediaId;
    mediaEl.dataset.chunks = "";
    if (media.kind === "audio") {
      mediaEl.innerHTML = '<audio controls preload="metadata"></audio>';
    } else {
      mediaEl.innerHTML = '<img alt="' + escapeHtml(media.filename || "image") + '" loading="lazy">';
    }
    container.appendChild(mediaEl);
  }

  if (media.delta) {
    mediaEl.dataset.chunks += media.delta;
  }
  if (media.url) {
    const target = mediaEl.querySelector("img, audio");
    if (target) target.src = media.url;
    mediaEl.dataset.chunks = "";
  } else if (media.finalize && mediaEl.dataset.chunks) {
    const target = mediaEl.querySelector("img, audio");
    if (target) target.src = mediaEl.dataset.chunks;
  }
}

/**
 * Static HTML for persisted msg.media attachments (MediaAttachment list).
 */
export function mediaHtml(msg) {
  if (!msg.media || msg.media.length === 0) return "";
  return '<div class="msg-media">' + msg.media.map((m) => {
    const url = escapeHtml(m.url || "");
    const label = escapeHtml(m.filename || m.kind);
    if (m.kind === "audio") {
      return '<div class="media-item"><audio controls preload="metadata" src="' + url + '"></audio><div class="media-label">' + label + "</div></div>";
    }
    return '<div class="media-item"><img src="' + url + '" alt="' + label + '" loading="lazy"></div>';
  }).join("") + "</div>";
}

/**
 * Get provider display info for a model.
 */
export function buildMessageNode(msg) {
  const isUser = msg.role === 'user';

  if (isUser) {
    const node = document.createElement('div');
    node.className = 'msg user';
    node.dataset.id = msg.id || '';
    node.setAttribute('role', 'article');
    node.setAttribute('aria-label', `Your message, ${formatTime(msg.created_at)}`);
    node.innerHTML = `
      <div class="msg-avatar" aria-hidden="true"><i class="fa-solid fa-user" aria-hidden="true"></i></div>
      <div class="msg-body">
        <div class="msg-meta"><span class="msg-author">You</span><span class="msg-time">${formatTime(msg.created_at)}</span></div>
        <div class="msg-content" aria-live="polite">${escapeHtml(msg.content)}</div>
        ${mediaHtml(msg)}
        <div class="msg-edit-btn" title="Edit message"><i class="fa-regular fa-pen-to-square" aria-hidden="true"></i> Edit</div>
      </div>`;

    var editBtn = node.querySelector(".msg-edit-btn");
    if (editBtn) {
      editBtn.addEventListener("click", function() {
        var contentEl = node.querySelector(".msg-content");
        if (!contentEl) return;
        var origText = msg.content;
        var ta = document.createElement("textarea");
        ta.className = "msg-edit-textarea";
        ta.value = origText;
        contentEl.replaceWith(ta);
        editBtn.style.display = "none";

        var adiv = document.createElement("div");
        adiv.className = "msg-edit-actions";
        adiv.innerHTML = '<button class="msg-edit-save">Save</button><button class="msg-edit-cancel">Cancel</button>';
        ta.after(adiv);
        ta.focus();

        function doSave() {
          // Never edit mid-stream: _rerender would kill the in-flight
          // typing node and _runGeneration would start a second stream.
          if (getIsGenerating()) {
            showToast({ type: 'info', title: 'Still generating', message: 'Wait for the response to finish before editing.' });
            return;
          }
          var nt = ta.value.trim();
          if (nt && nt !== origText) {
            msg.content = nt;
            var allMsgs = getMessages();
            var idx = allMsgs.indexOf(msg);
            if (idx !== -1) {
              setMessages(allMsgs.slice(0, idx + 1));
              _rerender && _rerender();
              setLastUserText(nt);
              setTimeout(function() { _runGeneration && _runGeneration({ content: nt, fileIds: [], regenerate: true }); }, 100);
            }
          } else { doCancel(); }
        }
        function doCancel() {
          var rst = document.createElement("div");
          rst.className = "msg-content";
          rst.innerHTML = escapeHtml(origText);
          ta.replaceWith(rst);
          editBtn.style.display = "";
          adiv.remove();
        }
        adiv.querySelector(".msg-edit-save").addEventListener("click", doSave);
        adiv.querySelector(".msg-edit-cancel").addEventListener("click", doCancel);
        ta.addEventListener("keydown", function(e) {
          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSave(); }
          if (e.key === "Escape") { e.preventDefault(); doCancel(); }
        });
      });
    }
    return node;
  }

  // Assistant message
  const model = getSelectedModel();
  const info = getProviderInfo(model);
  const node = document.createElement('div');
  node.className = 'msg assistant';
  node.dataset.id = msg.id || '';
  // ARIA: mark as article for assistive tech, with role="log" for live content
  node.setAttribute('role', 'article');
  node.setAttribute('aria-label', `Message from ${escapeHtml(model?.name || msg.model || 'Assistant')}, ${formatTime(msg.created_at)}`);
  node.style.setProperty('--provider-color', info.color);

    
  // Wave-2 reload evidence: reloaded messages carry the same
  // tool_calls / citations / artifacts the live message had, but in
  // persisted shapes — tool arguments may be an object (provider
  // arguments dict), citations may carry only text/label instead of
  // a title. Normalize here so reload renders exactly like the live
  // message instead of "[object Object]" or a blank "Source" row.
  // (In-session messages already use these shapes, so this is a
  // no-op for them.)
  const reloadToolCalls = Array.isArray(msg.tool_calls) ? msg.tool_calls.map((tc) => ({
    ...tc,
    arguments: typeof tc.arguments === 'string' ? tc.arguments
      : (tc.arguments == null ? '' : JSON.stringify(tc.arguments)),
  })) : [];
  const reloadCitations = Array.isArray(msg.citations) ? msg.citations.map((c) => ({
    ...c,
    title: c.title || c.label || c.filename
      || (typeof c.text === 'string' && c.text ? c.text.slice(0, 80) : 'Source'),
  })) : [];
  const reloadArtifacts = Array.isArray(msg.artifacts) ? msg.artifacts : [];

  // Render tool calls if present
  let toolCallsHtml = "";
  if (reloadToolCalls.length > 0) {
    toolCallsHtml = '<div class="msg-tool-calls">' +
      reloadToolCalls.map(tc => '<details open><summary><i class="fa-solid fa-wrench"></i> ' + escapeHtml(tc.name) + ' <span class="tool-call-status"> ✓</span></summary><div class="tool-call-args"><pre><code>' + escapeHtml(tc.arguments || "") + '</code></pre></div><div class="tool-call-result" style="display:block;"><pre><code>' + escapeHtml(tc.result || "") + '</code></pre></div></details>').join("") +
      '</div>';
  }

  // Render citations if present
  let citationsHtml = "";
  if (reloadCitations.length > 0) {
    citationsHtml = '<div class="msg-citations">' +
      reloadCitations.map((c, idx) => '<div class="citation-item" data-citation-index="' + (idx + 1) + '"><span class="citation-badge">[' + (idx + 1) + ']</span><span class="citation-title">' + escapeHtml(c.title || "Source") + '</span>' + (c.url ? '<a href="' + escapeHtml(c.url) + '" target="_blank" rel="noopener noreferrer" class="citation-link"><i class="fa-solid fa-external-link-alt"></i></a>' : '') + '</div>').join("") +
      '</div>';
  }

  // Render artifacts if present
  let artifactsHtml = "";
  if (reloadArtifacts.length > 0) {
    artifactsHtml = '<div class="msg-artifacts">' +
      reloadArtifacts.map(a => {
      let contentHtml = "";
      if (a.mime?.startsWith("text/") || a.type === "code") {
        contentHtml = '<pre><code>' + escapeHtml(a.content || "") + '</code></pre>';
      } else if (a.mime?.startsWith("image/")) {
        contentHtml = '<img src="' + escapeHtml(a.content || "") + '" alt="' + escapeHtml(a.title || "") + '" loading="lazy">';
      } else {
        contentHtml = escapeHtml(a.content || "");
      }
      return '<div class="artifact"><div class="artifact-header"><span class="artifact-type"><i class="fa-solid fa-file-code"></i> ' + escapeHtml(a.type || "artifact") + '</span><span class="artifact-title">' + escapeHtml(a.title || "Untitled") + '</span></div><div class="artifact-content">' + contentHtml + '</div></div>';
      }).join("") +
      '</div>';
  }

  node.innerHTML = `
    <div class="msg-body">
      <div class="msg-meta">
        <span class="msg-author">${escapeHtml(model?.name || msg.model || "Assistant")}</span>
        <span class="msg-provider-tag" style="color:${info.color}">${escapeHtml(info.label)}</span>
        <span class="msg-time">${formatTime(msg.created_at)}</span>
        ${msg.response_time != null ? `<span class="msg-response-time">${msg.response_time.toFixed(1)}s</span>` : ""}
      </div>
      <article class="assistant-response" aria-live="polite">${msg.content ? renderMarkdown(msg.content) : ""}</article>
      ${toolCallsHtml}
      ${citationsHtml}
      ${artifactsHtml}
      ${mediaHtml(msg)}
      <div class="msg-actions always-visible" role="group" aria-label="Message actions">
        <button class="msg-action-btn copy-msg-btn" aria-label="Copy message"><i class="fa-regular fa-copy" aria-hidden="true"></i> Copy</button>
        <button class="msg-action-btn regenerate-btn" aria-label="Regenerate response"><i class="fa-solid fa-arrow-rotate-right" aria-hidden="true"></i> Regenerate</button>
        <button class="msg-action-btn save-msg-btn" aria-label="Save answer as a file"><i class="fa-regular fa-bookmark" aria-hidden="true"></i> Save</button>
        <button class="msg-action-btn msg-more-btn" type="button" aria-label="More message actions" aria-expanded="false" aria-haspopup="true"><i class="fa-solid fa-ellipsis" aria-hidden="true"></i> More</button>
        <div class="msg-more-menu hidden" role="group" aria-label="More message actions">
        <button class="msg-action-btn workflow-msg-btn" aria-label="Turn this chat into a workflow"><i class="fa-solid fa-diagram-project" aria-hidden="true"></i> Workflow</button>
        <button class="msg-action-btn inspect-msg-btn" aria-label="Inspect this message's evidence"><i class="fa-solid fa-circle-info" aria-hidden="true"></i> Inspect</button>
        <button class="msg-action-btn quality-msg-btn" aria-label="Check this message's writing quality"><i class="fa-solid fa-spell-check" aria-hidden="true"></i> Check writing</button>
        <button class="msg-action-btn humanize-msg-btn" aria-label="Rewrite this message in plainer, more natural phrasing"><i class="fa-solid fa-pen" aria-hidden="true"></i> Natural rewrite</button>
        ${window.__sangamVoice ? '<button class="msg-action-btn speak-msg-btn" aria-label="Read aloud"><i class="fa-solid fa-volume-high" aria-hidden="true"></i> Speak</button>' : ''}
        <button class="msg-action-btn feedback-btn${msg.feedback === 'up' ? ' feedback-active' : ''}" aria-label="Thumbs up" data-value="up"${msg.feedback === 'up' ? ' aria-pressed="true"' : ''}><i class="fa-regular fa-thumbs-up" aria-hidden="true"></i></button>
        <button class="msg-action-btn feedback-btn${msg.feedback === 'down' ? ' feedback-active' : ''}" aria-label="Thumbs down" data-value="down"${msg.feedback === 'down' ? ' aria-pressed="true"' : ''}><i class="fa-regular fa-thumbs-down" aria-hidden="true"></i></button>
        </div>
      </div>
    </div>`; // Copy button
  // "More" menu (UI-simplify): only Copy / Regenerate / Save show by
  // default; the rest live in this menu. Buttons keep their original
  // classes, so every handler below still finds them unchanged.
  const moreBtn = node.querySelector('.msg-more-btn');
  const moreMenu = node.querySelector('.msg-more-menu');
  const closeMoreMenu = () => {
    moreMenu?.classList.add('hidden');
    moreBtn?.setAttribute('aria-expanded', 'false');
  };
  moreBtn?.addEventListener('click', () => {
    const willOpen = moreMenu?.classList.contains('hidden');
    closeMoreMenu();
    if (willOpen) {
      moreMenu.classList.remove('hidden');
      moreBtn.setAttribute('aria-expanded', 'true');
    }
  });
  // Choosing an action closes the menu (this bubble-phase listener runs
  // after the action button's own handler); Escape closes it too.
  moreMenu?.addEventListener('click', closeMoreMenu);
  moreMenu?.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMoreMenu(); });
  const copyBtn = node.querySelector('.copy-msg-btn');
  copyBtn.addEventListener('click', () => {
    navigator.clipboard.writeText(msg.content || '').then(() => {
      copyBtn.classList.add('copied');
      copyBtn.innerHTML = `<i class="fa-solid fa-check"></i> Copied`;
      setTimeout(() => {
        copyBtn.classList.remove('copied');
        copyBtn.innerHTML = `<i class="fa-regular fa-copy"></i> Copy`;
      }, 1600);
    });
  });

  // Regenerate button
  const regenBtn = node.querySelector('.regenerate-btn');
  regenBtn.addEventListener('click', () => _regenerate && _regenerate());

  // Save button (UX-refine wave): one click saves the answer as a .md
  // file via the existing POST /files upload endpoint (md is an allowed
  // extension and uploads are indexed for retrieval). Saved files surface
  // under Create → Documents, so the toast says exactly that.
  const saveBtn = node.querySelector('.save-msg-btn');
  saveBtn?.addEventListener('click', async () => {
    if (saveBtn.disabled) return;
    saveBtn.disabled = true;
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 16);
    const form = new FormData();
    form.append('file', new Blob([msg.content || ''], { type: 'text/markdown' }), `sangam-answer-${stamp}.md`);
    try {
      const res = await apiFetch('/files', { method: 'POST', body: form });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Save failed (${res.status})`);
      saveBtn.innerHTML = '<i class="fa-solid fa-check"></i> Saved';
      showToast({ type: 'success', title: 'Answer saved', message: 'Saved as a file — find it in Create → Documents.' });
    } catch (err) {
      saveBtn.disabled = false;
      showToast({ type: 'error', title: 'Save failed', message: err?.message || String(err) });
    }
  });

  // Workflow button (UX-refine wave): one click turns this chat into a
  // runnable workflow via the existing POST /workflows endpoint — a
  // single llm node whose prompt is the last user question (or, if the
  // chat has none, the canvas default {{input.q}} template) — then opens
  // Work → Workflows with the new workflow listed.
  const wfBtn = node.querySelector('.workflow-msg-btn');
  wfBtn?.addEventListener('click', async () => {
    if (wfBtn.disabled) return;
    wfBtn.disabled = true;
    try {
      const msgs = getMessages();
      const lastUser = [...msgs].reverse().find((m) => m.role === 'user');
      const prompt = lastUser?.content?.trim() || '{{input.q}}';
      const name = `From chat: ${(lastUser?.content || 'answer').slice(0, 60)}`;
      const res = await apiFetch('/workflows', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name,
          definition: { nodes: [{ id: 'prompt', type: 'llm', config: { prompt } }], edges: [] },
          trigger: 'manual',
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Workflow creation failed (${res.status})`);
      showToast({ type: 'success', title: 'Workflow created', message: `"${name}" is ready in Work → Workflows.` });
      const { showToolSection } = await import('../tabs/tabs.js');
      showToolSection('work', 'workflows');
    } catch (err) {
      showToast({ type: 'error', title: 'Workflow failed', message: err?.message || String(err) });
    } finally {
      wfBtn.disabled = false;
    }
  });

  // Inspect button (UX-refine wave): selects this message in the
  // Inspector, where its tool calls, sources, and artifacts are shown
  // next to chat — no tab hop to review evidence.
  const inspectBtn = node.querySelector('.inspect-msg-btn');
  inspectBtn?.addEventListener('click', async () => {
    const { setSelectedMessage, isInspectorVisible, toggleInspector } = await import('../inspector/inspector.js');
    setSelectedMessage(msg);
    if (!isInspectorVisible()) toggleInspector();
  });

  // Speak button (voice feature) — toggles to Stop while speaking
  const speakBtn = node.querySelector('.speak-msg-btn');
  if (speakBtn) {
    const baseHtml = speakBtn.innerHTML;
    speakBtn.addEventListener('click', async () => {
      const m = await import('../voice/voice.js');
      const article = node.querySelector('article.assistant-response');
      m.speakText(article ? article.innerText : (msg.content || ''), node);
    });
    // Reflect controller state on this button
    import('../voice/voice.js').then((m) => {
      m.onVoiceState((state) => {
        const active = (state === 'speaking' || state === 'fetching') && m.getSpeakingNode() === node;
        speakBtn.classList.toggle('speaking', active);
        speakBtn.innerHTML = active
          ? '<i class="fa-solid fa-stop"></i> Stop'
          : baseHtml;
        speakBtn.setAttribute('aria-pressed', String(active));
      });
    }).catch(() => {});
  }

  // Check writing + Natural rewrite (Batch 13 writing-quality, Chat-wired):
  // per-message actions that call /quality/report and /quality/humanize
  // and render the result INLINE under the message. Nothing is ever
  // auto-applied: Check only reports, and Rewrite shows the rewritten
  // text in a panel with its own Copy button — the original message
  // stays untouched until the user copies or saves the rewrite.
  // The rewrite panel states plainly that it improves readability
  // and does not evade AI detectors.
  function qualityPanel() {
    let panel = node.querySelector('.msg-quality-panel');
    if (!panel) {
      panel = document.createElement('div');
      panel.className = 'msg-quality-panel';
      const actions = node.querySelector('.msg-actions');
      (actions ? actions.parentNode : node).insertBefore(panel, actions ? actions.nextSibling : null);
    }
    return panel;
  }
  const checkBtn = node.querySelector('.quality-msg-btn');
  checkBtn?.addEventListener('click', async () => {
    if (checkBtn.disabled) return;
    checkBtn.disabled = true;
    const panel = qualityPanel();
    panel.innerHTML = '<p>Checking writing…</p>';
    try {
      const res = await apiFetch('/quality/report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: msg.content || '' }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Quality check failed (${res.status})`);
      const r = data.readability || {};
      const pre = data.adhd_pre_send_check || {};
      const fmt = (hits) => (hits || []).map((h) => `<li>${escapeHtml(h.pattern || h.rule || '')} (line ${h.line}): “${escapeHtml(h.quote || '')}” — ${escapeHtml(h.fix || h.suggestion || '')}</li>`).join('');
      panel.innerHTML = `<div class="quality-report"><p><strong>Writing check:</strong> ${escapeHtml(data.summary || '')}</p>`
        + `<p>Readability (rough figures, not a grade): ${r.words ?? 0} words, ${r.sentences ?? 0} sentences, avg ${r.avg_sentence_words ?? 0} words/sentence, ${r.long_sentences ?? 0} long sentences. ${escapeHtml(r.note || '')}</p>`
        + (pre.issues?.length ? `<p>ADHD pre-send check: ${escapeHtml(pre.issues.join('; '))}</p>` : '<p>ADHD pre-send check: first line is an action and last line is a next step.</p>')
        + (data.slop?.length ? `<p>Slop hits:</p><ul>${fmt(data.slop)}</ul>` : '')
        + (data.structure?.length ? `<p>Structural patterns:</p><ul>${fmt(data.structure)}</ul>` : '')
        + `<p>Full ranked findings with fixes: use Check in Settings → Quality, or POST /quality/check. This panel never rewrites your message.</p></div>`;
    } catch (err) {
      panel.innerHTML = `<p>Quality check failed: ${escapeHtml(err?.message || String(err))}</p>`;
    } finally {
      checkBtn.disabled = false;
    }
  });
  const rewriteBtn = node.querySelector('.humanize-msg-btn');
  rewriteBtn?.addEventListener('click', async () => {
    if (rewriteBtn.disabled) return;
    rewriteBtn.disabled = true;
    const panel = qualityPanel();
    panel.innerHTML = '<p>Rewriting for readability…</p>';
    try {
      const res = await apiFetch('/quality/humanize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: msg.content || '' }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Rewrite failed (${res.status})`);
      const changes = (data.changes || []).map((c) => `<li>${escapeHtml(c.pattern)}: “${escapeHtml(c.before)}” → “${escapeHtml(c.after)}”</li>`).join('');
      panel.innerHTML = `<div class="quality-rewrite"><p><strong>Natural rewrite (readability only):</strong></p>`
        + `<article class="assistant-response">${renderMarkdown(data.rewritten || '')}</article>`
        + `<p>${escapeHtml(data.note || '')}</p>`
        + (changes ? `<p>What changed:</p><ul>${changes}</ul>` : '<p>No changes: the text was already plain.</p>')
        + `<button class="msg-action-btn quality-copy-btn" type="button"><i class="fa-regular fa-copy" aria-hidden="true"></i> Copy rewrite</button>`
        + `<p>The original message above is unchanged — copy the rewrite only if you want it.</p></div>`;
      panel.querySelector('.quality-copy-btn')?.addEventListener('click', () => {
        navigator.clipboard.writeText(data.rewritten || '').then(() => {
          showToast({ type: 'success', title: 'Rewrite copied' });
        }).catch(() => {});
      });
    } catch (err) {
      panel.innerHTML = `<p>Rewrite failed: ${escapeHtml(err?.message || String(err))}</p>`;
    } finally {
      rewriteBtn.disabled = false;
    }
  });

  // Feedback buttons (thumbs up/down) — persisted via the messages API.
  // Clicking the active thumb again clears the feedback (toggle-off undo).
  node.querySelectorAll('.feedback-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const value = btn.dataset.value;                 // "up" | "down"
      const wasActive = btn.classList.contains('feedback-active');
      // Server clears feedback when the same value is re-sent (toggle-off undo),
      // so the client always sends the clicked value as-is.
      // Optimistic UI: flip active state immediately, revert on failure.
      node.querySelectorAll('.feedback-btn').forEach((b) => {
        b.classList.remove('feedback-active');
        b.removeAttribute('aria-pressed');
      });
      if (!wasActive) {
        btn.classList.add('feedback-active');
        btn.setAttribute('aria-pressed', 'true');
      }
      try {
        await apiFetch(`/messages/${msg.id}/feedback`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ value }),
        });
        msg.feedback = wasActive ? null : value;   // keep local state in sync for re-renders
        showToast(wasActive
          ? { type: 'info', title: 'Feedback cleared' }
          : { type: 'success', title: 'Thanks!', message: 'Feedback saved.' });
      } catch (err) {
        // Revert optimistic update on failure.
        node.querySelectorAll('.feedback-btn').forEach((b) => {
          b.classList.remove('feedback-active');
          b.removeAttribute('aria-pressed');
        });
        const saved = msg.feedback;
        if (saved) {
          const activeBtn = node.querySelector(`.feedback-btn[data-value="${saved}"]`);
          activeBtn?.classList.add('feedback-active');
          activeBtn?.setAttribute('aria-pressed', 'true');
        }
        showToast({ type: 'error', title: 'Failed to save feedback', message: err.message || 'Please try again.' });
      }
    });
  });

  return node;
}

