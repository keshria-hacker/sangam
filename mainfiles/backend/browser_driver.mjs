// browser_driver.mjs — Batch 2 browser driver (Node + playwright-core).
//
// Reads ONE JSON object on stdin: { actions: [...], profileDir: "..." }
//   navigate  { url }
//   click     { selector }
//   type      { selector, text }
//   extract   { selector? }  -> page text (or element text)
//   screenshot { name? }     -> PNG under profileDir/screenshots/
//
// Uses an ISOLATED profile dir (a caller-supplied workspace dir), never
// the user's daily browser profile. Prints ONE JSON object on stdout:
//   { results: [{ action, ok, ... }] }
// and exits non-zero with { error } on stdout when the engine is
// unavailable, so the Python wrapper can return 503 instead of faking
// results. Chromium comes from the repo's node_modules (playwright-core)
// with the browser binary under ~/.cache/ms-playwright.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

function fail(message) {
  console.log(JSON.stringify({ error: message }));
  process.exit(3);
}

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (c) => { data += c; });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

function findChromiumExecutable() {
  if (process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH) {
    return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  }
  const cache = path.join(os.homedir(), '.cache', 'ms-playwright');
  if (!fs.existsSync(cache)) return null;
  for (const dir of fs.readdirSync(cache)) {
    if (!dir.startsWith('chromium')) continue;
    for (const candidate of [
      path.join(cache, dir, 'chrome-linux', 'chrome'),
      path.join(cache, dir, 'chrome-linux64', 'chrome'),
      path.join(cache, dir, 'chrome-mac', 'Chromium.app', 'Contents', 'MacOS', 'Chromium'),
    ]) {
      if (fs.existsSync(candidate)) return candidate;
    }
  }
  return null;
}

const main = async () => {
  let payload;
  try {
    payload = JSON.parse(await readStdin());
  } catch {
    fail('driver: stdin was not valid JSON');
    return;
  }
  const actions = payload.actions || [];
  const profileDir = payload.profileDir || path.join(os.tmpdir(), 'sangam-browser-profile');
  fs.mkdirSync(profileDir, { recursive: true });
  const shotDir = path.join(profileDir, 'screenshots');
  fs.mkdirSync(shotDir, { recursive: true });

  let chromium;
  try {
    const mod = await import('playwright-core');
    chromium = mod.chromium;
  } catch {
    fail('driver: playwright-core is not installed (repo node_modules missing)');
    return;
  }
  const executablePath = findChromiumExecutable();
  if (!executablePath) {
    fail('driver: no Chromium binary found under ~/.cache/ms-playwright');
    return;
  }

  let context;
  try {
    context = await chromium.launchPersistentContext(profileDir, {
      headless: true, executablePath,
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
    });
  } catch (err) {
    fail(`driver: failed to launch Chromium: ${err.message}`);
    return;
  }
  const page = context.pages()[0] || await context.newPage();
  const results = [];
  try {
    for (const a of actions) {
      try {
        if (a.action === 'navigate') {
          await page.goto(a.url, { waitUntil: 'domcontentloaded', timeout: 30000 });
          results.push({ action: 'navigate', ok: true, url: page.url(), title: await page.title() });
        } else if (a.action === 'click') {
          await page.click(a.selector, { timeout: 15000 });
          results.push({ action: 'click', ok: true, selector: a.selector });
        } else if (a.action === 'type') {
          await page.fill(a.selector, a.text ?? '', { timeout: 15000 });
          results.push({ action: 'type', ok: true, selector: a.selector });
        } else if (a.action === 'extract') {
          const text = a.selector
            ? await page.textContent(a.selector, { timeout: 15000 })
            : await page.evaluate(() => document.body ? document.body.innerText.slice(0, 8000) : '');
          results.push({ action: 'extract', ok: true, selector: a.selector || null, text: text || '' });
        } else if (a.action === 'screenshot') {
          const name = `${(a.name || 'shot').replace(/[^A-Za-z0-9._-]/g, '_')}.png`;
          const file = path.join(shotDir, name);
          await page.screenshot({ path: file, fullPage: false });
          results.push({ action: 'screenshot', ok: true, screenshot: file });
        } else {
          results.push({ action: a.action || '?', ok: false, error: 'unknown action' });
        }
      } catch (err) {
        results.push({ action: a.action || '?', ok: false, error: String(err.message || err).slice(0, 500) });
      }
    }
  } finally {
    await context.close();
  }
  console.log(JSON.stringify({ results }));
};

main();
