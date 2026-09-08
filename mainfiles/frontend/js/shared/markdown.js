/**
 * Markdown rendering with syntax highlighting.
 * Uses marked.js 15+ and highlight.js from CDN with DOMPurify sanitization.
 * Supports streaming incremental rendering and final enhanced render pass.
 */

import { escapeHtml } from './utils.js';

// Language normalization map - maps common aliases to highlight.js language IDs
const LANGUAGE_ALIASES = {
  'js': 'javascript',
  'jsx': 'javascript',
  'ts': 'typescript',
  'tsx': 'typescript',
  'py': 'python',
  'rb': 'ruby',
  'sh': 'bash',
  'shell': 'bash',
  'yml': 'yaml',
  'md': 'markdown',
  'mkd': 'markdown',
  'json': 'json',
  'html': 'xml',
  'htm': 'xml',
  'vue': 'xml',
  'svelte': 'xml',
  'cs': 'csharp',
  'csharp': 'csharp',
  'cpp': 'cpp',
  'cc': 'cpp',
  'cxx': 'cpp',
  'c': 'c',
  'h': 'cpp',
  'hpp': 'cpp',
  'rs': 'rust',
  'go': 'go',
  'java': 'java',
  'kt': 'kotlin',
  'scala': 'scala',
  'swift': 'swift',
  'php': 'php',
  'sql': 'sql',
  'r': 'r',
  'dart': 'dart',
  'lua': 'lua',
  'pl': 'perl',
  'pm': 'perl',
  'vim': 'vim',
  'dockerfile': 'dockerfile',
  'docker': 'dockerfile',
  'tf': 'hcl',
  'hcl': 'hcl',
  'toml': 'toml',
  'ini': 'ini',
  'cfg': 'ini',
  'conf': 'ini',
  'text': 'plaintext',
  'txt': 'plaintext',
  'log': 'plaintext',
};

// Supported languages for highlight.js (subset of common ones)
const SUPPORTED_LANGUAGES = new Set([
  'javascript', 'typescript', 'python', 'ruby', 'bash', 'shell',
  'yaml', 'markdown', 'json', 'xml', 'html', 'css', 'scss', 'sass', 'less',
  'csharp', 'cpp', 'c', 'rust', 'go', 'java', 'kotlin', 'scala', 'swift',
  'php', 'sql', 'r', 'dart', 'lua', 'perl', 'vim', 'dockerfile',
  'hcl', 'toml', 'ini', 'plaintext', 'diff', 'nginx', 'apache',
  'graphql', 'protobuf', 'proto', 'regex', 'regexp', 'makefile', 'cmake',
]);

function normalizeLanguage(lang) {
  if (!lang) return 'plaintext';
  const lower = lang.toLowerCase().trim();
  const normalized = LANGUAGE_ALIASES[lower] || lower;
  return SUPPORTED_LANGUAGES.has(normalized) ? normalized : 'plaintext';
}

// Extract filename from code fence info string (e.g., ```js file=example.js)
// Also support ```js:example.js shorthand
function extractFilename(infoString) {
  if (!infoString) return null;
  // Match file=filename or filename at end (after optional language)
  const fileMatch = infoString.match(/file\s*=\s*(\S+)/i);
  if (fileMatch) return fileMatch[1];
  // Match :filename shorthand
  const colonMatch = infoString.match(/:(\S+)$/);
  if (colonMatch) return colonMatch[1];
  return null;
}

// Extract line highlighting info (e.g., ```js {1,3-5})
function extractLineHighlight(infoString) {
  if (!infoString) return null;
  const match = infoString.match(/\{([\d,\-\s]+)\}/);
  if (!match) return null;
  const ranges = match[1].split(',').map(s => s.trim());
  const lines = new Set();
  for (const range of ranges) {
    if (range.includes('-')) {
      const [start, end] = range.split('-').map(Number);
      if (!isNaN(start) && !isNaN(end)) {
        for (let i = start; i <= end; i++) lines.add(i);
      }
    } else {
      const num = Number(range);
      if (!isNaN(num)) lines.add(num);
    }
  }
  return lines.size > 0 ? lines : null;
}

let _marked = null;
let _hljs = null;
let _DOMPurify = null;

// Streaming render cache - stores last input/output to avoid re-render on no-op updates
let _streamCache = { markdown: '', html: '' };

/**
 * Check if markdown libraries are loaded.
 */
function checkLibraries() {
  if (typeof marked !== 'undefined') _marked = marked;
  if (typeof hljs !== 'undefined') _hljs = hljs;
  if (typeof DOMPurify !== 'undefined') _DOMPurify = DOMPurify;
}

/**
 * Configure marked.js 15+ with GFM options and custom renderers.
 */
function configureMarked() {
  if (!_marked || _marked.__sangamConfigured) return;

  // marked.js 15+ uses marked.use() for configuration
  _marked.use({
    gfm: true,
    breaks: true,
    pedantic: false,
    silent: false,
    async: false,
    // Custom renderer for security-sensitive elements
    renderer: {
      link(token) {
        if (!token.href) return token.text || '';
        const safeHref = token.href.startsWith('javascript:') ? '#' : token.href;
        const target = safeHref.startsWith('http') ? ' target="_blank" rel="noopener noreferrer"' : '';
        const titleAttr = token.title ? ` title="${escapeHtml(token.title)}"` : '';
        return `<a href="${escapeHtml(safeHref)}"${target}${titleAttr}>${this.parser.parseInline(token.tokens)}</a>`;
      },
      image(token) {
        if (!token.href) return '';
        const safeHref = token.href.startsWith('javascript:') ? '' : token.href;
        const titleAttr = token.title ? ` title="${escapeHtml(token.title)}"` : '';
        return `<img src="${escapeHtml(safeHref)}" alt="${escapeHtml(token.text || '')}"${titleAttr} loading="lazy">`;
      },
      codespan(token) {
        return `<code>${escapeHtml(token.text)}</code>`;
      },
      code(token) {
        const lang = token.lang && token.lang.trim() ? token.lang.trim() : 'text';
        const normalizedLang = normalizeLanguage(lang);
        const filename = extractFilename(token.lang);
        const highlightLines = extractLineHighlight(token.lang);
        const safeLang = escapeHtml(normalizedLang);
        const safeCode = escapeHtml(token.text);
        let attrs = `class="language-${safeLang}"`;
        if (filename) attrs += ` data-filename="${escapeHtml(filename)}"`;
        if (highlightLines) attrs += ` data-highlight-lines="${escapeHtml(Array.from(highlightLines).join(','))}"`;
        return `<pre><code ${attrs}>${safeCode}</code></pre>`;
      },
      blockquote(token) {
        return `<blockquote>${this.parser.parse(token.tokens)}</blockquote>`;
      },
      table(token) {
        // Build table with scroll wrapper
        const header = token.header || '';
        const rows = token.rows || [];
        return `<div class="table-scroll"><table><thead>${header}</thead><tbody>${rows}</tbody></table></div>`;
      },
      tablerow(token) {
        return `<tr>${this.parser.parseInline(token.tokens)}</tr>`;
      },
      tablecell(token) {
        const tag = token.header ? 'th' : 'td';
        const align = token.align ? ` style="text-align:${token.align}"` : '';
        return `<${tag}${align}>${this.parser.parseInline(token.tokens)}</${tag}>`;
      },
      hr() {
        return '<hr>';
      },
      heading(token) {
        return `<h${token.depth}>${this.parser.parseInline(token.tokens)}</h${token.depth}>`;
      },
      list(token) {
        const tag = token.ordered ? 'ol' : 'ul';
        const startAttr = token.ordered && token.start && token.start !== 1 ? ` start="${token.start}"` : '';
        return `<${tag}${startAttr}>${this.parser.parse(token.tokens)}</${tag}>`;
      },
      listitem(token) {
        if (token.task) {
          const checkAttr = token.checked ? ' checked' : '';
          return `<li class="task-list-item"><input type="checkbox" disabled${checkAttr}> ${this.parser.parseInline(token.tokens)}</li>`;
        }
        return `<li>${this.parser.parse(token.tokens)}</li>`;
      },
      paragraph(token) {
        return `<p>${this.parser.parseInline(token.tokens)}</p>`;
      },
      strong(token) {
        return `<strong>${this.parser.parseInline(token.tokens)}</strong>`;
      },
      em(token) {
        return `<em>${this.parser.parseInline(token.tokens)}</em>`;
      },
      del(token) {
        return `<del>${this.parser.parseInline(token.tokens)}</del>`;
      },
      text(token) {
        return escapeHtml(token.text);
      },
      br() {
        return '<br>';
      },
    },
  });

  _marked.__sangamConfigured = true;
}

/**
 * Parse markdown to sanitized HTML.
 * @param {string} markdown - Markdown text
 * @returns {string} - Sanitized HTML string
 */
export function parseMarkdown(markdown) {
  checkLibraries();
  configureMarked();

  if (!_marked?.parse) {
    // Fallback: escaped text with line breaks
    return escapeHtml(markdown || '').replace(/\n/g, '<br>');
  }

  try {
    const raw = _marked.parse(markdown || '');

    // Sanitize HTML to prevent XSS
    let safeHtml = raw;
    if (_DOMPurify?.sanitize) {
      safeHtml = _DOMPurify.sanitize(raw, {
        USE_PROFILES: { html: true },
        ALLOWED_TAGS: [
          'p', 'br', 'strong', 'em', 'del', 'code', 'pre', 'blockquote',
          'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
          'ul', 'ol', 'li', 'a', 'img', 'hr',
          'table', 'thead', 'tbody', 'tr', 'th', 'td',
          'div', 'span', 'input', 'details', 'summary'
        ],
        ALLOWED_ATTR: [
          'href', 'title', 'target', 'rel', 'src', 'alt', 'loading',
          'class', 'style', 'disabled', 'checked', 'start', 'align',
          'data-filename', 'data-highlight-lines', 'data-highlighted',
          'aria-label', 'aria-live', 'aria-busy', 'role'
        ],
        FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form', 'frame', 'frameset'],
        FORBID_ATTR: ['on*']
      });
    } else {
      // Fallback sanitization
      const temp = document.createElement('div');
      temp.innerHTML = raw;
      // Remove dangerous elements
      temp.querySelectorAll('script, style, iframe, object, embed, form, input:not([type="checkbox"])').forEach((el) => el.remove());
      // Remove inline event handlers
      temp.querySelectorAll('[onclick],[onerror],[onload],[onmouseover],[onmouseenter],[onmouseleave]').forEach((el) => {
        [...el.attributes].forEach((attr) => {
          if (attr.name.startsWith('on')) el.removeAttribute(attr.name);
        });
      });
      temp.querySelectorAll('a[href^="javascript:"]').forEach((el) => el.removeAttribute('href'));
      safeHtml = temp.innerHTML;
    }

    return safeHtml;
  } catch (e) {
    console.warn('Markdown parse error:', e);
    // Fallback: escaped text with line breaks
    return escapeHtml(markdown || '').replace(/\n/g, '<br>');
  }
}

/**
 * Apply syntax highlighting and code block enhancements to a container.
 * @param {HTMLElement} container - Container element with rendered markdown
 * @returns {Promise<void>}
 */
export async function enhanceCodeBlocks(container) {
  checkLibraries();
  if (!_hljs) return;

  const codeBlocks = container.querySelectorAll('pre code:not([data-highlighted])');

  for (const codeEl of codeBlocks) {
    try {
      // Mark as processed to avoid double-enhancement
      codeEl.setAttribute('data-highlighted', 'true');

      // Apply syntax highlighting
      _hljs.highlightElement(codeEl);
    } catch (e) {
      // Unknown language, leave unhighlighted
    }

    // Wrap code block with header and copy button (only once)
    const pre = codeEl.parentElement;
    if (!pre || pre.classList.contains('code-block')) continue;
    if (pre.parentElement?.classList.contains('code-block')) continue;

    const langMatch = /language-(\w+)/.exec(codeEl.className || '');
    const lang = langMatch ? langMatch[1] : 'text';

    // Extract metadata from data attributes
    const filename = codeEl.getAttribute('data-filename');
    const highlightLinesAttr = codeEl.getAttribute('data-highlight-lines');
    const highlightLines = highlightLinesAttr ? new Set(highlightLinesAttr.split(',').map(Number).filter(n => !isNaN(n))) : null;

    const block = document.createElement('div');
    block.className = 'code-block';
    let headerContent = `<span>${escapeHtml(lang)}</span>`;
    if (filename) {
      headerContent = `<span class="code-filename">${escapeHtml(filename)}</span>` + headerContent;
    }
    block.innerHTML = `
      <div class="code-block-header">
        ${headerContent}
        <button class="copy-code-btn" title="Copy code" aria-label="Copy code">
          <i class="fa-regular fa-copy"></i><span>Copy</span>
        </button>
      </div>
    `;

    pre.replaceWith(block);
    block.appendChild(pre);

    // Apply line highlighting if specified
    if (highlightLines && highlightLines.size > 0) {
      block.classList.add('has-line-highlights');
      // Wrap each line in a span for line numbering and highlighting
      wrapLinesWithNumbers(codeEl, highlightLines);
    }

    // Copy button handler - copies only the code text (without line numbers)
    const copyBtn = block.querySelector('.copy-code-btn');
    if (copyBtn) {
      copyBtn.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const codeText = codeEl.textContent;

        try {
          await navigator.clipboard.writeText(codeText);
          btn.classList.add('copied');
          btn.innerHTML = `<i class="fa-solid fa-check"></i><span>Copied</span>`;
          setTimeout(() => {
            btn.classList.remove('copied');
            btn.innerHTML = `<i class="fa-regular fa-copy"></i><span>Copy</span>`;
          }, 1600);
        } catch {
          // Fallback: select text
          const range = document.createRange();
          range.selectNodeContents(codeEl);
          const sel = window.getSelection();
          sel?.removeAllRanges();
          sel?.addRange(range);
        }
      });
    }
  }
}

/**
 * Wrap code lines in spans for line numbering and highlighting.
 * @param {HTMLElement} codeEl - The code element
 * @param {Set<number>} highlightLines - Set of line numbers to highlight
 */
function wrapLinesWithNumbers(codeEl, highlightLines) {
  // Get the text content and split by lines
  const text = codeEl.textContent;
  if (!text) return;

  const lines = text.split('\n');
  const fragment = document.createDocumentFragment();

  lines.forEach((line, index) => {
    const lineNum = index + 1;
    const lineEl = document.createElement('span');
    lineEl.className = 'hljs-ln';
    if (highlightLines.has(lineNum)) {
      lineEl.classList.add('highlighted');
    }
    lineEl.innerHTML = line === '' ? '<br>' : line;
    fragment.appendChild(lineEl);
    if (index < lines.length - 1) {
      fragment.appendChild(document.createTextNode('\n'));
    }
  });

  // Replace the code element's content with the line-wrapped version
  codeEl.innerHTML = '';
  codeEl.appendChild(fragment);
}

/**
 * Render markdown to a DOM element with syntax highlighting.
 * @param {string} markdown - Markdown text
 * @returns {Promise<HTMLElement>} - Wrapper element with rendered content
 */
export async function renderMarkdownToElement(markdown) {
  const html = parseMarkdown(markdown);
  const wrapper = document.createElement('div');
  wrapper.innerHTML = html;
  await enhanceCodeBlocks(wrapper);
  return wrapper;
}

/**
 * Render markdown to HTML string (for message rendering).
 * This is the FINAL RENDER PASS - applies full markdown + enhancements.
 * @param {string} markdown - Markdown text
 * @returns {string} - HTML string
 */
export function renderMarkdown(markdown) {
  const temp = document.createElement('div');
  temp.innerHTML = parseMarkdown(markdown);

  // Apply syntax highlighting and code block wrapping synchronously
  checkLibraries();
  if (_hljs) {
    // Find all code blocks and process them
    temp.querySelectorAll('pre code').forEach((codeEl) => {
      // Skip if already enhanced
      if (codeEl.hasAttribute('data-highlighted')) return;

      try {
        codeEl.setAttribute('data-highlighted', 'true');
        _hljs.highlightElement(codeEl);
      } catch {
        // ignore
      }

      const pre = codeEl.parentElement;
      if (pre && !pre.classList.contains('code-block') && !pre.parentElement?.classList.contains('code-block')) {
        const langMatch = /language-(\w+)/.exec(codeEl.className || '');
        const lang = langMatch ? langMatch[1] : 'text';

        // Extract metadata from data attributes
        const filename = codeEl.getAttribute('data-filename');
        const highlightLinesAttr = codeEl.getAttribute('data-highlight-lines');
        const highlightLines = highlightLinesAttr ? new Set(highlightLinesAttr.split(',').map(Number).filter(n => !isNaN(n))) : null;

        const block = document.createElement('div');
        block.className = 'code-block';
        let headerContent = `<span>${escapeHtml(lang)}</span>`;
        if (filename) {
          headerContent = `<span class="code-filename">${escapeHtml(filename)}</span>` + headerContent;
        }
        block.innerHTML = `
          <div class="code-block-header">
            ${headerContent}
            <button class="copy-code-btn"><i class="fa-regular fa-copy"></i><span>Copy</span></button>
          </div>
        `;

        // Apply line highlighting if specified
        if (highlightLines && highlightLines.size > 0) {
          block.classList.add('has-line-highlights');
          // Wrap lines for highlighting
          wrapLinesWithNumbers(codeEl, highlightLines);
        }

        pre.replaceWith(block);
        block.appendChild(pre);
      }
    });
  }

  return temp.innerHTML;
}

/**
 * Render markdown for STREAMING - produces visually stable output during incremental updates.
 * Uses marked.js 15+ parse with fallback to safe escaped rendering on parse errors.
 * Does NOT apply syntax highlighting during streaming (done in final pass).
 * Uses a simple cache to avoid re-rendering when markdown hasn't meaningfully changed.
 * @param {string} markdown - Accumulated markdown text so far
 * @returns {string} - HTML string safe for streaming display
 */
export function renderMarkdownStream(markdown) {
  // Fast path: if markdown is identical to last render, return cached HTML
  if (markdown === _streamCache.markdown) {
    return _streamCache.html;
  }

  // Fast path: if markdown is just growing by appending text (no structural changes),
  // we can do an incremental update. Check if the new markdown starts with the old.
  // This covers the common case of text deltas being appended.
  if (markdown.startsWith(_streamCache.markdown) && _streamCache.markdown.length > 0) {
    // Only the appended part needs checking - for pure text appends, we can avoid full re-parse
    // But Markdown is not reliably incremental (e.g., ``` could start a code block),
    // so we still do a full re-parse for safety. The cache above handles the no-change case.
  }

  checkLibraries();
  configureMarked();

  if (!_marked?.parse) {
    // Fallback: escaped text with line breaks
    const html = escapeHtml(markdown || '').replace(/\n/g, '<br>');
    _streamCache = { markdown, html };
    return html;
  }

  try {
    // Parse with marked - marked 15 handles incomplete markdown reasonably
    const raw = _marked.parse(markdown || '');

    // Sanitize but allow basic markdown elements
    let safeHtml = raw;
    if (_DOMPurify?.sanitize) {
      safeHtml = _DOMPurify.sanitize(raw, {
        USE_PROFILES: { html: true },
        ALLOWED_TAGS: [
          'p', 'br', 'strong', 'em', 'del', 'code', 'pre', 'blockquote',
          'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
          'ul', 'ol', 'li', 'a', 'hr',
          'div', 'span', 'input', 'details', 'summary'
        ],
        ALLOWED_ATTR: [
          'href', 'title', 'target', 'rel', 'class', 'style',
          'disabled', 'checked', 'start', 'align',
          'data-filename', 'data-highlight-lines', 'data-highlighted',
          'aria-label', 'aria-live', 'aria-busy', 'role'
        ],
        FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form', 'frame', 'frameset'],
        FORBID_ATTR: ['on*']
      });
    } else {
      const temp = document.createElement('div');
      temp.innerHTML = raw;
      temp.querySelectorAll('script, style, iframe, object, embed, form, input:not([type="checkbox"])').forEach((el) => el.remove());
      temp.querySelectorAll('[onclick],[onerror],[onload],[onmouseover],[onmouseenter],[onmouseleave]').forEach((el) => {
        [...el.attributes].forEach((attr) => {
          if (attr.name.startsWith('on')) el.removeAttribute(attr.name);
        });
      });
      temp.querySelectorAll('a[href^="javascript:"]').forEach((el) => el.removeAttribute('href'));
      safeHtml = temp.innerHTML;
    }

    // Cache the result
    _streamCache = { markdown, html: safeHtml };
    return safeHtml;
  } catch (e) {
    // On parse error (incomplete markdown), fallback to safe escaped rendering
    const html = escapeHtml(markdown || '').replace(/\n/g, '<br>');
    _streamCache = { markdown, html };
    return html;
  }
}

/**
 * Clear the streaming render cache.
 * Call this when starting a new message to avoid cross-message cache pollution.
 */
export function clearStreamCache() {
  _streamCache = { markdown: '', html: '' };
}

/**
 * Set code theme dynamically.
 * @param {string} theme - Theme name (e.g., 'github-dark', 'atom-one-dark')
 */
export function setCodeTheme(theme) {
  const themeEl = document.getElementById('hljs-theme');
  const urls = {
    'github-dark': 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.11.0/styles/github-dark.min.css',
    'atom-one-dark': 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.11.0/styles/atom-one-dark.min.css',
    'nord': 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.11.0/styles/nord.min.css',
    'dracula': 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.11.0/styles/dracula.min.css',
    'github': 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.11.0/styles/github.min.css',
  };

  if (themeEl && urls[theme]) {
    themeEl.href = urls[theme];
    document.body.setAttribute('data-code-theme', theme);
  }
}

/**
 * Check if markdown libraries are available.
 */
export function areMarkdownLibsLoaded() {
  checkLibraries();
  return !!_marked && !!_hljs;
}

/**
 * Generate recommended Content Security Policy directives for markdown content.
 * Returns an object with CSP directives that can be used in a meta tag or header.
 * Note: 'unsafe-inline' for styles is needed for highlight.js dynamic styling.
 * @returns {Object} CSP directives
 */
export function getMarkdownCSP() {
  // Allow http: for local backend connections (e.g., http://127.0.0.1:8001)
  const isLocalhost = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
  const connectSrc = isLocalhost ? "'self' http: https:" : "'self' https:";

  return {
    'script-src': "'self' 'unsafe-eval' https://cdnjs.cloudflare.com",
    'style-src': "'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com",
    'font-src': "'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com",
    'img-src': "'self' data: https:",
    'connect-src': connectSrc,
    'frame-ancestors': "'none'",
    'base-uri': "'self'",
    'form-action': "'self'"
  };
}

/**
 * Inject CSP meta tag for markdown content security.
 * Call this during app initialization to add CSP for markdown-rendered content.
 * @param {Object} customDirectives - Additional CSP directives to merge
 */
export function injectMarkdownCSP(customDirectives = {}) {
  const csp = { ...getMarkdownCSP(), ...customDirectives };
  const policy = Object.entries(csp)
    .map(([key, value]) => `${key} ${value}`)
    .join('; ');

  // Remove any existing CSP meta tag to avoid duplicates
  const existing = document.querySelector('meta[http-equiv="Content-Security-Policy"]');
  if (existing) existing.remove();

  const meta = document.createElement('meta');
  meta.httpEquiv = 'Content-Security-Policy';
  meta.content = policy;
  document.head.appendChild(meta);

  console.debug('[Markdown] CSP injected for markdown content security');
}

/**
 * Final render pass for completed messages.
 * Re-renders the complete markdown with full enhancements.
 * @param {HTMLElement} messageNode - The assistant message DOM node
 * @param {string} markdown - Complete markdown source
 * @returns {Promise<void>}
 */
export async function finalizeMarkdownRender(messageNode, markdown) {
  // Target the semantic response container
  const responseEl = messageNode.querySelector('.assistant-response');
  if (!responseEl) return;

  try {
    // Full render with all enhancements
    const html = renderMarkdown(markdown);
    responseEl.innerHTML = html;

    // Apply async enhancements (highlighting is sync in renderMarkdown,
    // but we keep this for future async enhancements)
    await enhanceCodeBlocks(responseEl);
  } catch (e) {
    console.error('Final markdown render error:', e);
    // Leave existing content on error
  }
}