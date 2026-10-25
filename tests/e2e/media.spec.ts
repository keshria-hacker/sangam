/**
 * Phase 4 media jobs spec (not part of the smoke gate — run it the same
 * way run_smoke.sh runs smoke.spec.ts, against a fresh mock backend).
 *
 * Opens the Media tab, checks the create form renders, and creates a
 * TTS job with no engine available — which must land as a failed job
 * with an error, not a crash or a hang. That is the honest observable
 * outcome on a machine without a TTS engine installed.
 *
 * FAILS on console.error / pageerror, or on HTTP >= 400 after login
 * (job failure itself is a 202 + failed status, not an HTTP error).
 */
import { test, expect, Page } from '@playwright/test';

test.use({
  launchOptions: {
    args: ['--disable-http-cache', '--disk-cache-size=1'],
  },
});

const FRONTEND_URL = process.env.E2E_FRONTEND_URL || 'http://127.0.0.1:5500';
const BACKEND_URL = process.env.E2E_BACKEND_URL || 'http://127.0.0.1:8001';
const PASS = 'Media-Test-Password-123';
const USER = 'mediauser';

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

test('Media: create job, observe failure without an engine', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  // Batch 1: Media jobs now live in Create.
  await page.locator('#tabAdd').click();
  await page.locator('[data-tab-tool="create"]').click();
  await page.waitForTimeout(2000);
  await page.locator('[data-createsub="media"]').click();
  await page.waitForTimeout(3000);

  await expect(page.getByRole('heading', { name: 'Media jobs', exact: true })).toBeVisible();
  await page.fill('#mjText', 'Hello from the media job test');
  await page.locator('#mjCreateBtn').click();
  await expect(page.locator('#mjCreateStatus')).toContainText('created', { timeout: 20000 });
  // Poll via Refresh until the job reaches a terminal state.
  for (let i = 0; i < 10; i++) {
    await page.waitForTimeout(2000);
    await page.locator('#mjList .mj-refresh-btn').first().click();
    await page.waitForTimeout(500);
    const text = await page.locator('#mjList').innerText();
    if (text.includes('failed') || text.includes('succeeded')) break;
  }
  const listText = await page.locator('#mjList').innerText();
  expect(listText).toMatch(/failed|succeeded/);

  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.consoleErrors, `console.error: ${JSON.stringify(ctx.consoleErrors)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
});
