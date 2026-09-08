/**
 * Shared constants and configuration.
 * Centralized to avoid duplication across modules.
 */

// Provider color mapping for UI indicators
export const PROVIDER_COLORS = {
  anthropic: '#D97757',
  openai: '#10A37F',
  nvidia: '#76B900',
  together: '#7C5CFC',
  groq: '#F55036',
  openrouter: '#6C6BF5',
  deepseek: '#4C6FFF',
  mistral: '#FF7000',
  gemini: '#4285F4',
  ollama: '#9A9A9A',
  omniroute: '#22C55E',
};

// File extension to icon/color mapping
export const FILE_ICON_MAP = {
  pdf:  { icon: 'fa-file-pdf',     color: '#F26D6D' },
  docx: { icon: 'fa-file-word',    color: '#2F80ED' },
  doc:  { icon: 'fa-file-word',    color: '#2F80ED' },
  txt:  { icon: 'fa-file-lines',   color: '#9AA1AC' },
  md:   { icon: 'fa-file-lines',   color: '#9AA1AC' },
  csv:  { icon: 'fa-file-csv',     color: '#4ADE80' },
  xlsx: { icon: 'fa-file-excel',   color: '#4ADE80' },
  pptx: { icon: 'fa-file-powerpoint', color: '#F5A623' },
  json: { icon: 'fa-file-code',    color: '#F5A623' },
  html: { icon: 'fa-file-code',    color: '#F55036' },
  xml:  { icon: 'fa-file-code',    color: '#F55036' },
  py:   { icon: 'fa-file-code',    color: '#4C6FFF' },
  java: { icon: 'fa-file-code',    color: '#D97757' },
  js:   { icon: 'fa-file-code',    color: '#F5A623' },
  c:    { icon: 'fa-file-code',    color: '#6C6BF5' },
  cpp:  { icon: 'fa-file-code',    color: '#6C6BF5' },
  cs:   { icon: 'fa-file-code',    color: '#7C5CFC' },
  go:   { icon: 'fa-file-code',    color: '#00B8A9' },
  rs:   { icon: 'fa-file-code',    color: '#F55036' },
  php:  { icon: 'fa-file-code',    color: '#7C5CFC' },
  sql:  { icon: 'fa-file-code',    color: '#4285F4' },
  r:    { icon: 'fa-file-code',    color: '#2F80ED' },
};

export const SUPPORTED_FILE_EXTENSIONS = Object.keys(FILE_ICON_MAP);

// Code highlighting themes
export const CODE_THEME_URLS = {
  'github-dark': 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css',
  'atom-one-dark': 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css',
  'nord': 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/nord.min.css',
  'dracula': 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/dracula.min.css',
  'github': 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css',
};

// Toast types
export const TOAST_TYPES = {
  SUCCESS: 'success',
  ERROR: 'error',
  INFO: 'info',
};

// Toast icons
export const TOAST_ICONS = {
  success: 'fa-circle-check',
  error: 'fa-circle-exclamation',
  info: 'fa-circle-info',
};

// Default settings
export const DEFAULT_SETTINGS = {
  theme: 'dark',
  fontSize: 'md',
  chatWidth: 'default',
  codeThemeDark: 'github-dark',
  codeThemeLight: 'github',
  animations: true,
};

// Chat date bucketing
export const CHAT_BUCKETS = ['Today', 'Yesterday', 'Previous 7 days', 'Previous 30 days', 'Older'];

// Non-chat model markers (for filtering provider model lists)
export const NON_CHAT_MARKERS = [
  'whisper', 'dall-e', 'dall_e', 'tts', 'embedding', 'embed',
  'moderation', 'rerank', 'reranker',
];

// Storage keys
export const STORAGE_KEYS = {
  API_BASE: 'sangam-api-base',
  ACCESS_TOKEN: 'sangam-access-token',
  SETTINGS: 'sangam-settings',
};

// Auth settings
export const AUTH = {
  MIN_PASSWORD_LENGTH: 10,
  MAX_AUTH_RETRIES: 3,
  INITIAL_TIMEOUT: 4000,
  FINAL_TIMEOUT: 6000,
  RETRY_DELAY_BASE: 1000,
};