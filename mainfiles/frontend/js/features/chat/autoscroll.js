/*
autoscroll.js — smart auto-scroll controller for the chat view.

While the user is near the bottom the stream keeps following the latest
content; the moment they scroll up, following stops. A "↓ Jump to latest"
button reappears and resumes following on click. Hysteresis keeps the
flag from flapping on trackpad/touch momentum.
*/
let _followStream = true;             // whether new tokens auto-scroll the view
let _suppressScrollHandler = false;   // guard for programmatic scrolls
const AUTO_SCROLL_THRESHOLD_PX = 220; // dist beyond which following stops
const AUTO_SCROLL_REENGAGE_PX = 60;   // dist within which following resumes
const SMOOTH_SCROLL_SETTLE_MS = 400;  // how long a smooth scroll fires scroll events

let elements = {};

export function initAutoscroll(elemMap) {
  elements = elemMap;
}

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

export function nearBottomDist() {
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
export function onChatScroll() {
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
export function resumeFollow() {
  _followStream = true;
  _suppressScrollHandler = true;
  scrollToBottom(false);
  requestAnimationFrame(() => {
    _suppressScrollHandler = false;
    updateJumpBtn();
  });
}

/**

export function isFollowingStream() {
  return _followStream;
}

export function setFollowingStream(value) {
  _followStream = value;
}
