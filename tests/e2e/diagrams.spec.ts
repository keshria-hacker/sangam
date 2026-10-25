/**
 * Batch 7 Diagrams + Image Ops spec (not part of the smoke gate — run it
 * the same way run_smoke.sh runs smoke.spec.ts, against a fresh mock
 * backend).
 *
 * Diagrams: Create > Diagrams shows the catalogue, picking Flowchart
 * inserts its template, lint runs, and the Export SVG button is present.
 * Image Ops: Create > Image shows Vary/Upscale/Inpaint/Outpaint/Describe
 * controls. No generated image is asserted (no real engine in the mock
 * backend); the capability-message path is covered by pytest instead.
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
const PASS = 'Diagrams-Test-Password-123';
const USER = 'diagramsuser';

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

async function openCreate(page: Page) {
  await page.locator('[data-nav="studio"]').click();
  await page.waitForTimeout(2000);
  await page.locator('[data-dest-section="create"]').click();
  await page.waitForTimeout(2000);
}

test('Diagrams: catalogue -> flowchart template -> lint -> export buttons', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);
  await openCreate(page);

  await page.locator('[data-createsub="diagrams"]').click();
  await expect(page.locator('.diagrams-section')).toBeVisible({ timeout: 20000 });
  await expect(page.getByRole('button', { name: 'Flowchart' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Export SVG' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Export PNG' })).toBeVisible();

  await page.getByRole('button', { name: 'Flowchart' }).click();
  await expect(page.locator('[data-diag-editor]')).toHaveValue(/flowchart/);

  await page.getByRole('button', { name: 'Run lint' }).click();
  await expect(page.locator('[data-diag-lint-out]')).not.toBeEmpty({ timeout: 20000 });

  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.consoleErrors, `console.error: ${JSON.stringify(ctx.consoleErrors)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
});

test('Image Studio: Vary/Upscale/Inpaint/Outpaint/Describe controls exist', async ({ page }) => {
  test.setTimeout(180000);
  ctx.badResponses = []; ctx.consoleErrors = []; ctx.pageErrors = [];
  attachGuards(page);
  await register(page);
  await openCreate(page);

  await page.locator('[data-createsub="image"]').click();
  await expect(page.getByRole('button', { name: 'Vary', exact: true })).toBeVisible({ timeout: 20000 });
  await expect(page.getByRole('button', { name: 'Upscale', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Inpaint', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Outpaint', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Describe', exact: true })).toBeVisible();

  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.consoleErrors, `console.error: ${JSON.stringify(ctx.consoleErrors)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
});
