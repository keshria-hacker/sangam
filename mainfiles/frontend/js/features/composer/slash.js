/**
 * Composer slash-command menu (UX-refine wave).
 *
 * Type "/" at the start of the composer (or after a space) and a menu of
 * real commands appears. Every command maps to an EXISTING frontend action
 * — a composer mode, a tools toggle, an existing destination, or Settings.
 * No command invents a backend endpoint and none opens a new destination.
 *
 * Keyboard: ArrowUp/ArrowDown to move, Enter/Tab to run, Esc to close.
 * The keydown handler is registered in the capture phase and calls
 * stopImmediatePropagation() while the menu is open, so Enter runs the
 * highlighted command instead of sending the message.
 */
import { showToast } from '../../shared/toast.js';
import { escapeHtml } from '../../shared/utils.js';

console.log('[Module] composer/slash.js loaded');

const COMMANDS = [
  { cmd: 'chat', label: 'Chat', desc: 'Normal conversation mode', run: () => setMode('chat') },
  { cmd: 'think', label: 'Think', desc: 'Deep reasoning, shows thinking', run: () => setMode('think') },
  { cmd: 'agent', label: 'Agent', desc: 'Agent mode — uses tools to get things done', run: () => setMode('agent') },
  { cmd: 'code', label: 'Code', desc: 'Code agent mode with file tools', run: () => setMode('code') },
  { cmd: 'research', label: 'Research', desc: 'Web research with citations', run: () => setMode('research') },
  { cmd: 'image', label: 'Image', desc: 'Generate images', run: () => setMode('image') },
  { cmd: 'council', label: 'Council', desc: 'Several AI helpers discuss and vote on your question (panel debate) — sends the agreed answer, not a normal reply', run: () => setMode('council') },
  { cmd: 'search', label: 'Search the web', desc: 'Turn on web search + Research mode', run: async () => { const { setToolEnabled } = await import('./popovers.js'); setToolEnabled('web_search', true); setMode('research'); } },
  { cmd: 'runs', label: 'Open Runs', desc: 'Live runs, history, and artifacts (Work → Activity)', run: () => openSection('work', 'activity') },
  { cmd: 'workflows', label: 'Open Workflows', desc: 'Build and run automations (Work → Workflows)', run: () => openSection('work', 'workflows') },
  { cmd: 'agents', label: 'Open Agents', desc: 'Agent teams and runs (Work → Agents)', run: () => openSection('work', 'agents') },
  { cmd: 'library', label: 'Open Library', desc: 'Skills, tools, extensions, templates', run: () => openTool('library') },
  { cmd: 'knowledge', label: 'Open Knowledge', desc: 'Memory, files, and retrieval', run: () => openTool('knowledge') },
  { cmd: 'create', label: 'Open Create', desc: 'Make images, audio, documents, designs', run: () => openTool('create') },
  { cmd: 'settings', label: 'Open Settings', desc: 'Providers, appearance, devices', run: () => openSettings() },
];

async function setMode(mode) {
  const { setMode: apply } = await import('./popovers.js');
  apply(mode);
}

async function openSection(tool, section) {
  const { showToolSection } = await import('../tabs/tabs.js');
  showToolSection(tool, section);
}

async function openTool(tool) {
  const { openToolTab } = await import('../tabs/tabs.js');
  openToolTab(tool);
}

async function openSettings() {
  const { openSettings: open } = await import('../settings/open.js');
  open();
}

export function getSlashCommands() { return COMMANDS.map((c) => `/${c.cmd}`); }

export function initSlashMenu(textarea) {
  if (!textarea || textarea.dataset.slashInit === '1') return;
  textarea.dataset.slashInit = '1';

  const composer = document.getElementById('composer') || textarea.parentElement;
  const menu = document.createElement('div');
  menu.className = 'slash-menu hidden';
  menu.setAttribute('role', 'listbox');
  menu.setAttribute('aria-label', 'Slash commands');
  composer.appendChild(menu);

  let items = [];
  let active = 0;
  let tokenStart = -1; // index in the textarea value where the "/" token starts

  function close() {
    menu.classList.add('hidden');
    menu.innerHTML = '';
    items = [];
    tokenStart = -1;
  }

  function render() {
    if (!items.length) { close(); return; }
    active = Math.max(0, Math.min(active, items.length - 1));
    menu.innerHTML = items.map((c, i) => `
      <button type="button" class="slash-item${i === active ? ' active' : ''}" role="option"
        aria-selected="${i === active}" data-cmd="${escapeHtml(c.cmd)}">
        <span><strong>/${escapeHtml(c.cmd)}</strong><small>${escapeHtml(c.desc)}</small></span>
        <span class="slash-item-label">${escapeHtml(c.label)}</span>
      </button>`).join('') +
      `<div class="slash-hint">↑↓ navigate · Enter select · Esc close</div>`;
    menu.classList.remove('hidden');
    menu.querySelectorAll('.slash-item').forEach((btn) => {
      btn.addEventListener('mousedown', (e) => {
        // mousedown, not click: the textarea would lose focus (and the
        // menu close) before a click fires.
        e.preventDefault();
        runCommand(items.find((c) => c.cmd === btn.dataset.cmd));
      });
    });
  }

  async function runCommand(command) {
    if (!command) return;
    const value = textarea.value;
    const before = tokenStart >= 0 ? value.slice(0, tokenStart) : value;
    const after = value.slice(textarea.selectionStart || value.length);
    textarea.value = before + after;
    close();
    textarea.focus();
    try {
      await command.run();
    } catch (err) {
      showToast({ type: 'error', title: `/${command.cmd} failed`, message: err?.message || String(err) });
    }
  }

  textarea.addEventListener('input', () => {
    const pos = textarea.selectionStart ?? textarea.value.length;
    const beforeCursor = textarea.value.slice(0, pos);
    const match = /(?:^|\s)\/([a-z0-9-]*)$/.exec(beforeCursor);
    if (!match) { close(); return; }
    tokenStart = pos - match[1].length - 1;
    const query = match[1].toLowerCase();
    items = COMMANDS.filter((c) => c.cmd.startsWith(query));
    active = 0;
    render();
  });

  textarea.addEventListener('keydown', (e) => {
    if (menu.classList.contains('hidden')) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault(); e.stopImmediatePropagation();
      active = (active + 1) % items.length; render();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault(); e.stopImmediatePropagation();
      active = (active - 1 + items.length) % items.length; render();
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault(); e.stopImmediatePropagation();
      runCommand(items[active]);
    } else if (e.key === 'Escape') {
      e.preventDefault(); e.stopImmediatePropagation();
      close();
    }
  }, true);

  document.addEventListener('click', (e) => {
    if (!menu.classList.contains('hidden') && !menu.contains(e.target) && e.target !== textarea) close();
  });
}
