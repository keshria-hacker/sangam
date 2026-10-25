/**
 * Batch 7 Model Fit + Writing Quality spec (not part of the smoke gate —
 * run it the same way run_smoke.sh runs smoke.spec.ts, against a fresh
 * mock backend).
 *
 * Model Fit: Settings > Models & Routing shows the hardware summary and
 * Recommend returns a ranked list — asserted on rendered content, not on
 * real GPU numbers (the mock backend's host has no GPU; VRAM renders as
 * "unknown", which is the honest value).
 * Writing: Settings > Voice & Output shows the De-slop preview; Detect
 * leaves the text unchanged and lists a pattern, Edit shows what changed.
 *
 * FAILS on console.error / pageerror, or on HTTP >= 400 after login
 * (401 before login and 403 on duplicate register are allowed).
 */
import { test, expect, Page } from '@playwright/test';

test.use({
  launchOptions: {
    args: ['--disable-http-cache', '--disk-cache-size=1'],
  },
});

const FRONTEND_URL = process.env.E2E_FRONTEND_URL || 'http://127.0.0.1:5500';
const BACKEND_URL = process.env.E2E_BACKEND_URL || 'http://127.0.0.1:8001';
const PASS = 'Fit-Test-Password-123';
const USER = 'fituser';

const ctx = { badResponses: [] as string[], consoleErrors: [] as string[], pageErrors: [] as string[], loggedIn: false };

function attachGuards(page: Page) {
  page.on('response', (r) => {
    const status = r.status();
    if (status >= 400) {
      if (status === 401 && !ctx.loggedIn) return;
      if (status === 403 && r.url().includes('/auth/register')) return;
      // PRE-EXISTING (not Batch 7): the Settings > Models routing section
      // (features/routing/routes.js) polls /analytics/summary, which has
      // no backend route (only /analytics/stats exists). Ignored here so
      // this spec judges Batch 7 code, not that defect; reported to the
      // coordinator for a separate fix.
      if (r.url().includes('/analytics/summary') && status === 404) return;
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
  // Fresh login state per test: ctx is module-shared, and without this
  // reset the pre-login /analytics/summary 401 (usage meter, expected
  // before auth) from a later test would be mis-flagged as post-login
  // (same latent bug fixed in runs.spec.ts).
  ctx.loggedIn = false;
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

async function openSettings(page: Page) {
  await page.locator('[data-nav="settings"]').click();
  await page.waitForTimeout(2000);
}

test('Model Fit: hardware summary renders, recommend returns a ranked list', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);
  await openSettings(page);

  await page.locator('[data-cat="models"]').click();
  await page.waitForTimeout(2000);
  await expect(page.locator('.fit-section')).toBeVisible({ timeout: 20000 });
  await expect(page.locator('[data-fit-hardware]')).toContainText('Hardware:', { timeout: 20000 });

  await page.getByRole('button', { name: 'Recommend models' }).click();
  await expect(page.locator('.fit-row').first()).toBeVisible({ timeout: 20000 });
  const rankedText = await page.locator('[data-fit-recommend-out]').innerText();
  expect(rankedText).toMatch(/fits on this machine|does not fit on this machine/);

  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.consoleErrors, `console.error: ${JSON.stringify(ctx.consoleErrors)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
});

test('Writing preview: detect leaves text unchanged, edit shows what changed', async ({ page }) => {
  test.setTimeout(180000);
  ctx.badResponses = []; ctx.consoleErrors = []; ctx.pageErrors = [];
  attachGuards(page);
  await register(page);
  await openSettings(page);

  // Settings control center: the old 'voice_output' category was
  // renamed to 'voice' (settings_schema.js legacy map); the De-slop
  // preview renders in the voice category (settings_page.js).
  await page.locator('[data-cat="voice"]').click();
  await page.waitForTimeout(2000);
  await expect(page.getByRole('heading', { name: 'De-slop preview' })).toBeVisible({ timeout: 20000 });

  const passage = 'Delve into the rich tapestry of this crucial landscape.';
  await page.locator('[data-qp-input]').fill(passage);

  await page.locator('[data-qp-mode]').selectOption('detect');
  await page.getByRole('button', { name: 'Preview cleanup' }).click();
  await expect(page.locator('[data-qp-out]')).toContainText('Detect mode', { timeout: 20000 });
  await expect(page.locator('[data-qp-out]')).toContainText('delve-into');
  await expect(page.locator('[data-qp-out]')).toContainText(passage);

  await page.locator('[data-qp-mode]').selectOption('edit');
  await page.getByRole('button', { name: 'Preview cleanup' }).click();
  await expect(page.locator('[data-qp-out]')).toContainText('What changed', { timeout: 20000 });
  await expect(page.locator('[data-qp-out]')).toContainText('delve-into');

  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.consoleErrors, `console.error: ${JSON.stringify(ctx.consoleErrors)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
});
