/**
 * Sidebar module - Chat history, new chat, sidebar collapse, mobile toggle.
 * Enhanced with pin, rename, and context menu.
 */

import { getApiBaseUrl, apiFetch, apiDelete } from '../../shared/http.js';
import { showToast } from '../../shared/toast.js';
import { escapeHtml, bucketFor } from '../../shared/utils.js';
import { CHAT_BUCKETS } from '../../shared/constants.js';
import {
  getChats, setChats, getActiveChatId, setActiveChatId,
  getMessages, setMessages, getSelectedModel, selectModel,
  getAbortController, getModels, getSidebarCollapsed, setSidebarCollapsed
} from '../../core/state.js';
import { closeProfilePopup } from '../auth/auth.js';
console.log('[Module] sidebar.js loaded');

// Dynamic imports to break circular dependency with chat.js
let _chatModule = null;
async function getChatModule() {
  if (!_chatModule) {
    _chatModule = await import('../chat/chat.js');
  }
  return _chatModule;
}

let elements = {};
let _contextMenuEl = null;

// Pinned chat IDs persisted in localStorage
function getPinnedIds() {
  try { return JSON.parse(localStorage.getItem('sangam-pinned-chats') || '[]'); } catch { return []; }
}
function setPinnedIds(ids) {
  localStorage.setItem('sangam-pinned-chats', JSON.stringify(ids));
}

export function initElements() {
  elements = {
    sidebar: $('#sidebar'),
    sidebarScrim: $('#sidebarScrim'),
    collapseSidebar: $('#collapseSidebar'),
    expandSidebar: $('#expandSidebar'),
    mobileSidebarToggle: $('#mobileSidebarToggle'),
    newChatBtn: $('#newChatBtn'),
    mobileNewChat: $('#mobileNewChat'),
    searchChats: $('#searchChats'),
    chatHistory: $('#chatHistory'),
  };
}

export function openMobileSidebar() {
  elements.sidebar?.classList.add('mobile-open');
  elements.sidebarScrim?.classList.add('show');
}

export function closeMobileSidebar() {
  elements.sidebar?.classList.remove('mobile-open');
  elements.sidebarScrim?.classList.remove('show');
}

export function toggleSidebarCollapse() {
  const next = !getSidebarCollapsed();
  setSidebarCollapsed(next);
  elements.sidebar?.classList.toggle('collapsed', next);
  elements.expandSidebar?.classList.toggle('hidden', !next);
  elements.collapseSidebar?.setAttribute('aria-expanded', String(!next));
  elements.collapseSidebar?.setAttribute('aria-label', next ? 'Expand navigation rail' : 'Collapse sidebar');
  elements.collapseSidebar?.setAttribute('title', next ? 'Expand navigation rail' : 'Collapse sidebar');
  elements.expandSidebar?.setAttribute('aria-expanded', String(next));
  elements.expandSidebar?.classList.toggle('rotated', next);
  elements.collapseSidebar?.classList.toggle('rotated', !next);
}

export async function loadChatList() {
  try {
    const res = await apiFetch('/chats');
    const chats = await res.json();
    setChats(chats);
    renderChatHistory(elements.searchChats?.value || '');
  } catch (err) {
    showToast({ type: 'error', title: 'Could not load chat history', message: err.message });
  }
}

function togglePin(chatId) {
  const pinned = getPinnedIds();
  const idx = pinned.indexOf(chatId);
  if (idx > -1) pinned.splice(idx, 1);
  else pinned.push(chatId);
  setPinnedIds(pinned);
  renderChatHistory(elements.searchChats?.value || '');
}

async function renameChat(chatId, newTitle) {
  const t = newTitle.trim();
  if (!t || t.length > 200) return;
  try {
    await apiFetch('/chats/' + chatId, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: t }),
    });
    const chats = getChats().map(function(c) { return c.id === chatId ? { ...c, title: t } : c; });
    setChats(chats);
    renderChatHistory(elements.searchChats?.value || '');
    showToast({ type: 'success', message: 'Chat renamed.' });
  } catch (err) {
    showToast({ type: 'error', title: 'Rename failed', message: err.message });
  }
}

function showContextMenu(chatId, x, y) {
  closeContextMenu();
  if (!_contextMenuEl) {
    _contextMenuEl = document.createElement('div');
    _contextMenuEl.className = 'chat-context-menu';
    document.body.appendChild(_contextMenuEl);
  }
  var pinned = getPinnedIds();
  var isPinned = pinned.indexOf(chatId) > -1;
  _contextMenuEl.innerHTML = [
    '<button data-action="rename"><i class="fa-solid fa-pen"></i> Rename</button>',
    '<button data-action="pin"><i class="fa-solid fa-thumbtack"></i> ' + (isPinned ? 'Unpin' : 'Pin') + '</button>',
    '<div class="ctx-menu-divider"></div>',
    '<button data-action="delete" class="ctx-menu-danger"><i class="fa-solid fa-trash"></i> Delete</button>'
  ].join('');
  _contextMenuEl.style.left = Math.min(x, window.innerWidth - 180) + 'px';
  _contextMenuEl.style.top = Math.min(y, window.innerHeight - 160) + 'px';
  _contextMenuEl.classList.add('show');

  _contextMenuEl.querySelectorAll('button').forEach(function(btn) {
    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      var action = btn.dataset.action;
      closeContextMenu();
      if (action === 'rename') startInlineRename(chatId);
      else if (action === 'pin') togglePin(chatId);
      else if (action === 'delete') deleteChat(chatId);
    });
  });

  setTimeout(function() {
    document.addEventListener('click', closeContextMenu, { once: true });
  }, 0);
}

function closeContextMenu() {
  if (_contextMenuEl) _contextMenuEl.classList.remove('show');
}

function startInlineRename(chatId) {
  var item = elements.chatHistory.querySelector('[data-chat-id="' + chatId + '"]');
  if (!item) return;
  var span = item.querySelector('span');
  var currentTitle = span ? span.textContent : '';
  var input = document.createElement('input');
  input.type = 'text';
  input.className = 'chat-rename-input';
  input.value = currentTitle;
  input.maxLength = 200;
  if (span) span.replaceWith(input);
  input.focus();
  input.select();

  function finish(save) {
    var val = input.value.trim();
    if (save && val && val !== currentTitle) {
      renameChat(chatId, val);
    }
    var restoredSpan = document.createElement('span');
    restoredSpan.textContent = save && val ? val : currentTitle;
    input.replaceWith(restoredSpan);
  }

  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
    if (e.key === 'Escape') { e.preventDefault(); finish(false); }
  });
  input.addEventListener('blur', function() { finish(true); });
}

export function renderChatHistory(filter) {
  if (filter === undefined) filter = '';
  var q = filter.trim().toLowerCase();
  var container = elements.chatHistory;
  if (!container) return;

  container.innerHTML = '';
  var pinnedIds = getPinnedIds();
  var allChats = getChats();
  var pinnedChats = allChats.filter(function(c) { return pinnedIds.indexOf(c.id) > -1; });
  var unpinnedChats = allChats.filter(function(c) { return pinnedIds.indexOf(c.id) === -1; });

  if (pinnedChats.length && !q) {
    var pinLabel = document.createElement('div');
    pinLabel.className = 'chat-history-label';
    pinLabel.innerHTML = '<i class="fa-solid fa-thumbtack" style="font-size:9px;margin-right:4px"></i> Pinned';
    container.appendChild(pinLabel);
    pinnedChats.forEach(function(chat) { container.appendChild(buildChatItem(chat, true)); });
  }

  var shownAny = false;
  var buckets = CHAT_BUCKETS;
  buckets.forEach(function(bucket) {
    var items = unpinnedChats.filter(function(c) {
      return bucketFor(c.updated_at) === bucket && c.title.toLowerCase().indexOf(q) > -1;
    });
    if (!items.length) return;
    shownAny = true;
    var label = document.createElement('div');
    label.className = 'chat-history-label';
    label.textContent = bucket;
    container.appendChild(label);
    items.forEach(function(chat) { container.appendChild(buildChatItem(chat, false)); });
  });

  if (!shownAny && !pinnedChats.length) {
    var empty = document.createElement('div');
    empty.className = 'no-results';
    empty.textContent = allChats.length ? 'No chats match "' + filter + '"' : 'No conversations yet - start one below.';
    container.appendChild(empty);
  }
}

function buildChatItem(chat, isPinned) {
  var item = document.createElement('div');
  item.className = 'chat-item' + (chat.id === getActiveChatId() ? ' active' : '') + (isPinned ? ' pinned' : '');
  item.dataset.chatId = chat.id;
  item.setAttribute('role', 'button');
  item.setAttribute('tabindex', '0');
  item.setAttribute('title', chat.title);
  item.setAttribute('aria-label', 'Open chat: ' + chat.title);

  var iconClass = isPinned ? 'fa-solid fa-thumbtack' : 'fa-regular fa-message';
  item.innerHTML = [
    '<i class="' + iconClass + ' chat-icon"></i>',
    '<span>' + escapeHtml(chat.title) + '</span>',
    '<span class="chat-item-pin"><i class="fa-solid fa-thumbtack"></i></span>',
    '<button class="chat-item-menu-btn" title="More actions" aria-label="More actions"><i class="fa-solid fa-ellipsis"></i></button>'
  ].join('');

  var openHandler = function(e) {
    if (e.type === 'keydown' && e.key !== 'Enter' && e.key !== ' ') return;
    if (e.target.closest('.chat-item-menu-btn')) {
      e.stopPropagation();
      e.preventDefault();
      var rect = e.target.closest('.chat-item-menu-btn').getBoundingClientRect();
      showContextMenu(chat.id, rect.right - 160, rect.bottom + 4);
      return;
    }
    e.preventDefault();
    openChat(chat.id);
    if (window.innerWidth <= 900) closeMobileSidebar();
  };
  item.addEventListener('click', openHandler);
  item.addEventListener('keydown', openHandler);

  item.addEventListener('dblclick', function(e) {
    if (e.target.closest('.chat-item-menu-btn, .chat-item-pin')) return;
    startInlineRename(chat.id);
  });

  return item;
}

export async function openChat(chatId) {
  closeProfilePopup();
  setActiveChatId(chatId);
  renderChatHistory(elements.searchChats ? elements.searchChats.value : '');

  var welcomeEl = document.getElementById('welcomeScreen');
  var messagesEl = document.getElementById('messages');
  var errorEl = document.getElementById('errorState');
  var skeletonEl = document.getElementById('skeletonWrap');
  if (welcomeEl) welcomeEl.classList.add('hidden');
  if (messagesEl) messagesEl.classList.add('hidden');
  if (errorEl) errorEl.classList.add('hidden');
  if (skeletonEl) skeletonEl.classList.remove('hidden');

  try {
    var res = await apiFetch('/chats/' + chatId);
    var chat = await res.json();
    var allModels = getModels();
    if (allModels) {
      var model = allModels.find(function(m) { return m.id === chat.model; });
      if (model) selectModel(model, { silent: true });
    }
    setMessages(chat.messages);
    if (skeletonEl) skeletonEl.classList.add('hidden');
    if (messagesEl) messagesEl.classList.remove('hidden');
    await callChatModule('renderMessages');
    await callChatModule('scrollToBottom', false);
  } catch (err) {
    if (skeletonEl) skeletonEl.classList.add('hidden');
    if (errorEl) errorEl.classList.remove('hidden');
    var strongEl = errorEl ? errorEl.querySelector('strong') : null;
    var pEl = errorEl ? errorEl.querySelector('p') : null;
    if (strongEl) strongEl.textContent = 'Could not load this conversation.';
    if (pEl) pEl.textContent = err.message;
  }
}

var pendingDeleteChatId = null;

// Helper functions to access chat module exports
async function callChatModule(fnName, ...args) {
  const mod = await getChatModule();
  return mod[fnName](...args);
}

function showConfirmDelete(chatId) {
  pendingDeleteChatId = chatId;
  var titleEl = document.getElementById('confirmTitle');
  var msgEl = document.getElementById('confirmMessage');
  var overlayEl = document.getElementById('confirmOverlay');
  if (titleEl) titleEl.textContent = 'Delete chat?';
  if (msgEl) msgEl.textContent = 'This conversation will be permanently removed.';
  if (overlayEl) overlayEl.classList.remove('hidden');
  updateBodyScrollLock();
  setTimeout(function() { var el = document.getElementById('confirmCancel'); if (el) el.focus(); }, 50);
}

function hideConfirm() {
  var overlayEl = document.getElementById('confirmOverlay');
  if (overlayEl) overlayEl.classList.add('hidden');
  pendingDeleteChatId = null;
  updateBodyScrollLock();
}

export function deleteChat(chatId) {
  showConfirmDelete(chatId);
}

export function initSidebar() {
  initElements();

  elements.newChatBtn?.addEventListener('click', function() { closeProfilePopup(); callChatModule('startNewChat'); });
  elements.mobileNewChat?.addEventListener('click', function() { closeProfilePopup(); callChatModule('startNewChat'); closeMobileSidebar(); });
  elements.collapseSidebar?.addEventListener('click', toggleSidebarCollapse);
  elements.expandSidebar?.addEventListener('click', toggleSidebarCollapse);
  var collapsed = getSidebarCollapsed();
  if (elements.sidebar) elements.sidebar.classList.toggle('collapsed', collapsed);
  if (elements.expandSidebar) elements.expandSidebar.classList.toggle('hidden', !collapsed);
  if (elements.collapseSidebar) elements.collapseSidebar.classList.toggle('hidden', collapsed);
  if (elements.collapseSidebar) {
    elements.collapseSidebar.setAttribute('aria-expanded', String(!collapsed));
    elements.collapseSidebar.setAttribute('aria-label', collapsed ? 'Expand navigation rail' : 'Collapse sidebar');
  }
  elements.mobileSidebarToggle?.addEventListener('click', openMobileSidebar);
  elements.sidebarScrim?.addEventListener('click', closeMobileSidebar);
  elements.searchChats?.addEventListener('input', function() { renderChatHistory(elements.searchChats.value); });

  document.getElementById('confirmCancel')?.addEventListener('click', hideConfirm);
  document.getElementById('confirmOverlay')?.addEventListener('click', function(e) {
    if (e.target === document.getElementById('confirmOverlay')) hideConfirm();
  });
  document.addEventListener('keydown', function(e) {
    var overlay = document.getElementById('confirmOverlay');
    if (e.key === 'Escape' && overlay && !overlay.classList.contains('hidden')) hideConfirm();
    if (e.key === 'Escape') closeContextMenu();
  });
  document.getElementById('confirmDelete')?.addEventListener('click', async function() {
    var chatId = pendingDeleteChatId;
    hideConfirm();
    if (!chatId) return;
    try {
      await apiFetch('/chats/' + chatId, { method: 'DELETE' });
      var pinned = getPinnedIds().filter(function(id) { return id !== chatId; });
      setPinnedIds(pinned);
      setChats(getChats().filter(function(c) { return c.id !== chatId; }));
      if (getActiveChatId() === chatId) await callChatModule('startNewChat');
      renderChatHistory(elements.searchChats ? elements.searchChats.value : '');
      showToast({ type: 'success', message: 'Chat deleted.' });
    } catch (err) {
      showToast({ type: 'error', title: 'Could not delete chat', message: err.message });
    }
  });
}

export function updateBodyScrollLock() {
  var anyOpen = !document.getElementById('settingsOverlay')?.classList.contains('hidden') ||
                !document.getElementById('confirmOverlay')?.classList.contains('hidden') ||
                !document.getElementById('skillsOverlay')?.classList.contains('hidden') ||
                document.getElementById('profilePopup')?.classList.contains('show');
  document.body.style.overflow = anyOpen ? 'hidden' : '';
}
