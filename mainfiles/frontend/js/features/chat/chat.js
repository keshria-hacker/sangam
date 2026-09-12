/**
 * Chat feature - Message handling, streaming, and chat management.
 */

import { getApiBaseUrl, apiFetch, streamChatCompletion, parseSSE, ApiError } from '../../shared/http.js';
import { showToast, showError } from '../../shared/toast.js';
import { escapeHtml, formatTime, nowTime, formatBytes, extOf } from '../../shared/utils.js';
import { renderMarkdown, renderMarkdownStream, finalizeMarkdownRender, clearStreamCache } from '../../shared/markdown.js';
import { createResponseController } from './response_controller.js';
import {
  getMessages, setMessages, getActiveChatId, setActiveChatId,
  getSelectedModel, selectModel, getModels, getAttachedFiles, setAttachedFiles,
  getLastUserText, setLastUserText, getIsGenerating, setIsGenerating,
  getAbortController, setAbortController, getWebSearchEnabled, setWebSearchEnabled,
  getMaxTokens, getReasoningEffort, getTemperature,
  getChats, setChats,
  resetChatState
} from '../../core/state.js';
import { PROVIDER_COLORS, FILE_ICON_MAP } from '../../shared/constants.js';
console.log('[Module] chat.js loaded');

// DOM elements
let elements = {};

// Monotonic generation counter — prevents a stale minimum-duration
// pause in one runGeneration() from resetting the button while a
// newer generation is already in progress.
let _genCounter = 0;

/**
 * Initialize DOM references.
 */
export function initElements() {
  elements = {
    chatScroll: $('#chatScroll'),
    chatColumn: $('#chatColumn'),
    welcomeScreen: $('#welcomeScreen'),
    messages: $('#messages'),
    skeletonWrap: $('#skeletonWrap'),
    errorState: $('#errorState'),
    errorDetailToggle: $('#errorDetailToggle'),
    retryBtn: $('#retryBtn'),
    scrollBottomBtn: $('#scrollBottomBtn'),
    backendDownState: $('#backendDownState'),
    fileChips: $('#fileChips'),
    attachBtn: $('#attachBtn'),
    fileInput: $('#fileInput'),
    messageInput: $('#messageInput'),
    sendBtn: $('#sendBtn'),
    stopBtn: $('#stopBtn'),
    webSearchToggle: $('#webSearchToggle'),
    tempControl: $('#tempControl'),
    tempPopover: $('#tempPopover'),
    tempSlider: $('#tempSlider'),
    tempValue: $('#tempValue'),
    tempPopoverValue: $('#tempPopoverValue'),
    tokenBtn: $('#tokenBtn'),
    tokenLabel: $('#tokenLabel'),
    tokenDropdown: $('#tokenDropdown'),
    tokenSelect: $('#tokenSelect'),
    reasoningBtn: $('#reasoningBtn'),
    reasoningLabel: $('#reasoningLabel'),
    reasoningDropdown: $('#reasoningDropdown'),
    reasoningSelect: $('#reasoningSelect'),
  };
}

/**
 * Set unified send/stop button visual state.
 * - idle:       accent bg, ▲ send-arrow (sendBtn visible, stopBtn hidden)
 * - generating: red bg, ⏹ stop icon   (stopBtn visible, sendBtn hidden)
 *
 * Uses TWO separate buttons and toggles visibility — eliminates all
 * CSS-cascade issues, transition blending, and class-toggling bugs.
 */
function setSendButtonState(generating) {
  const sendBtn = document.getElementById('sendBtn');
  const stopBtn = document.getElementById('stopBtn');
  if (!sendBtn || !stopBtn) return;

  if (generating) {
    sendBtn.style.display = 'none';
    stopBtn.style.display = '';
    document.title = 'Generating… — Sangam';
  } else {
    sendBtn.style.display = '';
    stopBtn.style.display = 'none';
    document.title = 'Sangam — Universal AI Chat Platform';
  }
}

/**
 * Phase-aware response status helper.
 * Updates the assistant message node with the current response phase.
 */
function setThinkingPhase(node, phase, elapsedSec = null) {
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
function showReasoningInNode(node, text) {
  let section = node.querySelector('.msg-reasoning');
  if (!section) {
    section = document.createElement('div');
    section.className = 'msg-reasoning';
    section.innerHTML = `<details open>
      <summary><i class="fa-solid fa-brain"></i> Reasoning</summary>
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
function showToolCallInNode(node, toolCall) {
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
function showCitationInNode(node, citation) {
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
function showArtifactInNode(node, artifact) {
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
 * Get provider display info for a model.
 */
function getProviderInfo(model) {
  const providerId = model?.provider;
  if (!providerId) return { label: 'Unknown', state: 'offline', color: '#9AA1AC' };
  return {
    label: providerId,
    state: 'online',
    color: PROVIDER_COLORS[providerId] || '#9AA1AC',
  };
}

/**
 * Build a message DOM node for rendering.
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
          var nt = ta.value.trim();
          if (nt && nt !== origText) {
            msg.content = nt;
            var allMsgs = getMessages();
            var idx = allMsgs.indexOf(msg);
            if (idx !== -1) {
              setMessages(allMsgs.slice(0, idx + 1));
              renderMessages();
              setLastUserText(nt);
              setTimeout(function() { runGeneration({ content: nt, fileIds: [], regenerate: true }); }, 100);
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

    
  // Render tool calls if present
  let toolCallsHtml = "";
  if (msg.tool_calls && msg.tool_calls.length > 0) {
    toolCallsHtml = '<div class="msg-tool-calls">' +
      msg.tool_calls.map(tc => '<details open><summary><i class="fa-solid fa-wrench"></i> ' + escapeHtml(tc.name) + ' <span class="tool-call-status"> ✓</span></summary><div class="tool-call-args"><pre><code>' + escapeHtml(tc.arguments || "") + '</code></pre></div><div class="tool-call-result" style="display:block;"><pre><code>' + escapeHtml(tc.result || "") + '</code></pre></div></details>').join("") +
      '</div>';
  }

  // Render citations if present
  let citationsHtml = "";
  if (msg.citations && msg.citations.length > 0) {
    citationsHtml = '<div class="msg-citations">' +
      msg.citations.map((c, idx) => '<div class="citation-item" data-citation-index="' + (idx + 1) + '"><span class="citation-badge">[' + (idx + 1) + ']</span><span class="citation-title">' + escapeHtml(c.title || "Source") + '</span>' + (c.url ? '<a href="' + escapeHtml(c.url) + '" target="_blank" rel="noopener noreferrer" class="citation-link"><i class="fa-solid fa-external-link-alt"></i></a>' : '') + '</div>').join("") +
      '</div>';
  }

  // Render artifacts if present
  let artifactsHtml = "";
  if (msg.artifacts && msg.artifacts.length > 0) {
    artifactsHtml = '<div class="msg-artifacts">' +
      msg.artifacts.map(a => {
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
      <div class="msg-actions always-visible" role="group" aria-label="Message actions">
        <button class="msg-action-btn copy-msg-btn" aria-label="Copy message"><i class="fa-regular fa-copy" aria-hidden="true"></i> Copy</button>
        <button class="msg-action-btn regenerate-btn" aria-label="Regenerate response"><i class="fa-solid fa-arrow-rotate-right" aria-hidden="true"></i> Regenerate</button>
        <button class="msg-action-btn feedback-btn${msg.feedback === 'up' ? ' feedback-active' : ''}" aria-label="Thumbs up" data-value="up"${msg.feedback === 'up' ? ' aria-pressed="true"' : ''}><i class="fa-regular fa-thumbs-up" aria-hidden="true"></i></button>
        <button class="msg-action-btn feedback-btn${msg.feedback === 'down' ? ' feedback-active' : ''}" aria-label="Thumbs down" data-value="down"${msg.feedback === 'down' ? ' aria-pressed="true"' : ''}><i class="fa-regular fa-thumbs-down" aria-hidden="true"></i></button>
      </div>
    </div>`; // Copy button
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
  regenBtn.addEventListener('click', () => regenerate());

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

/**
 * Render all messages to the DOM.
 */
export function renderMessages() {
  const messages = getMessages();
  const container = elements.messages;
  if (!container) return;

  container.innerHTML = '';
  messages.forEach((m) => container.appendChild(buildMessageNode(m)));

  // Full re-render resets auto-scroll to "following latest".
  _followStream = true;
  updateJumpBtn();
}

/**
 * Smart auto-scroll (§27): while the user is near the bottom the stream keeps
 * following the latest content; the moment they scroll up, following stops.
 * A "↓ Jump to latest" button reappears and resumes following on click.
 *
 * Hysteresis keeps the flag from flapping on trackpad/touch momentum: we stop
 * following only once the user is clearly away (> THRESHOLD), and re-engage
 * only when they return to the very bottom (< REENGAGE).
 */
let _followStream = true;             // whether new tokens auto-scroll the view
let _suppressScrollHandler = false;   // guard for programmatic scrolls
const AUTO_SCROLL_THRESHOLD_PX = 220; // dist beyond which following stops
const AUTO_SCROLL_REENGAGE_PX = 60;   // dist within which following resumes
const SMOOTH_SCROLL_SETTLE_MS = 400;  // how long a smooth scroll fires scroll events

function nearBottomDist() {
  const scrollEl = elements.chatScroll;
  if (!scrollEl) return 0;
  return scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight;
}

/**
 * Scroll to bottom of chat. Programmatic smooth scrolls fire many passive
 * scroll events, so the follow-state listener is suspended for the duration
 * of the animation — otherwise an in-flight smooth scroll could re-capture a
 * user who is actively reading further up the history.
 */
export function scrollToBottom(smooth = true) {
  const scrollEl = elements.chatScroll;
  if (!scrollEl) return;
  if (smooth) {
    _suppressScrollHandler = true;
    scrollEl.scrollTo({ top: scrollEl.scrollHeight, behavior: 'smooth' });
    setTimeout(() => {
      _suppressScrollHandler = false;
      updateJumpBtn();
    }, SMOOTH_SCROLL_SETTLE_MS);
  } else {
    scrollEl.scrollTo({ top: scrollEl.scrollHeight, behavior: 'auto' });
  }
}

export function scrollToBottomIfNearBottom() {
  if (!_followStream) return;         // user scrolled away — don't yank them down
  if (nearBottomDist() < AUTO_SCROLL_THRESHOLD_PX) scrollToBottom(false);
}

/**
 * Show/hide the "↓ Jump to latest" button. Visible only when following has
 * been suspended (user scrolled up) and there is actual overflow.
 */
function updateJumpBtn() {
  const btn = elements.scrollBottomBtn;
  if (!btn) return;
  btn.classList.toggle('hidden', _followStream || nearBottomDist() < AUTO_SCROLL_THRESHOLD_PX);
}

/**
 * Passive scroll listener — tracks whether the user is still near the bottom.
 * Uses hysteresis so momentum scrolls near the threshold don't flicker the flag.
 */
function onChatScroll() {
  if (_suppressScrollHandler) return;
  const dist = nearBottomDist();
  if (_followStream) {
    if (dist > AUTO_SCROLL_THRESHOLD_PX) _followStream = false;
  } else if (dist < AUTO_SCROLL_REENGAGE_PX) {
    _followStream = true;
  }
  updateJumpBtn();
}

/**
 * Jump to the latest message and resume auto-following.
 */
function resumeFollow() {
  _followStream = true;
  _suppressScrollHandler = true;
  scrollToBottom(false);
  requestAnimationFrame(() => {
    _suppressScrollHandler = false;
    updateJumpBtn();
  });
}

/**
 * Handle file attachments - render file chips.
 */
export function renderFileChips() {
  const container = elements.fileChips;
  if (!container) return;

  const files = getAttachedFiles();
  container.innerHTML = '';

  files.forEach((f) => {
    const info = FILE_ICON_MAP[f.ext] || { icon: 'fa-file', color: '#9AA1AC' };
    const chip = document.createElement('div');
    chip.className = 'file-chip';
    chip.innerHTML = `
      <span class="file-chip-icon" style="background:${info.color}"><i class="fa-solid ${f.uploading ? 'fa-spinner fa-spin' : info.icon}"></i></span>
      <span class="file-chip-info">
        <span class="file-chip-name">${escapeHtml(f.name)}</span>
        <span class="file-chip-size">${f.uploading ? 'Uploading…' : formatBytes(f.size)}</span>
      </span>
      <button class="file-chip-remove" aria-label="Remove file"><i class="fa-solid fa-xmark"></i></button>
    `;

    chip.querySelector('.file-chip-remove').addEventListener('click', () => {
      const updated = getAttachedFiles().filter((x) => x.localId !== f.localId);
      setAttachedFiles(updated);
      renderFileChips();
    });

    container.appendChild(chip);
  });
}

/**
 * Handle file selection and upload.
 */
export async function handleFileSelection(fileList) {
  const accepted = [];
  let rejected = 0;

  Array.from(fileList).forEach((file) => {
    const ext = extOf(file.name);
    if (!FILE_ICON_MAP[ext]) {
      rejected++;
      return;
    }
    accepted.push(file);
  });

  if (rejected) showToast({ type: 'error', title: 'Unsupported file type', message: `${rejected} file(s) skipped.` });

  for (const file of accepted) {
    const localId = `local_${Math.random().toString(36).slice(2, 9)}`;
    const placeholder = { localId, id: null, name: file.name, size: file.size, ext: extOf(file.name), uploading: true };
    setAttachedFiles([...getAttachedFiles(), placeholder]);
    renderFileChips();

    try {
      const form = new FormData();
      form.append('file', file);
      const res = await apiFetch('/files', { method: 'POST', body: form });
      const data = await res.json();

      const newFiles = getAttachedFiles().map((f) =>
        f.localId === localId ? { ...f, id: data.file_id, size: data.size_bytes, uploading: false } : f
      );
      setAttachedFiles(newFiles);
      renderFileChips();
    } catch (err) {
      const newFiles = getAttachedFiles().filter((f) => f.localId !== localId);
      setAttachedFiles(newFiles);
      renderFileChips();
      showToast({ type: 'error', title: `Upload failed: ${file.name}`, message: err.message });
    }
  }
}

/**
 * Sending a message - main entry point.
 */
export function handleSend() {
  const text = elements.messageInput?.value.trim() || '';
  const files = getAttachedFiles();

  if (!text && files.length === 0) return;
  if (getIsGenerating()) return;
  if (!getSelectedModel()) {
    showToast({ type: 'info', title: 'Select a provider', message: 'Start Ollama or link a provider key before sending a message.' });
    return;
  }
  if (files.some((f) => f.uploading)) {
    showToast({ type: 'info', message: 'Still uploading a file — one moment.' });
    return;
  }

  elements.welcomeScreen?.classList.add('hidden');

  const userMsg = { role: 'user', content: text || '(Sent with attached files)', created_at: new Date().toISOString() };
  setMessages([...getMessages(), userMsg]);
  elements.messages?.appendChild(buildMessageNode(userMsg));
  setLastUserText(userMsg.content);

  elements.messageInput.value = '';
  autoResizeTextarea();

  const fileIds = files.map((f) => f.id).filter(Boolean);
  setAttachedFiles([]);
  renderFileChips();
  _followStream = true; // a new send re-engages auto-following
  updateJumpBtn();
  scrollToBottom(true);

  runGeneration({ content: userMsg.content, fileIds, regenerate: false });
}

/**
 * Regenerate last assistant response.
 */
export function regenerate() {
  if (getIsGenerating() || !getLastUserText()) return;
  if (!getSelectedModel()) {
    showToast({ type: 'info', title: 'Model required', message: 'Select a model before regenerating.' });
    return;
  }

  // Remove last assistant message
  const msgs = getMessages();
  const lastIdx = msgs.findLastIndex((m) => m.role === 'assistant');
  if (lastIdx !== -1) {
    const updated = msgs.slice(0, lastIdx);
    setMessages(updated);
    renderMessages();
  }

  runGeneration({ content: getLastUserText(), fileIds: [], regenerate: true });
}

/**
 * Core generation logic with SSE streaming.
 */
export async function runGeneration({ content, fileIds, regenerate }) {
  const model = getSelectedModel();
  if (!model) {
    showToast({ type: 'info', title: 'Model required', message: 'Select a model before sending a message.' });
    return;
  }

  setIsGenerating(true);
  setSendButtonState(true);
  // Clear streaming markdown cache for new generation
  clearStreamCache();
  // Yield so the stop-button generating state paints before stream I/O begins
  await new Promise((r) => setTimeout(r, 0));

  const genStartedAt = Date.now();
  const genId = ++_genCounter;
  const MIN_STOP_VISIBLE_MS = 2000;

  elements.errorState?.classList.add('hidden');
  const info = getProviderInfo(model);

  // Initial assistant message node with CONNECTING phase
  const typingNode = document.createElement('div');
  typingNode.className = 'msg assistant';
  typingNode.setAttribute('role', 'article');
  typingNode.setAttribute('aria-label', `Response from ${escapeHtml(model.name)}, generating`);
  typingNode.style.setProperty('--provider-color', info.color);
  typingNode.innerHTML = `
    <div class="msg-avatar" style="color:${info.color}" aria-hidden="true"><i class="fa-solid fa-sparkles" aria-hidden="true"></i></div>
    <div class="msg-body">
      <div class="msg-meta"><span class="msg-author">${escapeHtml(model.name)}</span><span class="msg-provider-tag" style="color:${info.color}">${escapeHtml(info.label)}</span></div>
      <article class="assistant-response" aria-live="polite" aria-busy="true"><div class="typing-indicator" aria-label="Generating response"><span aria-hidden="true"></span><span aria-hidden="true"></span><span aria-hidden="true"></span></div></article>
    </div>`;
  elements.messages?.appendChild(typingNode);
  scrollToBottom(true);

  var _thinkStartTime = Date.now();
  var _thinkTimer = null;
  function startElapsedTimer() {
    if (_thinkTimer) clearInterval(_thinkTimer);
    _thinkTimer = setInterval(function() {
      var elapsed = Math.floor((Date.now() - _thinkStartTime) / 1000);
      var phaseEl = typingNode.querySelector(".msg-phase-status");
      if (phaseEl) {
        var es = phaseEl.querySelector(".msg-thinking-elapsed");
        if (!es) { es = document.createElement("span"); es.className = "msg-thinking-elapsed"; phaseEl.appendChild(es); }
        es.textContent = elapsed + "s";
      }
    }, 1000);
  }

  // PHASE: Connecting
  setThinkingPhase(typingNode, 'connecting');
  startElapsedTimer();

  const controller = new AbortController();
  setAbortController(controller);

  const body = {
    chat_id: getActiveChatId(),
    model: model.id,
    messages: getMessages().map(({ role, content }) => ({ role, content })),
    file_ids: fileIds,
    temperature: getTemperature(),
    max_tokens: parseInt(getMaxTokens(), 10),
    reasoning_effort: getReasoningEffort() === 'none' ? null : getReasoningEffort(),
    regenerate,
    web_search: getWebSearchEnabled(),
  };

  let collected = '';
 let reasoningContent = '';
 let sawFirstToken = false;
 let hasStartedWriting = false;
 let newChatId = null;
 let streamError = null;
 let responseMessageId = null;
 let responseRequestId = null; // Request correlation ID (Phase 2)
 let aborted = false;
 let streamStarted = false;
  // Phase 4: Track tool calls, citations, artifacts for message persistence
  let toolCalls = [];
  let citations = [];
  let artifacts = [];
 
 try {
    const stream = await streamChatCompletion(body, controller.signal);
    streamStarted = true;

    // PHASE: Thinking — stream connected, waiting for first token
    setThinkingPhase(typingNode, 'thinking');

    const responseController = createResponseController({
      messageStart: (event) => {
        responseMessageId = event.message_id || null;
        // Capture request_id for correlation (Phase 2)
        if (event.request_id) {
          responseRequestId = event.request_id;
        }
      },
      textDelta: (text) => {
        if (!sawFirstToken) {
          sawFirstToken = true;
          const metaEl = typingNode.querySelector('.msg-meta');
          if (metaEl) metaEl.insertAdjacentHTML('beforeend', `<span class="msg-time">${nowTime()}</span>`);
          const indicator = typingNode.querySelector('.typing-indicator');
          if (indicator) indicator.outerHTML = '';
          // Remove aria-busy when first token arrives
          const responseEl = typingNode.querySelector('.assistant-response');
          if (responseEl) responseEl.removeAttribute('aria-busy');
        }

        // PHASE: Writing — first visible content token arrived
        if (!hasStartedWriting) {
          hasStartedWriting = true;
          setThinkingPhase(typingNode, 'writing');
        }

        collected += text;
        const responseEl = typingNode.querySelector('.assistant-response');
        if (responseEl) {
          // Use streaming markdown renderer for visually stable incremental updates
          responseEl.innerHTML = renderMarkdownStream(collected) + '<span class="stream-cursor"></span>';
        }
        scrollToBottomIfNearBottom();
      },
      reasoningDelta: (text) => {
        reasoningContent += text;
        showReasoningInNode(typingNode, reasoningContent);
      },
      toolStart: (event) => {
        const toolId = event.metadata?.tool_id;
        const toolName = event.content || 'tool';
        showToolCallInNode(typingNode, {
          id: toolId,
          name: toolName,
          arguments: '',
          status: 'starting'
        });
        // Track for message persistence
        toolCalls.push({ id: toolId, name: toolName, arguments: '', status: 'starting' });
      },
      toolInputDelta: ({ toolId, content }) => {
        const toolEl = typingNode.querySelector(`[data-tool-id="${toolId}"]`);
        if (toolEl) {
          const argsEl = toolEl.querySelector('.tool-call-args code');
          if (argsEl) argsEl.textContent += content;
        }
        // Update tracked tool call arguments
        const tc = toolCalls.find(t => t.id === toolId);
        if (tc) tc.arguments += content;
      },
      toolEnd: (event) => {
        // Status will be updated when tool_result arrives
      },
      toolResult: (event) => {
        const toolId = event.metadata?.tool_id;
        showToolCallInNode(typingNode, {
          id: toolId,
          result: event.content,
          status: 'completed'
        });
        // Update tracked tool call with result
        const tc = toolCalls.find(t => t.id === toolId);
        if (tc) {
          tc.result = event.content;
          tc.status = 'completed';
        }
      },
      citation: (event) => {
        const citation = event.metadata?.citation || JSON.parse(event.content);
        showCitationInNode(typingNode, citation);
        // Track for message persistence
        citations.push(citation);
      },
      artifactStart: (event) => {
        const artifact = event.metadata?.artifact || JSON.parse(event.content);
        showArtifactInNode(typingNode, artifact);
       // Track for message persistence
       artifacts.push(artifact);
     },
     artifactEnd: (event) => {
       // Finalize artifact if needed
     },

     artifactDelta: (event) => {
       const artifact = event.metadata?.artifact || JSON.parse(event.content);
       if (artifact.id && artifact.content !== undefined) {
          const artifactEl = typingNode.querySelector(`[data-artifact-id="${artifact.id}"]`);
          if (artifactEl) {
            const contentEl = artifactEl.querySelector('.artifact-content');
            if (contentEl) {
              if (artifact.mime?.startsWith('text/') || artifact.type === 'code') {
                contentEl.innerHTML = '<pre><code>' + escapeHtml(artifact.content) + '</code></pre>';
                import('../../shared/markdown.js').then(mod => { mod.enhanceCodeBlocks(contentEl); }).catch(() => {});
              } else if (artifact.mime?.startsWith('image/')) {
                contentEl.innerHTML = '<img src="' + escapeHtml(artifact.content) + '" alt="' + escapeHtml(artifact.title) + '" loading="lazy">';
              } else {
                contentEl.textContent = artifact.content;
              }
            }
          }
        }
        const idx = artifacts.findIndex(a => a.id === artifact.id);
        if (idx >= 0) artifacts[idx] = artifact;
      },
      clarification: (event) => {
        // Phase 2: pre-response clarification card. Replaces the typing
        // indicator — no provider generation happened for this turn.
        const options = event.metadata?.options || [];
        const promptText = event.content || 'Which did you mean?';
        const indicatorEl = typingNode.querySelector('.typing-indicator');
        if (indicatorEl) indicatorEl.outerHTML = '';
        const responseEl = typingNode.querySelector('.assistant-response');
        if (responseEl) responseEl.removeAttribute('aria-busy');
        setThinkingPhase(typingNode, 'done');
        if (_thinkTimer) { clearInterval(_thinkTimer); _thinkTimer = null; }
        const card = document.createElement('div');
        card.className = 'clarification-card';
        card.innerHTML = `
          <p class="clarify-prompt">${escapeHtml(promptText)}</p>
          <div class="clarify-options">
            ${options.map(opt => `<button type="button" class="clarify-btn" data-text="${escapeHtml(opt)}">${escapeHtml(opt)}</button>`).join('')}
          </div>`;
        responseEl?.replaceWith(card);
        // Option click => re-send that interpretation as a brand-new user turn.
        card.querySelectorAll('.clarify-btn').forEach((btn) => {
          btn.addEventListener('click', () => {
            const text = btn.dataset.text;
            if (!text || getIsGenerating()) return;
            card.querySelectorAll('.clarify-btn').forEach((b) => (b.disabled = true));
            const userMsg = { role: 'user', content: text, created_at: new Date().toISOString() };
            setMessages([...getMessages(), userMsg]);
            elements.messages?.appendChild(buildMessageNode(userMsg));
            setLastUserText(text);
            scrollToBottom(true);
            runGeneration({ content: text, fileIds: [], regenerate: false });
          });
        });
      },
      error: (err) => {
        streamError = err || { category: 'unknown', message: 'Provider request failed' };
      },
      unknown: (event) => {
        if (location.hostname === 'localhost' || location.hostname === '127.0.0.1') {
          console.debug('Ignoring unsupported response_event:', event.type, event);
        }
      },
      warning: (message) => {
        if (location.hostname === 'localhost' || location.hostname === '127.0.0.1') console.warn(message);
      },
    });

    for await (const { event, data } of parseSSE(stream)) {
      if (event === 'error') {
        streamError = data;
        continue;
      }
      if (event === 'chat_id') {
        newChatId = data;
        continue;
      }
      responseController.handleSSE({ event, data });
    }
    if (responseController.sawCanonical && !responseController.terminal) {
      streamError = {
        category: 'stream_error',
        message: 'The provider response ended before a terminal event was received.',
        retryable: true,
      };
    }
  } catch (err) {
    if (err.name === 'AbortError') {
      streamError = null;
      aborted = true;
    } else if (err instanceof ApiError) {
      streamError = { category: 'network_error', message: err.message, retryable: true };
    } else {
      streamError = { category: 'unknown', message: err.message, retryable: false };
    }
  }

  try {
    if (streamError) {
      typingNode.remove();
      elements.errorState?.classList.remove('hidden');
      const providerLabel = info.label || model.provider || 'Provider';
      const modelName = model.name || 'Unknown model';
      elements.errorState.querySelector('strong').textContent = `${providerLabel} — ${modelName} returned an error`;

      const streamErrorMessage = streamError.message || String(streamError);
      let guidance = streamErrorMessage;
      const errLow = streamErrorMessage.toLowerCase();
      const errorCategory = streamError.category || 'unknown';
      if (errorCategory === 'model_not_found' || errLow.includes('not available') || errLow.includes('model not found') || errLow.includes('does not exist') || errLow.includes('subscription')) {
        guidance = `The model "${modelName}" is not available on ${providerLabel}. It may require a different subscription or have been deprecated. Try selecting a different model.`;
      } else if (errorCategory === 'authentication_error' || errLow.includes('invalid') || errLow.includes('expired') || errLow.includes('authentication') || errLow.includes('unauthorized') || errLow.includes('401') || errLow.includes('no api key')) {
        guidance = `Your API key for ${providerLabel} appears to be invalid or missing. Open Settings → add or update your ${providerLabel} key.`;
      } else if (['rate_limit', 'quota_exceeded'].includes(errorCategory) || errLow.includes('rate') || errLow.includes('429') || errLow.includes('quota')) {
        guidance = `${providerLabel} rate limit or quota exceeded. Wait a moment and retry, or check your ${providerLabel} plan for usage limits.`;
      } else if (errorCategory === 'timeout' || errLow.includes('timeout') || errLow.includes('timed out')) {
        guidance = `${providerLabel} took too long to respond. Try a smaller model or reduce the max tokens setting.`;
      } else if (errorCategory === 'context_length' || errLow.includes('context') || errLow.includes('length') || errLow.includes('token')) {
        guidance = `The conversation is too long for ${modelName}. Start a new chat or reduce the message history.`;
      }
      elements.errorState.querySelector('p').textContent = guidance;
      elements.errorState.querySelector('.error-detail').textContent = streamErrorMessage;

      // Add settings link in error
      const btnWrapper = elements.errorState.querySelector('.error-btns');
      if (btnWrapper && !btnWrapper.querySelector('.error-settings-link')) {
        const link = document.createElement('button');
        link.className = 'btn-secondary error-settings-link';
        link.textContent = 'Open Settings';
        link.addEventListener('click', () => {
          import('../../features/settings/settings.js').then(m => m.openSettings());
        });
        btnWrapper.appendChild(link);
      }
      scrollToBottom(true);

      if (errLow.includes('not available') || errLow.includes('model not found') || errLow.includes('does not exist')) {
        // handled by models module
      }
    } else if (aborted) {
      // Aborted (Stop pressed or chat switched): preserve partial response if content was generated
      if (collected && sawFirstToken) {
        // Save chat ID on success
        if (newChatId && !getActiveChatId()) {
          setActiveChatId(newChatId);
        }
        // Reload chat list
        const sidebarModule = await import('../sidebar/sidebar.js');
        sidebarModule.loadChatList();
        const elapsedMs = Date.now() - genStartedAt;
        const elapsedSec = (elapsedMs / 1000).toFixed(1);
        const finalMsg = { id: responseMessageId, role: 'assistant', content: collected, model: model.id, created_at: new Date().toISOString(), response_time: parseFloat(elapsedSec), tool_calls: toolCalls, citations: citations, artifacts: artifacts };
        setMessages([...getMessages(), finalMsg]);
        // PHASE: Done — show completion time briefly, then replace with final message
        setThinkingPhase(typingNode, 'done', elapsedSec);
        // Small delay so "Done — Xs" is visible before replace
        await new Promise((r) => setTimeout(r, 600));
        const finalNode = buildMessageNode(finalMsg);
        typingNode.replaceWith(finalNode);
        // Final render pass: ensure complete markdown with syntax highlighting
        await finalizeMarkdownRender(finalNode, collected);
        showToast({ type: 'info', title: 'Generation stopped — partial response saved' });
      } else {
        // No content generated, just remove the typing indicator
        typingNode.remove();
        showToast({ type: 'info', title: 'Generation stopped' });
      }
    } else if (collected) {
      // Save chat ID on success
      if (newChatId && !getActiveChatId()) {
        setActiveChatId(newChatId);
      }
      // Reload chat list
      const sidebarModule = await import('../sidebar/sidebar.js');
      sidebarModule.loadChatList();
      const elapsedMs = Date.now() - genStartedAt;
      const elapsedSec = (elapsedMs / 1000).toFixed(1);
      const finalMsg = { id: responseMessageId, role: 'assistant', content: collected, model: model.id, created_at: new Date().toISOString(), response_time: parseFloat(elapsedSec), tool_calls: toolCalls, citations: citations, artifacts: artifacts };
      setMessages([...getMessages(), finalMsg]);
      // PHASE: Done — show completion time briefly, then replace with final message
      setThinkingPhase(typingNode, 'done', elapsedSec);
      // Small delay so "Done — Xs" is visible before replace
      await new Promise((r) => setTimeout(r, 600));
      const finalNode = buildMessageNode(finalMsg);
      typingNode.replaceWith(finalNode);
      // Final render pass: ensure complete markdown with syntax highlighting
      await finalizeMarkdownRender(finalNode, collected);
    } else if (!sawFirstToken) {
      // Aborted before any token
      typingNode.remove();
      showToast({ type: 'info', title: 'Generation stopped' });
    }
  } catch (_err) {
    showToast({ type: 'error', title: 'Unexpected error', message: _err?.message || String(_err) });
  }

  setIsGenerating(false);
  setAbortController(null);
  if (_thinkTimer) { clearInterval(_thinkTimer); _thinkTimer = null; }

  // Enforce minimum stop-button visibility
  const elapsed = Date.now() - genStartedAt;
  if (elapsed < MIN_STOP_VISIBLE_MS) {
    await new Promise((r) => setTimeout(r, MIN_STOP_VISIBLE_MS - elapsed));
  }
  await new Promise((r) => setTimeout(r, 16));

  if (genId === _genCounter) {
    setSendButtonState(false);
  }
  scrollToBottomIfNearBottom();
}

/**
 * Auto-resize textarea.
 */
export function autoResizeTextarea() {
  const ta = elements.messageInput;
  if (!ta) return;
  ta.style.height = 'auto';
  ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
}

/**
 * Stop generation by aborting the current request.
 */
export function stopGeneration() {
  const ac = getAbortController();
  if (ac) ac.abort();
}

/**
 * Start a new chat.
 */
export async function startNewChat() {
  if (getIsGenerating() && getAbortController()) {
    getAbortController().abort();
  }
  resetChatState();
  setSendButtonState(false);
  const sidebarModule = await import('../sidebar/sidebar.js');
  sidebarModule.renderChatHistory(document.getElementById('searchChats')?.value || '');
  elements.errorState?.classList.add('hidden');
  elements.backendDownState?.classList.add('hidden');
  elements.skeletonWrap?.classList.add('hidden');
  elements.messages?.classList.remove('hidden');
  elements.messages.innerHTML = '';
  elements.welcomeScreen?.classList.remove('hidden');
  elements.messageInput.value = '';
  autoResizeTextarea();
  elements.messageInput?.focus();
  _followStream = true;
  updateJumpBtn();
}

/**
 * Initialize chat event listeners.
 */
export function initChatEvents() {
  initElements();

  // Smart auto-scroll (§27): "↓ Jump to latest" resumes following the stream.
  // Guard against re-init stacking duplicate passive listeners.
  elements.scrollBottomBtn?.addEventListener('click', resumeFollow);
  elements.chatScroll?.removeEventListener('scroll', onChatScroll);
  elements.chatScroll?.addEventListener('scroll', onChatScroll, { passive: true });

  // Send button — always sends a message.
  elements.sendBtn?.addEventListener('click', () => {
    handleSend();
  });

  // Stop button — always aborts the current generation.
  elements.stopBtn?.addEventListener('click', stopGeneration);
  elements.retryBtn?.addEventListener('click', () => {
    elements.errorState?.classList.add('hidden');
    if (!getSelectedModel()) {
      showToast({ type: 'info', title: 'Model required', message: 'Select a model before retrying.' });
      return;
    }
    if (getLastUserText()) runGeneration({ content: getLastUserText(), fileIds: [], regenerate: true });
  });
  elements.attachBtn?.addEventListener('click', () => elements.fileInput?.click());
  elements.fileInput?.addEventListener('change', (e) => { handleFileSelection(e.target.files); e.target.value = ''; });

  elements.messageInput?.addEventListener('input', autoResizeTextarea);
  elements.messageInput?.addEventListener('keydown', (e) => {
    // Ctrl/Cmd+Enter always sends
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); handleSend(); }
    // Enter without Shift sends on desktop (> 900px)
    else if (e.key === 'Enter' && !e.shiftKey && window.innerWidth > 900) { e.preventDefault(); handleSend(); }
    // On mobile/tablet, Shift+Enter sends, plain Enter creates newlines
    else if (e.key === 'Enter' && e.shiftKey && window.innerWidth <= 900) { e.preventDefault(); handleSend(); }
  });

  // Web search toggle
  elements.webSearchToggle?.addEventListener('click', () => {
    const enabled = !getWebSearchEnabled();
    setWebSearchEnabled(enabled);
    elements.webSearchToggle.classList.toggle('active', enabled);
    elements.webSearchToggle.setAttribute('aria-pressed', String(enabled));
  });

  // Composer drag-drop
  const composerEl = document.getElementById('composer');
  ['dragover', 'dragenter'].forEach((evt) => composerEl?.addEventListener(evt, (e) => { e.preventDefault(); composerEl.style.borderColor = 'var(--accent)'; }));
  ['dragleave', 'drop'].forEach((evt) => composerEl?.addEventListener(evt, (e) => {
    e.preventDefault(); composerEl.style.borderColor = '';
    if (evt === 'drop' && e.dataTransfer.files.length) handleFileSelection(e.dataTransfer.files);
  }));

  // Suggestion cards
  document.querySelectorAll('.suggestion-card').forEach((card) => {
    card.addEventListener('click', () => {
      elements.messageInput.value = card.dataset.prompt;
      autoResizeTextarea();
      handleSend();
    });
  });


  // Token counter - live estimate
  var tokenCountEl = document.getElementById('tokenCounter');
  var msgInput = document.getElementById('messageInput');
  function updateTokenEstimate() {
    if (!tokenCountEl || !msgInput) return;
    var text = msgInput.value || '';
    var tokens = Math.ceil(text.length / 4);
    var maxTokens = 8192;
    var pct = tokens / maxTokens;
    tokenCountEl.textContent = tokens.toLocaleString() + ' / ' + maxTokens.toLocaleString() + ' tokens';
    tokenCountEl.className = 'token-counter';
    if (pct > 0.9) tokenCountEl.classList.add('danger');
    else if (pct > 0.7) tokenCountEl.classList.add('warning');
  }
  msgInput?.addEventListener('input', updateTokenEstimate);
  updateTokenEstimate();

}
