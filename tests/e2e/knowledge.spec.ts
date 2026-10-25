/**
 * Phase 2 remainder spec (not part of the smoke gate — run it the same
 * way run_smoke.sh runs smoke.spec.ts, against a fresh mock backend).
 *
 * Opens the Knowledge tab, checks the Phase 2 sections render
 * (Retrieve documents, Add from URL, Export button in Memories),
 * and runs a retrieve query against the empty index, which must
 * return the honest empty state, not an error.
 *
 * FAILS on console.error / pageerror, or on HTTP >= 400 after login.
 */
import { test, expect, Page } from '@playwright/test';

test.use({
  launchOptions: {
    args: ['--disable-http-cache', '--disk-cache-size=1'],
  },
});

const FRONTEND_URL = process.env.E2E_FRONTEND_URL || 'http://127.0.0.1:5500';
const BACKEND_URL = process.env.E2E_BACKEND_URL || 'http://127.0.0.1:8001';
const PASS = 'Knowledge-Test-Password-123';
const USER = 'knowledgeuser';

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

test('Knowledge: Phase 2 sections + empty-index retrieve', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  await page.locator('#tabAdd').click();
  await page.locator('[data-tab-tool="knowledge"]').click();
  await page.waitForTimeout(3000);

  await expect(page.getByRole('heading', { name: 'Retrieve documents' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Add from URL' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Export' })).toBeVisible();
  await expect(page.locator('#knRetrieveQ')).toBeVisible();
  await expect(page.locator('#knIngestUrl')).toBeVisible();

  // Empty index: retrieve must show the honest empty state, not an error.
  await page.fill('#knRetrieveQ', 'photosynthesis');
  await page.locator('#knRetrieveBtn').click();
  await expect(page.locator('#knRetrieveResults')).toContainText('No matching documents', { timeout: 20000 });

  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.consoleErrors, `console.error: ${JSON.stringify(ctx.consoleErrors)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
});
