/**
 * Canonical Sangam response event boundary.
 *
 * Network SSE frames enter here and are normalized before chat UI state mutates.
 * Legacy token SSE frames are still supported for backward compatibility, but
 * provider-specific response parsing must not live in UI components.
 *
 * Phase 2: Stream buffer + render scheduler
 * - Buffers incoming deltas (text/reasoning) in a small accumulator
 * - Flushes via requestAnimationFrame to cap DOM mutations at ~60fps
 * - Coalesces rapid text_delta events before render
 * - Exposes flush() for forced finalization on message_end/abort
 *
 * Phase 4: Tool calls, citations, artifacts, reasoning support
 * - Handles TOOL_START, TOOL_INPUT_DELTA, TOOL_END, TOOL_RESULT
 * - Handles CITATION
 * - Handles ARTIFACT_START, ARTIFACT_DELTA, ARTIFACT_END
 * - Handles REASONING_START, REASONING_DELTA, REASONING_END
 */

export const RESPONSE_EVENT_TYPES = Object.freeze({
  MESSAGE_START: "message_start",
  TEXT_START: "text_start",
  TEXT_DELTA: "text_delta",
  TEXT_END: "text_end",
  REASONING_START: "reasoning_start",
  REASONING_DELTA: "reasoning_delta",
  REASONING_END: "reasoning_end",
  TOOL_START: "tool_start",
  TOOL_INPUT_DELTA: "tool_input_delta",
  TOOL_END: "tool_end",
  TOOL_RESULT: "tool_result",
  CITATION: "citation",
  CLARIFICATION_REQUEST: "clarification_request",
  ARTIFACT_START: "artifact_start",
  ARTIFACT_DELTA: "artifact_delta",
  ARTIFACT_END: "artifact_end",
  USAGE: "usage",
  MESSAGE_END: "message_end",
  ERROR: "error",
});

const TERMINAL_TYPES = new Set([RESPONSE_EVENT_TYPES.MESSAGE_END, RESPONSE_EVENT_TYPES.ERROR]);

// Default batch window (ms) — how long we accumulate deltas before forcing a render.
// This plus rAF scheduling keeps DOM mutations at display refresh (~60fps).
const DEFAULT_BATCH_WINDOW_MS = 16;

/**
 * Cross-platform requestAnimationFrame polyfill.
 * Uses native rAF in browsers, falls back to setTimeout(_, 0) in Node.js / tests.
 */
function raf(callback) {
  if (typeof requestAnimationFrame === "function") {
    return requestAnimationFrame(callback);
  }
  // Node.js / non-browser: use immediate-style setTimeout
  return setTimeout(callback, 0);
}

/**
 * Cross-platform cancelAnimationFrame polyfill.
 */
function cancelRaf(id) {
  if (typeof cancelAnimationFrame === "function") {
    cancelAnimationFrame(id);
  } else {
    clearTimeout(id);
  }
}

/**
 * Create a response controller with stream buffering and scheduled rendering.
 *
 * @param {Object} handlers - Callback handlers for canonical events
 * @param {Object} options - Configuration options
 * @param {number} options.batchWindowMs - Max time to buffer deltas before flush (default: 16ms)
 * @param {Function} options.onFlush - Optional callback fired after each batched flush
 */
export function createResponseController(handlers = {}, options = {}) {
  const batchWindowMs = options.batchWindowMs ?? DEFAULT_BATCH_WINDOW_MS;
  const onFlush = options.onFlush ?? (() => {});

  // Stream buffers — accumulate deltas between rAF flushes
  let textBuffer = "";
  let reasoningBuffer = "";
  let toolInputBuffer = "";
  let textBufferScheduled = false;
  let reasoningBufferScheduled = false;
  let toolInputBufferScheduled = false;

  // Lifecycle state
  let lastSequence = -1;
  let terminal = false;
  let sawCanonical = false;
  let messageId = null;
  let requestId = null; // Track request_id from canonical events
  let started = false;
  let textOpen = false;
  let reasoningOpen = false;
  let toolOpen = false;
  let currentToolId = null;
  let finalized = false; // true after flush() called on terminal/abort

  function emit(name, payload) {
    const handler = handlers[name];
    if (typeof handler === "function") handler(payload);
  }

  /**
   * Schedule a buffered flush via requestAnimationFrame.
   * Coalesces multiple rapid deltas into a single DOM update.
   */
  function scheduleTextFlush() {
    if (textBufferScheduled) return;
    textBufferScheduled = true;
    raf(() => {
      textBufferScheduled = false;
      if (textBuffer.length > 0) {
        emit("textDelta", textBuffer);
        textBuffer = "";
      }
      onFlush("text");
    });
  }

  function scheduleReasoningFlush() {
    if (reasoningBufferScheduled) return;
    reasoningBufferScheduled = true;
    raf(() => {
      reasoningBufferScheduled = false;
      if (reasoningBuffer.length > 0) {
        emit("reasoningDelta", reasoningBuffer);
        reasoningBuffer = "";
      }
      onFlush("reasoning");
    });
  }

  function scheduleToolInputFlush() {
    if (toolInputBufferScheduled) return;
    toolInputBufferScheduled = true;
    raf(() => {
      toolInputBufferScheduled = false;
      if (toolInputBuffer.length > 0 && currentToolId) {
        emit("toolInputDelta", { toolId: currentToolId, content: toolInputBuffer });
        toolInputBuffer = "";
      }
      onFlush("tool_input");
    });
  }

  /**
   * Force-flush any pending buffers immediately (bypasses rAF).
   * Called on message_end, error, or abort to ensure final content renders.
   */
  function flush() {
    if (textBufferScheduled) {
      textBufferScheduled = false;
    }
    if (textBuffer.length > 0) {
      emit("textDelta", textBuffer);
      textBuffer = "";
    }
    if (reasoningBufferScheduled) {
      reasoningBufferScheduled = false;
    }
    if (reasoningBuffer.length > 0) {
      emit("reasoningDelta", reasoningBuffer);
      reasoningBuffer = "";
    }
    if (toolInputBufferScheduled) {
      toolInputBufferScheduled = false;
    }
    if (toolInputBuffer.length > 0 && currentToolId) {
      emit("toolInputDelta", { toolId: currentToolId, content: toolInputBuffer });
      toolInputBuffer = "";
    }
    onFlush("forced");
    finalized = true;
  }

  function handleCanonical(rawData) {
    let event;
    try {
      event = typeof rawData === "string" ? JSON.parse(rawData) : rawData;
    } catch (err) {
      emit("error", {
        category: "stream_error",
        message: `Malformed response event: ${err.message}`,
        retryable: false,
      });
      terminal = true;
      return;
    }

    if (!event || typeof event.type !== "string") {
      emit("warning", "Ignored response event without a type.");
      return;
    }
    sawCanonical = true;

    if (terminal && event.type !== RESPONSE_EVENT_TYPES.ERROR) {
      // Allow ERROR to propagate even after terminal (e.g., stream error after message_end)
      emit("warning", `Ignored ${event.type} after terminal response event.`);
      return;
    }

    if (!started && event.type !== RESPONSE_EVENT_TYPES.MESSAGE_START) {
      emit("warning", `Ignored ${event.type} before message_start.`);
      return;
    }

    if (event.message_id) {
      if (messageId && messageId !== event.message_id) {
        emit("warning", "Ignored response event for a different message id.");
        return;
      }
      messageId = event.message_id;
    }

    if (event.request_id) {
      if (requestId && requestId !== event.request_id) {
        emit("warning", "Ignored response event for a different request id.");
        return;
      }
      requestId = event.request_id;
    }

    if (typeof event.sequence === "number") {
      if (event.sequence <= lastSequence) {
        emit("warning", `Ignored out-of-order response event: ${event.type}.`);
        return;
      }
      lastSequence = event.sequence;
    }

    switch (event.type) {
      case RESPONSE_EVENT_TYPES.MESSAGE_START:
        if (started) {
          emit("warning", "Ignored duplicate message_start event.");
          return;
        }
        started = true;
        emit("messageStart", event);
        break;
      case RESPONSE_EVENT_TYPES.TEXT_START:
        if (textOpen) {
          emit("warning", "Ignored duplicate text_start event.");
          return;
        }
        textOpen = true;
        emit("textStart", event);
        break;
      case RESPONSE_EVENT_TYPES.TEXT_DELTA:
        if (!textOpen) {
          emit("warning", "Ignored text_delta outside a text block.");
          return;
        }
        if (event.content) {
          textBuffer += event.content;
          scheduleTextFlush();
        }
        break;
      case RESPONSE_EVENT_TYPES.TEXT_END:
        if (!textOpen) {
          emit("warning", "Ignored text_end without text_start.");
          return;
        }
        textOpen = false;
        flush();
        emit("textEnd", event);
        break;
      case RESPONSE_EVENT_TYPES.REASONING_START:
        if (reasoningOpen) {
          emit("warning", "Ignored duplicate reasoning_start event.");
          return;
        }
        reasoningOpen = true;
        emit("reasoningStart", event);
        break;
      case RESPONSE_EVENT_TYPES.REASONING_DELTA:
        if (!reasoningOpen) {
          emit("warning", "Ignored reasoning_delta outside a reasoning block.");
          return;
        }
        if (event.content) {
          reasoningBuffer += event.content;
          scheduleReasoningFlush();
        }
        break;
      case RESPONSE_EVENT_TYPES.REASONING_END:
        if (!reasoningOpen) {
          emit("warning", "Ignored reasoning_end without reasoning_start.");
          return;
        }
        reasoningOpen = false;
        flush();
        emit("reasoningEnd", event);
        break;
      case RESPONSE_EVENT_TYPES.TOOL_START:
        if (toolOpen && currentToolId !== event.metadata?.tool_id) {
          emit("warning", "Ignored tool_start for different tool without closing previous.");
          return;
        }
        toolOpen = true;
        currentToolId = event.metadata?.tool_id || null;
        emit("toolStart", event);
        break;
      case RESPONSE_EVENT_TYPES.TOOL_INPUT_DELTA:
        if (!toolOpen) {
          emit("warning", "Ignored tool_input_delta outside a tool block.");
          return;
        }
        if (event.content) {
          toolInputBuffer += event.content;
          scheduleToolInputFlush();
        }
        break;
      case RESPONSE_EVENT_TYPES.TOOL_END:
        if (!toolOpen) {
          emit("warning", "Ignored tool_end without tool_start.");
          return;
        }
        flush();
        toolOpen = false;
        currentToolId = null;
        emit("toolEnd", event);
        break;
      case RESPONSE_EVENT_TYPES.TOOL_RESULT:
        emit("toolResult", event);
        break;
      case RESPONSE_EVENT_TYPES.CITATION:
        emit("citation", event);
        break;
      case RESPONSE_EVENT_TYPES.CLARIFICATION_REQUEST:
        emit("clarification", event);
        break;
      case RESPONSE_EVENT_TYPES.ARTIFACT_START:
        emit("artifactStart", event);
        break;
      case RESPONSE_EVENT_TYPES.ARTIFACT_DELTA:
        if (event.content) {
          emit("artifactDelta", event);
        }
        break;
      case RESPONSE_EVENT_TYPES.ARTIFACT_END:
        emit("artifactEnd", event);
        break;
      case RESPONSE_EVENT_TYPES.USAGE:
        emit("usage", event.usage || {}, event);
        break;
      case RESPONSE_EVENT_TYPES.MESSAGE_END:
        if (textOpen || reasoningOpen || toolOpen) {
          emit("error", {
            category: "stream_error",
            message: "Response ended with an incomplete content block.",
            retryable: false,
          });
          terminal = true;
          break;
        }
        terminal = true;
        flush();
        emit("messageEnd", event);
        break;
      case RESPONSE_EVENT_TYPES.ERROR:
        terminal = true;
        flush();
        emit("error", event.error || { category: "unknown", message: "Provider request failed" }, event);
        break;
      default:
        // Forward compatibility: future non-rendered event types are safe no-ops.
        emit("unknown", event);
        break;
    }
  }

  function handleLegacy({ event, data }) {
    // When canonical events are present, legacy token frames are compatibility
    // duplicates emitted for older clients; ignore them in the new response path.
    if (sawCanonical && (event === "message" || data === "[DONE]")) return;
    if (event === "error") {
      terminal = true;
      flush();
      emit("error", { category: "unknown", message: data || "Provider request failed" });
      return;
    }
    if (data === "[DONE]") {
      terminal = true;
      flush();
      emit("messageEnd", { finish_reason: "stop" });
      return;
    }
    if (data && data !== "[DONE]") emit("textDelta", data);
  }

  return {
    handleSSE(frame) {
      if (frame.event === "response_event") handleCanonical(frame.data);
      else handleLegacy(frame);
    },
    // Exposed for callers that need to force-flush on abort/cancel
    flush,
    get sawCanonical() { return sawCanonical; },
    get terminal() { return terminal; },
    get messageId() { return messageId; },
    get requestId() { return requestId; },
    get isFinalized() { return finalized; },
  };
}
