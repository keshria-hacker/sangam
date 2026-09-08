/**
 * Auth feature - Authentication overlay, login, register, password reset.
 */

import { getApiBaseUrl, apiFetch, apiPost } from '../../shared/http.js';
import { showToast, showError } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';
import { STORAGE_KEYS } from '../../shared/constants.js';

console.log('[Module] auth.js loaded');

let elements = {};
/** @type {AbortController|null} — allows cleanup of popup listeners on re-init */
let _popupController = null;
/** @type {Element|null} — stores the element focused before popup opened */
let _prevFocus = null;

/**
 * Initialize DOM references.
 */
export function initElements() {
  elements = {
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
    profileAvatar: $('#profileAvatar'),
    profileName: $('#profileName'),
    profileSection: $('#profileSection'),
    profilePopup: $('#profilePopup'),
    profilePopupName: $('#profilePopupName'),
    profilePopupAvatar: $('#profilePopupAvatar'),
    profilePopupEmail: $('#profilePopupEmail'),
    logoutBtn: $('#logoutBtn'),
    accountSettingsBtn: $('#accountSettingsBtn'),
    preferencesBtn: $('#preferencesBtn'),
  };
}



/**
 * Logout the current user.
 */
export async function logout() {
  try {
    const res = await apiFetch('/auth/logout', {
      method: 'POST',
      credentials: 'include',
    });

    if (res.ok) {
      // Reload the page to show the auth screen
      window.location.reload();
    } else {
      throw new Error('Logout failed');
    }
  } catch (err) {
    showToast({ type: 'error', title: 'Logout failed', message: err.message });
  }
}

/**
 * Initialize profile popup (positioned near the sidebar profile section).
 * Uses AbortController so re-initialization cleans up prior listeners.
 */
export function initProfilePopup() {
  // Teardown previous listeners if re-initializing
  _popupController?.abort();
  _popupController = new AbortController();
  const sig = _popupController.signal;

  if (!elements.profileSection || !elements.profilePopup) return;

  // Toggle popup on profile section click
  elements.profileSection.addEventListener('click', (e) => {
    e.preventDefault();
    toggleProfilePopup();
  }, { signal: sig });

  // Keyboard support: Enter/Space on profile section
  elements.profileSection.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggleProfilePopup();
    }
  }, { signal: sig });

  // Close when clicking outside
  document.addEventListener('click', (e) => {
    if (elements.profilePopup.classList.contains('show') &&
        !elements.profilePopup.contains(e.target) &&
        e.target !== elements.profileSection &&
        !elements.profileSection.contains(e.target)) {
      hideProfilePopup();
    }
  }, { signal: sig });

  // Close on Escape + focus trap on Tab
  document.addEventListener('keydown', (e) => {
    if (!elements.profilePopup.classList.contains('show')) return;
    if (e.key === 'Escape') {
      hideProfilePopup();
    } else if (e.key === 'Tab') {
      // Trap focus inside popup
      const focusable = elements.profilePopup.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }, { signal: sig });

  // Reposition on scroll/resize while open
  window.addEventListener('scroll', () => {
    if (elements.profilePopup.classList.contains('show')) positionProfilePopup();
  }, { signal: sig, capture: true });
  window.addEventListener('resize', () => {
    if (elements.profilePopup.classList.contains('show')) positionProfilePopup();
  }, { signal: sig });

  // Logout button
  elements.logoutBtn?.addEventListener('click', async () => {
    hideProfilePopup();
    if (confirm('Are you sure you want to logout?')) {
      await logout();
    }
  }, { signal: sig });

  // Account settings (stub)
  elements.accountSettingsBtn?.addEventListener('click', () => {
    hideProfilePopup();
    showToast({ type: 'info', message: 'Account settings would open here' });
  }, { signal: sig });

  // Preferences (stub)
  elements.preferencesBtn?.addEventListener('click', () => {
    hideProfilePopup();
    showToast({ type: 'info', message: 'Preferences would open here' });
  }, { signal: sig });
}

/** Position the popup — above profile section, fully in viewport */
function positionProfilePopup() {
  const rect = elements.profileSection.getBoundingClientRect();
  const popup = elements.profilePopup;
  const gap = 8;
  const viewportPad = 10;

  // Show momentarily to measure actual height (no paint flicker — synchronous JS)
  popup.classList.add('show');
  const popupH = popup.offsetHeight;
  popup.classList.remove('show');

  // Default: position above the profile section
  let top = rect.top - popupH - gap;

  // If not enough room above, flip to below
  if (top < viewportPad) {
    top = rect.bottom + gap;
  }

  // If even below would overflow bottom, clamp to viewport bottom
  if (top + popupH + viewportPad > window.innerHeight) {
    top = window.innerHeight - popupH - viewportPad;
  }

  // Center horizontally on profile section, clamped to viewport
  let left = rect.left + (rect.width / 2) - 130;
  left = Math.max(viewportPad, left);

  popup.style.left = left + 'px';
  popup.style.top = top + 'px';
}

/** Toggle popup visibility */
function toggleProfilePopup() {
  if (elements.profilePopup.classList.contains('show')) {
    hideProfilePopup();
  } else {
    showProfilePopup();
  }
}

/** Show the popup with focus management */
function showProfilePopup() {
  // Save currently focused element to restore later
  _prevFocus = document.activeElement;
  positionProfilePopup();
  elements.profilePopup.classList.add('show');
  // Focus first button inside popup
  const firstBtn = elements.profilePopup.querySelector('button');
  if (firstBtn) firstBtn.focus();
}

/** Hide the popup and restore focus */
function hideProfilePopup() {
  elements.profilePopup.classList.remove('show');
  // Restore focus to the profile section trigger
  if (_prevFocus && _prevFocus !== document.body) {
    _prevFocus.focus();
  } else {
    elements.profileSection?.focus();
  }
  _prevFocus = null;
}

/** Close popup from outside (e.g. sidebar navigation) */
export function closeProfilePopup() {
  if (elements.profilePopup?.classList.contains('show')) {
    hideProfilePopup();
  }
}

/**
 * Initialize auth flow on app start.
 * Returns a Promise that resolves when auth is complete.
 */
export async function initializeAuth() {
  initElements();
  initProfilePopup();

  // Show loading overlay
  elements.authOverlay.classList.remove('hidden');
  elements.authLoading.classList.remove('hidden');
  elements.authLoadingRetry.classList.add('hidden');
  elements.authLoadingText.classList.remove('auth-loading-text--done');
  elements.authForm.classList.add('hidden');
  elements.authError.classList.add('hidden');

  let status;
  const maxRetries = 3;
  let lastError;

  console.log('[Auth] Starting initializeAuth()');

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      if (attempt === 1) {
        elements.authLoadingText.textContent = 'Connecting to backend';
        elements.authLoadingSub.textContent = 'Establishing secure connection…';
      } else {
        elements.authLoadingText.textContent = `Connecting to backend (attempt ${attempt}/${maxRetries})`;
        elements.authLoadingSub.textContent = 'Still trying…';
      }

      console.log(`[Auth] Attempt ${attempt}: Fetching /api/auth/status`);

      const controller = new AbortController();
      const timeoutMs = attempt < maxRetries ? 4000 : 6000;
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
      const response = await fetch(`${getApiBaseUrl()}/auth/status`, { signal: controller.signal });
      clearTimeout(timeoutId);

      console.log(`[Auth] Response status: ${response.status}`);

      if (response.status === 401) {
        // User is not authenticated, show login screen
        console.log('[Auth] 401 Unauthorized, showing login screen');
        status = { authenticated: false, registration_open: false };
        lastError = null;
        break;
      } else if (!response.ok) {
        throw new Error('Authentication service is unavailable');
      }
      status = await response.json();
      console.log('[Auth] Response:', status);
      lastError = null;
      break;
    } catch (err) {
      lastError = err;
      if (attempt < maxRetries) {
        const delay = Math.min(1000 * attempt, 3000);
        await new Promise(r => setTimeout(r, delay));
      }
    }
  }

  if (lastError) {
    // All retries exhausted
    elements.authLoadingText.classList.add('auth-loading-text--done');
    elements.authLoadingText.textContent = 'Could not reach the backend';
    elements.authLoadingSub.textContent = '';
    elements.authLoadingErrmsg.textContent = lastError.name === 'AbortError'
      ? 'Backend took too long to respond. Make sure the server is running, then click Retry.'
      : `Unable to connect: ${lastError.message}`;
    elements.authLoadingRetry.classList.remove('hidden');
    return;
  }

  // Check if we have a stored token
  if (localStorage.getItem(STORAGE_KEYS.ACCESS_TOKEN)) {
    try {
      const token = localStorage.getItem(STORAGE_KEYS.ACCESS_TOKEN);
      const response = await fetch(`${getApiBaseUrl()}/auth/me`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (response.ok) {
        const user = await response.json();
        setProfile(user.username);
        elements.authOverlay.classList.add('hidden');
        startApplication();
        return;
      }
    } catch (_) { /* Show sign-in form below */ }
    localStorage.removeItem(STORAGE_KEYS.ACCESS_TOKEN);
  }

  // Transition to auth form
  elements.authLoading.classList.add('hidden');
  elements.authLoadingRetry.classList.add('hidden');
  const registering = status.registration_open;
  elements.authTitle.textContent = registering ? 'Create your Sangam account' : 'Sign in to Sangam';
  elements.authDescription.textContent = registering
    ? 'Create the local account that protects your providers and conversations.'
    : 'Use your local account to access your providers and conversations.';
  elements.authConfirmWrap.classList.toggle('hidden', !registering);
  elements.authConfirmPassword.required = registering;
  elements.authPassword.autocomplete = registering ? 'new-password' : 'current-password';
  elements.authSubmit.textContent = registering ? 'Create account' : 'Sign in';
  elements.authForm.dataset.mode = registering ? 'register' : 'login';
  elements.authForgotLink.classList.toggle('hidden', registering);
  elements.authForm.classList.remove('hidden');
  elements.authUsername.focus();
}

/**
 * Set user profile in UI.
 */
function setProfile(username) {
  elements.profileName.textContent = username;
  elements.profileAvatar.textContent = username.slice(0, 1).toUpperCase();

  // Update popup profile info from cache
  if (elements.profilePopupName) elements.profilePopupName.textContent = username;
  if (elements.profilePopupAvatar) elements.profilePopupAvatar.textContent = username.slice(0, 1).toUpperCase();
  if (elements.profilePopupEmail) elements.profilePopupEmail.textContent = 'Personal workspace';
}

/**
 * Start the main application after auth.
 * This will be overridden by main app.
 */
let startApplication = () => {
  // No-op — overridden by setStartApplicationCallback
};

/**
 * Set the startApplication callback.
 */
export function setStartApplicationCallback(fn) {
  startApplication = fn;
}

/**
 * Submit login/register form.
 */
async function submitAuthForm(event) {
  event.preventDefault();
  const registering = elements.authForm.dataset.mode === 'register';
  const username = elements.authUsername.value.trim();
  const password = elements.authPassword.value;

  elements.authError.classList.add('hidden');

  if (registering && password !== elements.authConfirmPassword.value) {
    elements.authError.textContent = 'Passwords do not match.';
    elements.authError.classList.remove('hidden');
    return;
  }

  elements.authSubmit.disabled = true;
  elements.authSubmit.textContent = registering ? 'Creating account…' : 'Signing in…';

  try {
    const response = await fetch(`${getApiBaseUrl()}/auth/${registering ? 'register' : 'login'}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Could not authenticate');

    localStorage.setItem(STORAGE_KEYS.ACCESS_TOKEN, data.access_token);
    setProfile(data.username);
    elements.authOverlay.classList.add('hidden');
    showToast({ type: 'success', title: registering ? 'Account created' : 'Signed in', message: `Welcome, ${data.username}.` });
    startApplication();
  } catch (err) {
    elements.authError.textContent = err.message;
    elements.authError.classList.remove('hidden');
  } finally {
    elements.authSubmit.disabled = false;
    elements.authSubmit.textContent = registering ? 'Create account' : 'Sign in';
  }
}

/**
 * Show login form (from forgot/reset forms).
 */
function showLoginForm() {
  elements.authForm.classList.remove('hidden');
  elements.authForgotForm.classList.add('hidden');
  elements.authResetForm.classList.add('hidden');
  elements.authForgotError.classList.add('hidden');
  elements.authResetError.classList.add('hidden');
  elements.authResetSuccess.classList.add('hidden');
  elements.authTokenBox.classList.add('hidden');
}

/**
 * Initialize auth event listeners.
 */
export function initAuth() {
  elements.authForm?.addEventListener('submit', submitAuthForm);

  // Forgot password button
  elements.authForgotBtn?.addEventListener('click', () => {
    elements.authForm.classList.add('hidden');
    elements.authForgotForm.classList.remove('hidden');
    elements.authForgotUsername.value = '';
    elements.authForgotError.classList.add('hidden');
    elements.authTokenBox.classList.add('hidden');
    elements.authForgotSubmit.classList.remove('hidden');
    elements.authForgotSubmit.textContent = 'Send reset token';
    elements.authForgotSubmit.disabled = false;
    elements.authForgotUsername.focus();
  });

  // Back to sign in from forgot form
  elements.authForgotBack?.addEventListener('click', showLoginForm);

  // Back to sign in from reset form
  elements.authResetBack?.addEventListener('click', showLoginForm);

  // Submit forgot password
  elements.authForgotSubmit?.addEventListener('click', async () => {
    const username = elements.authForgotUsername.value.trim();
    if (!username) {
      elements.authForgotError.textContent = 'Please enter your username.';
      elements.authForgotError.classList.remove('hidden');
      return;
    }
    elements.authForgotError.classList.add('hidden');
    elements.authForgotSubmit.disabled = true;
    elements.authForgotSubmit.textContent = 'Sending…';

    try {
      const res = await apiFetch('/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username }),
      });
      const data = await res.json();
      if (data.reset_token) {
        elements.authTokenText.textContent = data.reset_token;
        elements.authTokenBox.classList.remove('hidden');
        elements.authForgotSubmit.classList.add('hidden');
      } else {
        // Username didn't exist - vague message
        elements.authForgotError.textContent = data.message || 'Could not process request.';
        elements.authForgotError.classList.remove('hidden');
      }
    } catch (err) {
      elements.authForgotError.textContent = err.message;
      elements.authForgotError.classList.remove('hidden');
    } finally {
      elements.authForgotSubmit.disabled = false;
      elements.authForgotSubmit.textContent = 'Send reset token';
    }
  });

  // Copy reset token
  elements.authCopyToken?.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(elements.authTokenText.textContent);
      const original = elements.authCopyToken.innerHTML;
      elements.authCopyToken.innerHTML = '<i class="fa-solid fa-check"></i> Copied!';
      setTimeout(() => { elements.authCopyToken.innerHTML = original; }, 2000);
    } catch {
      // Fallback: select the text
      const range = document.createRange();
      range.selectNodeContents(elements.authTokenText);
      const sel = window.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(range);
    }
  });

  // Continue to reset form
  elements.authContinueReset?.addEventListener('click', () => {
    elements.authForgotForm.classList.add('hidden');
    elements.authResetForm.classList.remove('hidden');
    elements.authResetToken.value = elements.authTokenText.textContent;
    elements.authResetPassword.value = '';
    elements.authResetConfirm.value = '';
    elements.authResetError.classList.add('hidden');
    elements.authResetSuccess.classList.add('hidden');
    elements.authResetPassword.focus();
  });

  // Submit reset password
  elements.authResetSubmit?.addEventListener('click', async () => {
    const token = elements.authResetToken.value.trim();
    const password = elements.authResetPassword.value;
    const confirm = elements.authResetConfirm.value;

    elements.authResetError.classList.add('hidden');
    elements.authResetSuccess.classList.add('hidden');

    if (!token) {
      elements.authResetError.textContent = 'Please enter the reset token.';
      elements.authResetError.classList.remove('hidden');
      return;
    }
    if (password.length < 10) {
      elements.authResetError.textContent = 'Password must be at least 10 characters.';
      elements.authResetError.classList.remove('hidden');
      return;
    }
    if (password !== confirm) {
      elements.authResetError.textContent = 'Passwords do not match.';
      elements.authResetError.classList.remove('hidden');
      return;
    }

    elements.authResetSubmit.disabled = true;
    elements.authResetSubmit.textContent = 'Resetting…';

    try {
      const res = await apiFetch('/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reset_token: token, new_password: password }),
      });
      const data = await res.json();
      elements.authResetSuccess.textContent = data.message || 'Password reset successfully!';
      elements.authResetSuccess.classList.remove('hidden');
      elements.authResetSubmit.classList.add('hidden');
      elements.authResetToken.disabled = true;
      elements.authResetPassword.disabled = true;
      elements.authResetConfirm.disabled = true;
    } catch (err) {
      elements.authResetError.textContent = err.message;
      elements.authResetError.classList.remove('hidden');
    } finally {
      elements.authResetSubmit.disabled = false;
      elements.authResetSubmit.textContent = 'Reset password';
    }
  });

  // Retry auth connection
  elements.authRetryBtn?.addEventListener('click', () => { initializeAuth(); });
}
