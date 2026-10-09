/**
 * Chat feature - Message handling, streaming, and chat management.
 */

import { getApiBaseUrl, apiFetch, apiPost, streamChatCompletion, parseSSE, ApiError } from '../../shared/http.js';
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
  getAgentModeEnabled, setAgentModeEnabled,
  getThinkingDisplay,
  getChats, setChats,
  resetChatState
} from '../../core/state.js';
import { FILE_ICON_MAP } from '../../shared/constants.js';
import {
  buildMessageNode,
  getProviderInfo,
  setThinkingPhase,
  showReasoningInNode,
  showToolCallInNode,
  showCitationInNode,
  showArtifactInNode,
  showMediaInNode,
  bindChatActions,
} from './message_view.js';
import {
  initAutoscroll,
  nearBottomDist,
  onChatScroll,
  resumeFollow,
  scrollToBottom as coreScrollToBottom,
  scrollToBottomIfNearBottom,
  updateJumpBtn,
  isFollowingStream,
  setFollowingStream,
} from './autoscroll.js';

// Re-exported for app.js, which treats chat.js as the chat feature facade.
export { buildMessageNode };
console.log('[Module] chat.js loaded');


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
 * (Implementation lives in message_view.js: setThinkingPhase et al.)
 */
export function renderMessages() {
  const messages = getMessages();
  const container = elements.messages;
  if (!container) return;

  container.innerHTML = '';
  messages.forEach((m) => container.appendChild(buildMessageNode(m)));

  // Full re-render resets auto-scroll to "following latest".
  setFollowingStream(true);
  updateJumpBtn();
}

/**
 * Render attached-file chips above the composer.
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
    const thumb = f.imageUrl
      ? `<img class="file-chip-thumb" src="${escapeHtml(f.imageUrl)}" alt="">`
      : `<span class="file-chip-icon" style="background:${info.color}"><i class="fa-solid ${f.uploading ? 'fa-spinner fa-spin' : info.icon}"></i></span>`;
    chip.innerHTML = `
      ${thumb}
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
export async function handleSend() {
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

  // New send stops any voice I/O (speech or dictation)
  document.dispatchEvent(new CustomEvent('sangam:before-send'));

  elements.welcomeScreen?.classList.add('hidden');

  const agentMode = getAgentModeEnabled();
  const userMsg = { role: 'user', content: text || '(Sent with attached files)', created_at: new Date().toISOString() };
  setMessages([...getMessages(), userMsg]);
  elements.messages?.appendChild(buildMessageNode(userMsg));
  setLastUserText(userMsg.content);

  elements.messageInput.value = '';
  autoResizeTextarea();

  const fileIds = files.map((f) => f.id).filter(Boolean);
  setAttachedFiles([]);
  renderFileChips();
  setFollowingStream(true); // a new send re-engages auto-following
  updateJumpBtn();
  scrollToBottom(true);

  if (agentMode) {
    setIsGenerating(true);
    setSendButtonState(true);
    const { runAgentGeneration } = await import('./agent_mode.js');
    await runAgentGeneration({
      content: userMsg.content,
      messagesEl: elements.messages,
      scrollToBottom,
      onDone: async (answer, stopped) => {
        setIsGenerating(false);
        setSendButtonState(false);
        if (answer && !stopped) {
          const asstMsg = { role: 'assistant', content: answer, created_at: new Date().toISOString() };
          setMessages([...getMessages(), asstMsg]);
          // Persist both messages via the append endpoint (create chat first if new)
          try {
            let chatId = getActiveChatId();
            if (!chatId) {
              const created = await (await apiPost('/chats', {
                title: userMsg.content.slice(0, 60) || 'New chat',
                model: getSelectedModel()?.id || '',
              })).json();
              chatId = created.id;
              setActiveChatId(chatId);
              const sidebarModule = await import('../sidebar/sidebar.js');
              sidebarModule.loadChatList?.();
            }
            await apiPost(`/chats/${chatId}/messages`, {
              messages: [
                { role: 'user', content: userMsg.content },
                { role: 'assistant', content: answer },
              ],
            });
          } catch (e) { console.warn('[Agent] persist failed', e); }
        }
      },
    });
    return;
  }

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
      <article class="assistant-response" aria-live="polite" aria-busy="true"><div class="typing-indicator" aria-label="Generating response">thinking<span aria-hidden="true"></span><span aria-hidden="true"></span><span aria-hidden="true"></span></div></article>
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
    media_ids: getAttachedFiles().map((f) => f.mediaId).filter(Boolean),
    temperature: getTemperature(),
    max_tokens: getMaxTokens() === 'auto' ? null : parseInt(getMaxTokens(), 10),
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
  // Foundation: streamed media (image/audio) tracked the same way.
  let media = [];
  let currentMedia = null;
 
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
        showReasoningInNode(typingNode, reasoningContent, { thinkingState: { getThinkingDisplay } });
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

     // Foundation: streamed media attachments (image/audio) for voice + image-gen.
     mediaStart: ({ kind, metadata }) => {
       currentMedia = { id: 'stream-' + Date.now(), kind, filename: metadata?.filename || '', url: null, chunks: '' };
       showMediaInNode(typingNode, currentMedia);
       media.push(currentMedia);
     },
     mediaDelta: ({ content }) => {
       if (currentMedia) {
         currentMedia.chunks += content;
         showMediaInNode(typingNode, { ...currentMedia, delta: content });
       }
     },
     mediaEnd: ({ url, metadata }) => {
       if (currentMedia) {
         if (url) currentMedia.url = url;
         showMediaInNode(typingNode, { ...currentMedia, url: currentMedia.url, finalize: true });
         currentMedia = null;
       }
       void metadata;
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
        const finalMsg = { id: responseMessageId, role: 'assistant', content: collected, model: model.id, created_at: new Date().toISOString(), response_time: parseFloat(elapsedSec), tool_calls: toolCalls, citations: citations, artifacts: artifacts, media: media.map(m => ({ id: m.id, kind: m.kind, filename: m.filename, url: m.url })) };
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
      const finalMsg = { id: responseMessageId, role: 'assistant', content: collected, model: model.id, created_at: new Date().toISOString(), response_time: parseFloat(elapsedSec), tool_calls: toolCalls, citations: citations, artifacts: artifacts, media: media.map(m => ({ id: m.id, kind: m.kind, filename: m.filename, url: m.url })) };
      setMessages([...getMessages(), finalMsg]);
      // PHASE: Done — show completion time briefly, then replace with final message
      setThinkingPhase(typingNode, 'done', elapsedSec);
      // Small delay so "Done — Xs" is visible before replace
      await new Promise((r) => setTimeout(r, 600));
      const finalNode = buildMessageNode(finalMsg);
      typingNode.replaceWith(finalNode);
      // Final render pass: ensure complete markdown with syntax highlighting
      await finalizeMarkdownRender(finalNode, collected);
      // Voice: auto-speak the response when the user enabled it.
      import('../voice/voice.js').then((m) => m.maybeAutoSpeak(collected)).catch(() => {});
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
 * Scroll chat to the bottom (delegates to the autoscroll controller).
 */
export function scrollToBottom(smooth = true) {
  coreScrollToBottom(smooth);
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
  setFollowingStream(true);
  updateJumpBtn();
}

/**
 * Initialize chat event listeners.
 */
export function initChatEvents() {
  initElements();
  initAutoscroll(elements);
  // Break the render -> generate cycle: message_view calls back into this
  // module for regenerate / re-render / generation.
  bindChatActions({ regenerate, rerender: renderMessages, runGeneration });

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

  // Mode/Tools popovers (Phase 2) drive these states now
  document.addEventListener('sangam:mode-changed', (e) => {
    const mode = e.detail?.mode;
    if (mode === 'research' && !getWebSearchEnabled()) setWebSearchEnabled(true);
    if (mode === 'agent' || mode === 'code') {
      showToast({ type: 'info', title: 'Agent mode', message: 'Agent can now use tools (web, files, code).' });
    }
  });
  document.addEventListener('sangam:tools-changed', (e) => {
    const tools = e.detail?.tools || [];
    setWebSearchEnabled(tools.includes('web_search'));
  });

  // Initialize agent mode toggle state
  const agentModeOn = getAgentModeEnabled();
  elements.agentModeToggle?.classList.toggle('active', agentModeOn);
  elements.agentModeToggle?.setAttribute('aria-pressed', String(agentModeOn));

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
