/**
 * Sangam - Universal AI Chat Platform
 * Main entry point - bootstraps all feature modules.
 */

import { initAppState, getMessages, getIsGenerating, getLastUserText, getTemperature, setTemperature, getMaxTokens, setMaxTokens, getReasoningEffort, setReasoningEffort } from './core/state.js';
import { initElements as initChatElements, initChatEvents, handleSend, regenerate, runGeneration, stopGeneration, autoResizeTextarea, scrollToBottom, buildMessageNode, renderMessages, startNewChat as chatStartNewChat } from './features/chat/chat.js';
import { initElements as initModelsElements, loadProvidersAndModels, renderModelList, renderProviderFilters, renderProviderStatusList, renderConnPulse, selectModel, openModelDropdown, closeModelDropdown, initModelSelector } from './features/models/models.js';
import { initElements as initSettingsElements, openSettings, closeSettingsModal, applySettings as settingsApplySettings, loadSettings, syncSettingsUI, initSettings, renderProviderStatusList as settingsRenderProviderStatusList } from './features/settings/settings.js';
import { initElements as initAuthElements, initializeAuth, setStartApplicationCallback, initAuth, logout } from './features/auth/auth.js';
import { init as initSkills, openSkillsModal, closeSkillsModal } from './features/skills/skills.js';
import { initElements as initSidebarElements, initSidebar, openMobileSidebar, closeMobileSidebar, toggleSidebarCollapse, loadChatList as sidebarLoadChatList, renderChatHistory as sidebarRenderChatHistory, openChat as sidebarOpenChat, deleteChat as sidebarDeleteChat } from './features/sidebar/sidebar.js';
import { showToast, initToasts } from './shared/toast.js';
import { getApiBaseUrl } from './shared/http.js';
import { injectMarkdownCSP } from './shared/markdown.js';
import { $, $$ } from './shared/utils.js';

// Global elements that cross module boundaries
let elements = {};

/**
 * Initialize all DOM element references across modules.
 */
function initDOM() {
  // Shared elements
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
    settingsBtn: $('#settingsBtn'),
    settingsOverlay: $('#settingsOverlay'),
    closeSettings: $('#closeSettings'),
    themeOptions: $('#themeOptions'),
    fontSizeSegmented: $('#fontSizeSegmented'),
    chatWidthSegmented: $('#chatWidthSegmented'),
    codeThemeSelect: $('#codeThemeSelect'),
    animationToggle: $('#animationToggle'),
    themeToggle: $('#themeToggle'),
    toastContainer: $('#toastContainer'),
    confirmOverlay: $('#confirmOverlay'),
    confirmTitle: $('#confirmTitle'),
    confirmMessage: $('#confirmMessage'),
    confirmDelete: $('#confirmDelete'),
    confirmCancel: $('#confirmCancel'),
    modelSelector: $('#modelSelector'),
    modelSelectorBtn: $('#modelSelectorBtn'),
    modelDropdown: $('#modelDropdown'),
    modelSearch: $('#modelSearch'),
    modelSearchClear: $('#modelSearchClear'),
    modelList: $('#modelList'),
    modelProviderFilters: $('#modelProviderFilters'),
    connPulse: $('#connPulse'),
    onboardingHint: $('#onboardingHint'),
    profileAvatar: $('#profileAvatar'),
    profileName: $('#profileName'),
    providerStatusList: $('#providerStatusList'),
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
    authOverlay: $('#authOverlay'),
    authLoading: $('#authLoading'),
    authLoadingText: $('#authLoadingText'),
    authLoadingSub: $('#authLoadingSub'),
    authLoadingRetry: $('#authLoadingRetry'),
    authLoadingErrmsg: $('#authLoadingErrmsg'),
    authRetryBtn: $('#authRetryBtn'),
    authForm: $('#authForm'),
    authTitle: $('#authTitle'),
    authDescription: $('#authDescription'),
    authUsername: $('#authUsername'),
    authPassword: $('#authPassword'),
    authConfirmWrap: $('#authConfirmWrap'),
    authConfirmPassword: $('#authConfirmPassword'),
    authError: $('#authError'),
    authSubmit: $('#authSubmit'),
    authNote: $('#authNote'),
    authForgotLink: $('#authForgotLink'),
    authForgotBtn: $('#authForgotBtn'),
    authForgotForm: $('#authForgotForm'),
    authForgotUsername: $('#authForgotUsername'),
    authForgotError: $('#authForgotError'),
    authForgotSubmit: $('#authForgotSubmit'),
    authTokenBox: $('#authTokenBox'),
    authTokenText: $('#authTokenText'),
    authCopyToken: $('#authCopyToken'),
    authContinueReset: $('#authContinueReset'),
    authResetForm: $('#authResetForm'),
    authResetToken: $('#authResetToken'),
    authResetPassword: $('#authResetPassword'),
    authResetConfirm: $('#authResetConfirm'),
    authResetError: $('#authResetError'),
    authResetSuccess: $('#authResetSuccess'),
    authResetSubmit: $('#authResetSubmit'),
    authForgotBack: $('#authForgotBack'),
    authResetBack: $('#authResetBack'),
    skillsOverlay: $('#skillsOverlay'),
    skillsBtn: $('#skillsBtn'),
    closeSkills: $('#closeSkills'),
    shortcutsOverlay: $('#shortcutsOverlay'),
    closeShortcuts: $('#closeShortcuts'),
    backendUrlInput: $('#backendUrlInput'),
    testBackendBtn: $('#testBackendBtn'),
    logoutBtn: $('#logoutBtn'),
    providerKeyManager: $('#providerKeyManager'),
  };

  // Initialize modules with their element references
  initChatElements();
  initModelsElements();
  initSettingsElements();
  initAuthElements();
  initSidebarElements();
}

/**
 * Set up global event listeners that cross modules.
 */
function initGlobalListeners() {
  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    // Ctrl/Cmd+K - New chat
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      chatStartNewChat();
    }
    // Escape - Close modals, dropdowns
    if (e.key === 'Escape') {
      closeModelDropdown();
      closeSettingsModal();
      elements.tempPopover?.classList.add('hidden');
      if (!elements.skillsOverlay?.classList?.contains('hidden')) closeSkillsModal();
    }
    // Ctrl+Shift+C - Copy last assistant message
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'c') {
      e.preventDefault();
      const lastMsg = getMessages().slice().reverse().find((m) => m.role === 'assistant');
      if (lastMsg && lastMsg.content) {
        navigator.clipboard.writeText(lastMsg.content).then(() => {
          showToast({ type: 'success', message: 'Last response copied to clipboard.' });
        });
      } else {
        showToast({ type: 'info', message: 'No assistant message to copy.' });
      }
    }
    // Ctrl+Shift+R - Regenerate last response
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'r') {
      e.preventDefault();
      if (!getIsGenerating() && getLastUserText()) {
        regenerate();
      } else if (getIsGenerating()) {
        showToast({ type: 'info', message: 'Generation already in progress.' });
      } else {
        showToast({ type: 'info', message: 'No previous response to regenerate.' });
      }
    }
    // Ctrl/Cmd+, - Open settings
    if ((e.ctrlKey || e.metaKey) && e.key === ',') {
      e.preventDefault();
      openSettings();
    }
    // Ctrl/Cmd+M - Open model selector
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'm') {
      e.preventDefault();
      elements.modelSelector.classList.contains('open') ? closeModelDropdown() : openModelDropdown();
    }
    // / (when not in input) - Focus composer
    if (e.key === '/' && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA' && !document.activeElement.isContentEditable) {
      e.preventDefault();
      elements.messageInput?.focus();
    }
    // Ctrl+Shift+T - Toggle theme
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 't') {
      e.preventDefault();
      const cur = document.documentElement.getAttribute('data-theme');
      const newTheme = cur === 'dark' ? 'light' : 'dark';
      import('./core/state.js').then((m) => {
        m.setSettings({ ...m.getSettings(), theme: newTheme });
        settingsApplySettings();
      });
    }
    // Ctrl+Shift+W - Toggle web search
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'w') {
      e.preventDefault();
      elements.webSearchToggle?.click();
    }
    // Ctrl+/ - Shortcuts help
    if ((e.ctrlKey || e.metaKey) && e.key === '/') {
      e.preventDefault();
      elements.shortcutsOverlay?.classList.remove('hidden');
    }
  });

  // Close shortcuts modal
  elements.shortcutsOverlay?.addEventListener('click', (e) => {
    if (e.target === elements.shortcutsOverlay) elements.shortcutsOverlay.classList.add('hidden');
  });
  elements.closeShortcuts?.addEventListener('click', () => elements.shortcutsOverlay.classList.add('hidden'));

  // Skills button
  elements.skillsBtn?.addEventListener('click', () => openSkillsModal(document.getElementById('skillsOverlay')));
  elements.closeSkills?.addEventListener('click', () => closeSkillsModal());
  elements.skillsOverlay?.addEventListener('click', (e) => { if (e.target === elements.skillsOverlay) closeSkillsModal(); });

  // New chat buttons, sidebar controls, and search are handled by initSidebar()

  // Error detail toggle
  elements.errorDetailToggle?.addEventListener('click', () => {
    const detail = elements.errorState.querySelector('.error-detail');
    const expanded = detail.classList.toggle('expanded');
    elements.errorDetailToggle.setAttribute('aria-expanded', String(expanded));
    elements.errorDetailToggle.innerHTML = expanded
      ? `<i class="fa-solid fa-chevron-up"></i> Hide details`
      : `<i class="fa-solid fa-chevron-down"></i> Show details`;
  });

  // Settings button
  elements.settingsBtn?.addEventListener('click', openSettings);

  // ── Temperature popover ──
  elements.tempControl?.addEventListener('click', (e) => {
    e.stopPropagation();
    elements.tempPopover?.classList.toggle('hidden');
  });
  document.addEventListener('click', (e) => {
    if (!elements.tempControl?.contains(e.target) && !elements.tempPopover?.contains(e.target)) {
      elements.tempPopover?.classList.add('hidden');
    }
  });
  elements.tempSlider?.addEventListener('input', () => {
    const val = elements.tempSlider.value;
    elements.tempValue.textContent = val;
    elements.tempPopoverValue.textContent = val;
    setTemperature(parseFloat(val));
  });

  // ── Token dropdown ──
  elements.tokenBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    elements.tokenDropdown?.classList.toggle('hidden');
  });
  elements.tokenDropdown?.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-value]');
    if (!btn) return;
    const val = btn.dataset.value;
    elements.tokenLabel.textContent = parseInt(val).toLocaleString();
    setMaxTokens(val);
    elements.tokenDropdown.querySelectorAll('button').forEach((b) => b.classList.remove('selected'));
    btn.classList.add('selected');
    elements.tokenDropdown.classList.add('hidden');
  });

  // ── Reasoning dropdown ──
  elements.reasoningBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    elements.reasoningDropdown?.classList.toggle('hidden');
  });
  elements.reasoningDropdown?.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-value]');
    if (!btn) return;
    const val = btn.dataset.value;
    const labels = { none: 'Auto', low: 'Low', medium: 'Medium', high: 'High', extra_high: 'Extra High' };
    elements.reasoningLabel.textContent = labels[val] || val;
    setReasoningEffort(val);
    elements.reasoningDropdown.querySelectorAll('button').forEach((b) => b.classList.remove('selected'));
    btn.classList.add('selected');
    elements.reasoningDropdown.classList.add('hidden');
  });

  // Close select dropdowns when clicking outside
  document.addEventListener('click', (e) => {
    if (!elements.tokenSelect?.contains(e.target)) {
      elements.tokenDropdown?.classList.add('hidden');
    }
    if (!elements.reasoningSelect?.contains(e.target)) {
      elements.reasoningDropdown?.classList.add('hidden');
    }
  });
}

/**
 * Provide a global function namespace for inline HTML handlers.
 * This is needed for backward compatibility with HTML event handlers.
 */
function setupGlobalNamespace() {
  window.sangamApp = {
    // Chat
    handleSend,
    regenerate,
    stopGeneration,
    autoResizeTextarea,
    scrollToBottom,
    startNewChat: chatStartNewChat,
    openChat: sidebarOpenChat,
    deleteChat: sidebarDeleteChat,
    renderChatHistory: sidebarRenderChatHistory,
    // Models
    loadProvidersAndModels,
    renderModelList,
    renderProviderFilters,
    renderProviderStatusList,
    renderConnPulse,
    selectModel,
    openModelDropdown,
    closeModelDropdown,
    // Settings
    openSettings,
    closeSettingsModal,
    applySettings: settingsApplySettings,
    syncSettingsUI,
    // Sidebar
    openMobileSidebar,
    closeMobileSidebar,
    toggleSidebarCollapse,
    // Skills
    openSkillsModal: () => openSkillsModal(document.getElementById('skillsOverlay')),
    closeSkillsModal,
    // Auth
    initializeAuth,
    // Utils
    showToast,
  };
}

/**
 * Sync token and reasoning dropdowns with current state.
 */
function syncDropdownsFromState() {
  // Token dropdown
  const maxTokens = getMaxTokens();
  elements.tokenLabel.textContent = parseInt(maxTokens).toLocaleString();
  elements.tokenDropdown?.querySelectorAll('button').forEach((b) => {
    b.classList.toggle('selected', b.dataset.value === maxTokens);
  });

  // Reasoning dropdown
  const reasoningEffort = getReasoningEffort();
  const labels = { none: 'Auto', low: 'Low', medium: 'Medium', high: 'High', extra_high: 'Extra High' };
  elements.reasoningLabel.textContent = labels[reasoningEffort] || reasoningEffort;
  elements.reasoningDropdown?.querySelectorAll('button').forEach((b) => {
    b.classList.toggle('selected', b.dataset.value === reasoningEffort);
  });
}

/**
 * Main bootstrap function - called after auth succeeds.
 */
export async function startApplication() {
  // Apply saved settings
  loadSettings();
  settingsApplySettings();

  // Initialize toast system
  initToasts();

  // Set up global namespace for inline handlers
  setupGlobalNamespace();

  // Sync dropdowns with current state
  syncDropdownsFromState();

  // Load providers and models from backend
  try {
    await loadProvidersAndModels();
    await sidebarLoadChatList();
    elements.backendDownState?.classList.add('hidden');
    chatStartNewChat();
    showToast({ type: 'success', title: 'Connected', message: `Live backend at ${getApiBaseUrl()}` });
  } catch (err) {
    chatStartNewChat();
    elements.messages.innerHTML = '';
    elements.welcomeScreen.classList.add('hidden');
    elements.backendDownState.classList.remove('hidden');
    elements.backendDownState.innerHTML = `
      <div class="backend-down-header">
        <i class="fa-solid fa-plug-circle-xmark"></i>
        <strong>Backend not reachable at ${getApiBaseUrl()}</strong>
      </div>
      <p>The frontend loads fine on its own, but nothing (providers, models, chat) can work until the FastAPI backend is actually running. Start it with:</p>
      <pre>./start.sh          <span class="comment"># Mac/Linux, from the project root</span>
start.bat           <span class="comment"># Windows, from the project root</span></pre>
      <p>Then click Retry below. Using a different port or host? Open Settings → Connection to change the backend URL.</p>
      <button class="btn-secondary" id="retryBackendBtn">Retry connection</button>
    `;
    document.getElementById('retryBackendBtn').addEventListener('click', () => startApplication());
    showToast({ type: 'error', title: 'Backend unreachable', message: 'See the message in the chat window for the exact fix.', duration: 6000 });
  }
}

/**
 * Initialize the application.
 */
async function init() {
  // Initialize DOM references
  initDOM();

  // Inject CSP for markdown content security
  injectMarkdownCSP();

  // Initialize core state
  initAppState();

  // Initialize modules
  initAuth();
  initSettings();
  initModelSelector();
  initChatEvents();
  initSidebar();
  initGlobalListeners();
  initSkills(document.getElementById('skillsOverlay'));

  // Initialize auth flow (this will call startApplication on success)
  setStartApplicationCallback(startApplication);
  await initializeAuth();
}

// Start the app when DOM is ready
console.log('[App] Document readyState:', document.readyState, '- Starting module loads...');
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    console.log('[App] DOMContentLoaded - calling init()');
    init();
  });
} else {
  console.log('[App] Already loaded - calling init() directly');
  init();
}

console.log('[App] Module graph loaded successfully, exports available');