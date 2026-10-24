/**
 * Batch 4 notebooks spec: Knowledge page -> Notebooks section ->
 * create notebook -> add a note -> retrieve shows the note ->
 * backlinks: note B linking [[A]] -> A's backlinks list B.
 * No LLM calls (no model is configured against the mock backend);
 * only real UI flows over the real API.
 */
import { test, expect, Page } from '@playwright/test';

test.use({
  launchOptions: {
    args: ['--disable-http-cache', '--disk-cache-size=1'],
  },
});

const FRONTEND_URL = process.env.E2E_FRONTEND_URL || 'http://127.0.0.1:5500';
const BACKEND_URL = process.env.E2E_BACKEND_URL || 'http://127.0.0.1:8001';
const PASS = 'Notebooks-Test-Password-123';
const USER = 'notebooksuser';

const ctx = { badResponses: [] as string[], consoleErrors: [] as string[], pageErrors: [] as string[], loggedIn: false };

function attachGuards(page: Page) {
  page.on('response', (r) => {
    const status = r.status();
    if (status >= 400) {
      if (status === 401 && !ctx.loggedIn) return;
      if (status === 403 && r.url().includes('/auth/register')) return;
      ctx.badResponses.push(`${r.request().method()} ${r.url()} -> ${status}`);
    }
  });
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      if (text.includes('Failed to load resource') || text.includes('net::ERR_')) return;
      ctx.consoleErrors.push(text.slice(0, 300));
    }
  });
  page.on('pageerror', (err) => ctx.pageErrors.push(String(err).slice(0, 300)));
}

async function register(page: Page) {
  const api = page.request;
  let resp = await api.post(`${BACKEND_URL}/api/auth/register`, {
    data: { username: USER, password: PASS },
  });
  if (resp.status() === 403) {
    resp = await api.post(`${BACKEND_URL}/api/auth/login`, {
      data: { username: USER, password: PASS },
    });
  }
  expect(resp.ok(), `API register/login failed: ${resp.status()}`).toBe(true);
  await page.goto(FRONTEND_URL);
  await page.waitForFunction(
    () => {
      const form = document.querySelector('#authForm');
      const overlay = document.querySelector('#authOverlay');
      return (form && !form.classList.contains('hidden')) ||
             (overlay && overlay.classList.contains('hidden'));
    },
    { timeout: 20000 },
  );
  if (await page.locator('#authOverlay.hidden').count()) {
    ctx.loggedIn = true;
    await page.waitForTimeout(1500);
    return;
  }
  await page.fill('#authUsername', USER);
  await page.fill('#authPassword', PASS);
  await page.click('#authSubmit');
  await expect(page.locator('#authOverlay')).toHaveClass(/hidden/, { timeout: 20000 });
  ctx.loggedIn = true;
  await page.waitForTimeout(1500);
}

test('Notebooks: create, note, retrieve, backlinks', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  await page.locator('#tabAdd').click();
  await page.locator('[data-tab-tool="knowledge"]').click();
  await page.waitForTimeout(3000);

  await expect(page.getByRole('heading', { name: 'Notebooks' })).toBeVisible();
  await expect(page.locator('#nbList')).toBeVisible();

  // Create a notebook (opens it on success).
  await page.fill('#nbName', 'E2E Research');
  await page.fill('#nbDesc', 'Spec notebook');
  await page.locator('#nbCreateBtn').click();
  await expect(page.locator('#nbSources')).toBeVisible({ timeout: 20000 });

  // Note A, then note B linking [[AlphaNote]].
  await page.fill('#nbNoteTitle', 'AlphaNote');
  await page.fill('#nbNoteContent', 'Alpha unique content zebra');
  await page.locator('#nbNoteBtn').click();
  await expect(page.locator('#nbNotes')).toContainText('AlphaNote', { timeout: 20000 });

  await page.fill('#nbNoteTitle', 'BetaNote');
  await page.fill('#nbNoteContent', 'See [[AlphaNote]] for context.');
  await page.locator('#nbNoteBtn').click();
  await expect(page.locator('#nbNotes')).toContainText('BetaNote', { timeout: 20000 });

  // Retrieve shows the note content.
  await page.fill('#nbRetrieveQ', 'zebra');
  await page.locator('#nbRetrieveBtn').click();
  await expect(page.locator('#nbRetrieveResults')).toContainText('Alpha unique content zebra', { timeout: 20000 });

  // A's backlinks list B.
  // Match on the title element, not row text: Beta's content itself
  // contains "[[AlphaNote]]", so a plain hasText would match both rows.
  await page.locator('#nbNotes .nb-row').filter({ has: page.locator('strong', { hasText: /^AlphaNote$/ }) }).locator('[data-nb-note-view]').click();
  await expect(page.locator('#nbBacklinks')).toContainText('BetaNote', { timeout: 20000 });

  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.consoleErrors, `console.error: ${JSON.stringify(ctx.consoleErrors)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
});
