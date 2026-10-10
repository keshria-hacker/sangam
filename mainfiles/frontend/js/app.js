/**
 * Sangam - Universal AI Chat Platform
 * Main entry point - bootstraps all feature modules.
 */

import { initAppState, getMessages, getIsGenerating, getLastUserText } from './core/state.js';
import { initElements as initChatElements, initChatEvents, handleSend, regenerate, runGeneration, stopGeneration, autoResizeTextarea, scrollToBottom, buildMessageNode, renderMessages, startNewChat as chatStartNewChat } from './features/chat/chat.js';
import { initElements as initModelsElements, loadProvidersAndModels, renderModelList, renderProviderFilters, renderProviderStatusList, renderConnPulse, selectModel, openModelDropdown, closeModelDropdown, initModelSelector } from './features/models/models.js';
import { openSettings } from './features/settings/open.js';
import { applyAppearance, initAppearance } from './features/settings/appearance.js';
import { initElements as initAuthElements, initializeAuth, setStartApplicationCallback, initAuth, logout } from './features/auth/auth.js';
import { renderSkillsTab } from './features/skills/skills.js';
import { renderTeamsTab } from './features/teams/teams.js';
import { renderLearnTab } from './features/learn/learn.js';
import { renderAnalyticsTab } from './features/analytics/analytics.js';
import { renderImageTab } from './features/image/image.js';
import { renderCodeAgentTab } from './features/code-agent/code-agent.js';
import { renderDesignTab } from './features/design/design-studio.js';
import { initTabs, openToolTab, showTool, registerTabRenderer } from './features/tabs/tabs.js';
import { trapFocus } from './shared/focus_trap.js';
import { setLang } from './shared/i18n.js';
import { getSetting } from './shared/settings_store.js';
import { renderRail, registerNavHandler } from './core/nav.js';
import { initPopovers } from './features/composer/popovers.js';
import { initTray } from './features/tray/tray.js';
import { initInspector } from './features/inspector/inspector.js';
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
    // Phase 8 B4: temp/token/reasoning pills removed — Tune popover owns them.
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
    skillsBtn: $('#skillsBtn'),
    codeBtn: $('#codeBtn'),
    designBtn: $('#designBtn'),
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
  initAuthElements();
  initSidebarElements();
}

/**
 * Set up global event listeners that cross modules.
 */
/**
 * Initialize the studio rail (intent-grouped navigation).
 * A9: only registers handlers here. The rail itself renders in
 * loadRailFeatures(), called post-auth when /features returns real state.
 */
async function initRail() {
  const container = document.getElementById('railNav');
  if (!container) return;
  // Register nav handlers
  registerNavHandler('home', () => {
    showTool('home');
  });
  registerNavHandler('chat', () => {
    const { switchTab } = window.__sangamTabs || {};
    // Fallback: main tab is the chat
    document.getElementById('mainTab')?.click();
  });
  registerNavHandler('settings', () => {
    showTool('settings');
  });
  // Load features and render
  // (moved to loadRailFeatures — called post-auth from startApplication)
  // Re-render rail when features change
  document.addEventListener('sangam:features-changed', async (e) => {
    renderRail(container, e.detail?.features || {});
  });
}

/**
 * A9: Fetch /features and render the rail. Called once post-auth from
 * startApplication, so the rail never shows stale "Turn on" badges.
 */
async function loadRailFeatures() {
  const container = document.getElementById('railNav');
  if (!container) return;
  try {
    const { apiFetch } = await import('./shared/http.js');
    const data = await (await apiFetch('/features')).json();
    renderRail(container, data.features || {});
  } catch {
    renderRail(container, {});
  }
}

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
      elements.tempPopover?.classList.add('hidden');
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
      import('./features/settings/appearance.js').then((m) => m.toggleTheme());
    }
    // Ctrl+Shift+W - Toggle web search
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'w') {
      e.preventDefault();
      elements.webSearchToggle?.click();
    }
    // Ctrl+/ - Shortcuts help
    if ((e.ctrlKey || e.metaKey) && e.key === '/') {
      e.preventDefault();
      openShortcutsModal();
    }
  });

  // Shortcuts modal with focus trap
  let releaseShortcutsTrap = null;
  function openShortcutsModal() {
    elements.shortcutsOverlay?.classList.remove('hidden');
    releaseShortcutsTrap = trapFocus(elements.shortcutsOverlay);
  }
  function closeShortcutsModal() {
    elements.shortcutsOverlay?.classList.add('hidden');
    releaseShortcutsTrap?.();
    releaseShortcutsTrap = null;
  }
  // Escape closes it (handled globally too, but be explicit)
  elements.shortcutsOverlay?.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeShortcutsModal();
  });
  elements.shortcutsOverlay?.addEventListener('click', (e) => {
    if (e.target === elements.shortcutsOverlay) closeShortcutsModal();
  });
  elements.closeShortcuts?.addEventListener('click', closeShortcutsModal);

  // Skills button -> opens Skills tab
  elements.skillsBtn?.addEventListener('click', () => showTool('skills'));
  // Code agent button -> opens Code agent tab
  elements.codeBtn?.addEventListener('click', () => showTool('code'));
  // Design studio button -> opens Design studio tab
  elements.designBtn?.addEventListener('click', () => showTool('design'));

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

  // (Footer Settings button removed in Phase 8 B1 — rail Settings is the single entry.)

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
    applySettings: applyAppearance,
    // Sidebar
    openMobileSidebar,
    closeMobileSidebar,
    toggleSidebarCollapse,
    // Skills
    openSkillsTab: () => showTool('skills'),
    // Auth
    initializeAuth,
    // Utils
    showToast,
  };
}

/**
 * Main bootstrap function - called after auth succeeds.
 */
export async function startApplication() {
  // Load settings from the server (source of truth); one-time legacy migration
  try {
    const { loadSettings } = await import('./shared/settings_store.js');
    await loadSettings();
  } catch (e) { console.warn('[settings] startup load failed', e); }
  // Apply saved appearance settings (theme/font/density from settings store)
  applyAppearance();

  // i18n: apply the language setting
  try { setLang(getSetting('language') || 'en'); } catch {}

  // PWA: register the service worker (safe no-op if unsupported)
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  }

  // Initialize toast system
  initToasts();

  // Set up global namespace for inline handlers
  setupGlobalNamespace();

  // Load providers and models from backend
  try {
    await loadProvidersAndModels();
    await sidebarLoadChatList();
    // A9: render the rail now that /features returns authenticated state.
    await loadRailFeatures();
    elements.backendDownState?.classList.add('hidden');
    chatStartNewChat();
    // Voice: show mic/speak UI only when the backend flag is on.
    import('./features/voice/voice.js').then((m) => m.initVoice()).catch(() => {});
    // Image generation: show the composer button only when the flag is on.
    import('./features/image/image.js').then((m) => m.initImage()).catch(() => {});
    // Agent teams: show the teams button only when the flag is on.
    import('./features/teams/teams.js').then((m) => m.initTeams()).catch(() => {});
    // Learning mode: show the learn button only when the flag is on.
    import('./features/learn/learn.js').then((m) => m.initLearn()).catch(() => {});
    // Analytics: show the usage button only when the flag is on.
    import('./features/analytics/analytics.js').then((m) => m.initAnalytics()).catch(() => {});
    // Command palette (Ctrl+P).
    import('./features/palette/palette.js').then((m) => m.initPalette()).catch(() => {});
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
  initAppearance();
  initModelSelector();
  initChatEvents();
  initSidebar();
  initGlobalListeners();
  initTabs();
  initRail();
  initPopovers();
  initTray();
  initInspector();
  registerTabRenderer('skills', renderSkillsTab);
  registerTabRenderer('teams', renderTeamsTab);
  registerTabRenderer('learn', renderLearnTab);
  registerTabRenderer('analytics', renderAnalyticsTab);
  registerTabRenderer('images', renderImageTab);
  registerTabRenderer('code', renderCodeAgentTab);
  registerTabRenderer('design', renderDesignTab);
  registerTabRenderer('home', async (bodyEl) => {
    const { renderHome } = await import('./features/home/home.js');
    renderHome(bodyEl);
  });
  registerTabRenderer('settings', async (bodyEl) => {
    const { renderSettingsPage } = await import('./features/settings/settings_page.js');
    renderSettingsPage(bodyEl);
  });
  registerTabRenderer('knowledge', async (bodyEl) => {
    const { renderKnowledgeTab } = await import('./features/knowledge/knowledge.js');
    renderKnowledgeTab(bodyEl);
  });
  registerTabRenderer('agents', async (bodyEl) => {
    const { renderAgentHub } = await import('./features/agents/hub.js');
    renderAgentHub(bodyEl);
  });
  registerTabRenderer('create', async (bodyEl) => {
    const { renderCreateHub } = await import('./features/create/hub.js');
    renderCreateHub(bodyEl);
  });
  registerTabRenderer('library', async (bodyEl) => {
    const { renderLibrary } = await import('./features/library/library.js');
    renderLibrary(bodyEl);
  });
  registerTabRenderer('routes', async (bodyEl) => {
    const { renderRoutesTab } = await import('./features/routing/routes.js');
    renderRoutesTab(bodyEl);
  });
  registerTabRenderer('automations', async (bodyEl) => {
    const { renderAutomations } = await import('./features/automations/ui.js');
    renderAutomations(bodyEl);
  });
  registerTabRenderer('compare', async (bodyEl) => {
    const { renderCompareTab } = await import('./features/compare/compare.js');
    renderCompareTab(bodyEl);
  });
  registerTabRenderer('voice', async (bodyEl) => {
    const { renderVoiceStudio } = await import('./features/voice/studio.js');
    renderVoiceStudio(bodyEl);
  });

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