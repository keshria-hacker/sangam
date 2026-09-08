/**
 * Centralized HTTP client for API communication.
 * Handles auth headers, CSRF tokens, and error normalization.
 */

import { STORAGE_KEYS } from './constants.js';

console.log('[Module] shared/http.js loaded');

// Store ref to API base for quick access
let _apiBase = null;

/**
 * Get the current API base URL from localStorage or default.
 */
export function getApiBaseUrl() {
  if (_apiBase) return _apiBase;
  _apiBase = localStorage.getItem(STORAGE_KEYS.API_BASE) || 'http://127.0.0.1:8001/api';
  return _apiBase;
}

/**
 * Update the API base URL.
 */
export function setApiBaseUrl(url) {
  _apiBase = url.replace(/\/+$/, '');
  localStorage.setItem(STORAGE_KEYS.API_BASE, _apiBase);
}

/**
 * Get the current auth token from localStorage.
 */
function getAuthToken() {
  return localStorage.getItem(STORAGE_KEYS.ACCESS_TOKEN);
}

/**
 * Build auth headers including Bearer token and CSRF token.
 */
export function buildAuthHeaders() {
  const headers = {};
  const token = getAuthToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  // CSRF token from cookie (for cookie-based sessions)
  const csrf = document.cookie
    .split('; ')
    .find((row) => row.startsWith('sangam_csrf='))
    ?.split('=')[1];
  if (csrf) {
    headers['X-CSRF-Token'] = csrf;
  }
  // Request ID for distributed tracing
  headers['X-Request-ID'] = generateRequestId();
  return headers;
}

/**
 * Generate a short request ID for tracing.
 * Uses a simple random hex string.
 */
function generateRequestId() {
  return Math.random().toString(16).slice(2, 14); // 12 chars
}

/**
 * Custom error class for API errors with status and detail.
 */
export class ApiError extends Error {
  constructor(message, status, detail = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Check if response is OK, otherwise throw ApiError with details.
 */
async function handleResponse(response) {
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // Non-JSON error body
    }
    // Special handling for 401 - clear token
    if (response.status === 401) {
      localStorage.removeItem(STORAGE_KEYS.ACCESS_TOKEN);
    }
    throw new ApiError(detail, response.status, detail);
  }
  return response;
}

/**
 * Core fetch wrapper with error handling and auth headers.
 * @param {string} path - API path (e.g., '/models', '/chat/stream')
 * @param {RequestInit} options - Fetch options
 * @param {boolean} throwOnError - Throw on non-OK response (default: true)
 * @returns {Promise<Response>}
 */
export async function apiFetch(path, options = {}, throwOnError = true) {
  const url = `${getApiBaseUrl()}${path}`;
  const headers = {
    ...buildAuthHeaders(),
    ...(options.headers || {}),
  };

  try {
    const response = await fetch(url, { ...options, headers });
    if (throwOnError) {
      return handleResponse(response);
    }
    return response;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    // Network error
    throw new ApiError(`Can't reach the backend at ${getApiBaseUrl()}. Is it running? (${error.message})`, 0);
  }
}

/**
 * GET request helper.
 */
export async function apiGet(path, throwOnError = true) {
  return apiFetch(path, { method: 'GET' }, throwOnError);
}

/**
 * POST request helper with JSON body.
 */
export async function apiPost(path, body, throwOnError = true) {
  return apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }, throwOnError);
}

/**
 * PUT request helper with JSON body.
 */
export async function apiPut(path, body, throwOnError = true) {
  return apiFetch(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }, throwOnError);
}

/**
 * DELETE request helper.
 */
export async function apiDelete(path, throwOnError = true) {
  return apiFetch(path, { method: 'DELETE' }, throwOnError);
}

/**
 * POST with FormData (for file uploads).
 */
export async function apiPostForm(path, formData, throwOnError = true) {
  return apiFetch(path, {
    method: 'POST',
    body: formData,
  }, throwOnError);
}

/**
 * Stream chat completion via SSE.
 * @param {Object} body - Request body for /chat/stream
 * @param {AbortSignal} signal - Abort signal for cancellation
 * @returns {Promise<ReadableStream>} SSE stream
 */
export async function streamChatCompletion(body, signal) {
  const response = await apiFetch('/chat/stream', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...buildAuthHeaders(),
    },
    body: JSON.stringify(body),
    signal,
  }, false); // Don't throw on error - handle in caller

  if (!response.ok || !response.body) {
    let detail = response.statusText;
    try {
      const err = await response.json();
      detail = err.detail || detail;
    } catch {
      // ignore
    }
    throw new ApiError(detail, response.status, detail);
  }

  return response.body;
}

/**
 * Parse SSE stream into events.
 * @param {ReadableStream} stream - Response body stream
 * @returns {AsyncGenerator<{event: string, data: string}>}
 */
export async function* parseSSE(stream) {
  const reader = stream.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: false });
  let buffer = '';

  function parseFrame(frame) {
    let eventType = 'message';
    let data = '';

    frame.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n').forEach((line) => {
      if (!line || line.startsWith(':')) return;
      if (line.startsWith('event:')) {
        eventType = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        data += (data ? '\n' : '') + line.slice(5).replace(/^ /, '');
      }
    });

    return { event: eventType, data };
  }

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      buffer = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n');

      let frameEnd;
      while ((frameEnd = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, frameEnd);
        buffer = buffer.slice(frameEnd + 2);
        const parsed = parseFrame(frame);
        if (parsed.data || parsed.event !== 'message') yield parsed;
      }
    }

    const tail = decoder.decode();
    if (tail) buffer += tail;
    if (buffer.trim()) {
      // Surface an interrupted final frame as a normalized stream error.
      yield { event: 'error', data: 'The response stream ended unexpectedly.' };
    }
  } finally {
    reader.releaseLock();
  }
}
