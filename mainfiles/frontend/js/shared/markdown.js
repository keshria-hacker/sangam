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

/**
 * Preprocess markdown to handle KaTeX math expressions.
 * Converts $$...$$ and $...$ to HTML spans that KaTeX can render.
 */
function preprocessKaTeX(markdown) {
  // Handle display math: $$...$$
  // We need to be careful to not match inside code blocks
  let processed = markdown;

  // Split by code blocks to avoid processing math inside them
  const codeBlockRegex = /(```[\s\S]*?```)|(`[^`]*`)/g;
  const parts = [];
  let lastIndex = 0;

  let match;
  while ((match = codeBlockRegex.exec(processed)) !== null) {
    // Add text before the code block
    parts.push(processed.slice(lastIndex, match.index));
    // Add the code block unchanged
    parts.push(match[0]);
    lastIndex = codeBlockRegex.lastIndex;
  }

  // Add remaining text after last code block
  parts.push(processed.slice(lastIndex));

  // Process each non-code part for math
  for (let i = 0; i < parts.length; i++) {
    // Skip code blocks (odd indices)
    if (i % 2 === 0) {
      let text = parts[i];

      // Process display math: $$...$$
      text = text.replace(/\$\$([\s\S]*?)\$\$/g, (match, mathContent) => {
        // Escape HTML in math content to prevent XSS
        const escaped = escapeHtml(mathContent);
        return `<span class="math-display">${escaped}</span>`;
      });

      // Process inline math: $...$
      text = text.replace(/(?<!\\)\$([^\$\s][^$]*?[^\$\s])\$/g, (match, mathContent) => {
        // Escape HTML in math content to prevent XSS
        const escaped = escapeHtml(mathContent);
        return `<span class="math-inline">${escaped}</span>`;
      });

      parts[i] = text;
    }
  }

  return parts.join('');
}

/**
 * Preprocess markdown to handle Mermaid diagram blocks.
 * Converts ```mermaid blocks to divs that Mermaid.js can render.
 */
function preprocessMermaid(markdown) {
  // Split by code blocks to find mermaid blocks
  const codeBlockRegex = /```(\w+)?\n([\s\S]*?)```/g;
  const parts = [];
  let lastIndex = 0;

  let match;
  while ((match = codeBlockRegex.exec(markdown)) !== null) {
    // Add text before the code block
    parts.push(markdown.slice(lastIndex, match.index));

    const lang = match[1] || '';
    const content = match[2];

    // If it's a mermaid block, convert to a div
    if (lang.trim() === 'mermaid') {
      // Escape HTML in content to prevent XSS
      const escapedContent = escapeHtml(content);
      parts.push(`<div class="mermaid-diagram">${escapedContent}</div>`);
    } else {
      // Keep regular code blocks unchanged
      parts.push(match[0]);
    }

    lastIndex = codeBlockRegex.lastIndex;
  }

  // Add remaining text after last code block
  parts.push(markdown.slice(lastIndex));

  return parts.join('');
}

/**
 * Render markdown to HTML with syntax highlighting.
 * Used for final render pass after streaming completes.
 */
export function parseMarkdown(markdown) {
  // Preprocess for KaTeX and Mermaid
  let processed = preprocessKaTeX(markdown);
  processed = preprocessMermaid(processed);

  // Convert to HTML using marked
  const html = marked.parse(processed);

  // Sanitize HTML to prevent XSS
  return DOMPurify.sanitize(html, {
    ADD_TAGS: ['math-display', 'math-inline', 'mermaid-diagram'],
    ADD_ATTR: ['class'],
  });
}

/**
 * Render markdown to HTML for streaming incremental updates.
 * Used during SSE streaming for visually stable updates.
 */
export function renderMarkdownStream(markdown) {
  // Preprocess for KaTeX and Mermaid
  let processed = preprocessKaTeX(markdown);
  processed = preprocessMermaid(processed);

  // Convert to HTML using marked
  const html = marked.parse(processed);

  // Sanitize HTML to prevent XSS (more permissive for streaming)
  return DOMPurify.sanitize(html, {
    ADD_TAGS: ['math-display', 'math-inline', 'mermaid-diagram'],
    ADD_ATTR: ['class'],
    KEEP_CONTENT: true,
  });
}

/**
 * Render markdown to HTML with syntax highlighting.
 * Alias for parseMarkdown for backward compatibility.
 */
export function renderMarkdown(markdown) {
  return parseMarkdown(markdown);
}

/**
 * Apply syntax highlighting to code blocks in a container element.
 * Should be called after markdown rendering is complete.
 */
export function enhanceCodeBlocks(container) {
  // Process all pre code blocks
  container.querySelectorAll('pre code').forEach((block) => {
    highlightElement(block);

    const pre = block.parentElement;
    if (!pre) return;

    // Wrap the pre element in a code-block div if not already wrapped
    let codeBlock = pre.parentElement;
    if (!codeBlock || !codeBlock.classList.contains('code-block')) {
      codeBlock = document.createElement('div');
      codeBlock.className = 'code-block';
      pre.parentNode.insertBefore(codeBlock, pre);
      codeBlock.appendChild(pre);
    }

    // Add copy button if not already present
    if (!codeBlock.querySelector('.copy-code-btn')) {
      const copyBtn = document.createElement('button');
      copyBtn.className = 'copy-code-btn';
      copyBtn.innerHTML = '<i class="fa-regular fa-copy"></i>';
      copyBtn.setAttribute('aria-label', 'Copy code');

      copyBtn.addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(block.textContent);
          copyBtn.innerHTML = '<i class="fa-solid fa-check"></i>';
          copyBtn.setAttribute('aria-label', 'Copied!');

          setTimeout(() => {
            copyBtn.innerHTML = '<i class="fa-regular fa-copy"></i>';
            copyBtn.setAttribute('aria-label', 'Copy code');
          }, 1600);
        } catch (err) {
          copyBtn.innerHTML = '<i class="fa-solid fa-times"></i>';
          copyBtn.setAttribute('aria-label', 'Copy failed');

          setTimeout(() => {
            copyBtn.innerHTML = '<i class="fa-regular fa-copy"></i>';
            copyBtn.setAttribute('aria-label', 'Copy code');
          }, 1600);
        }
      });

      codeBlock.appendChild(copyBtn);
    }
  });
}

/**
 * Apply syntax highlighting to a single code block element.
 */
export function highlightElement(element) {
  // Get the language class from the parent <pre> element
  const pre = element.parentElement;
  if (!pre) return;

  // Extract language from class (e.g., "language-javascript" -> "javascript")
  const languageMatch = pre.className.match(/language-(\w+)/);
  if (!languageMatch) return;

  const language = languageMatch[1];
  const normalizedLanguage = LANGUAGE_ALIASES[language] || language;

  // Only highlight if the language is supported by highlight.js
  if (SUPPORTED_LANGUAGES.has(normalizedLanguage)) {
    // Use highlight.js to highlight the code block
    if (typeof window !== 'undefined' && window.hljs) {
      window.hljs.highlightElement(element);
    }
  }
}

/**
 * Finalize markdown rendering after streaming completes.
 * Applies syntax highlighting and other final enhancements to rendered markdown.
 * @param {HTMLElement} container - The container element containing rendered markdown
 */
export function finalizeMarkdownRender(container) {
  // Apply syntax highlighting to code blocks
  enhanceCodeBlocks(container);
}/**
 * Clear the streaming markdown cache.
 * Called before starting a new generation to ensure clean state.
 */
export function clearStreamCache() {
  // No cache to clear for now, but keeping the function for compatibility
}

/**
 * Apply the code theme by swapping the highlight.js stylesheet.
 * @param {string} theme - 'dark' | 'light'
 */
export function setCodeTheme(theme) {
  const link = document.getElementById('hljs-theme');
  if (!link) return;
  const base = 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.11.0/styles/';
  link.href = theme === 'light' ? `${base}github.min.css` : `${base}github-dark.min.css`;
}

/**
 * True when marked + DOMPurify are available on the page.
 */
export function areMarkdownLibsLoaded() {
  return typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined';
}

/**
 * Build a CSP directive string suitable for the markdown pipeline
 * (CDN scripts + inline styles used by highlight.js / KaTeX output).
 */
export function getMarkdownCSP() {
  return [
    "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net",
    "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net",
    "font-src 'self' data: https://cdnjs.cloudflare.com https://cdn.jsdelivr.net",
  ].join('; ');
}

/**
 * Relax the page CSP so CDN markdown libraries and their output can load.
 * Called once at app boot, before the first render.
 */
export function injectMarkdownCSP() {
  let meta = document.querySelector('meta[http-equiv="Content-Security-Policy"]');
  if (!meta) {
    meta = document.createElement('meta');
    meta.setAttribute('http-equiv', 'Content-Security-Policy');
    document.head.appendChild(meta);
  }
  meta.setAttribute('content', getMarkdownCSP());
}
