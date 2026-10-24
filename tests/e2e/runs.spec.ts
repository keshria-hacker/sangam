/**
 * Phase 1 Runs centre spec (not part of the smoke gate — run it the same
 * way run_smoke.sh runs smoke.spec.ts, against a fresh mock backend).
 *
 * Opens the Runs tab from the tab picker, checks the three sections
 * (live runs, history, artifacts) render with labelled controls, checks
 * accessibility basics (headings, aria-labels on every action button),
 * and captures a screenshot for visual review at
 * tests/e2e/screenshots/phase1-runs.png.
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
const PASS = 'Runs-Test-Password-123';
const USER = 'runsuser';

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

test('Runs centre: tab, sections, labelled controls, screenshot', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  await page.locator('#tabAdd').click();
  await page.locator('[data-tab-tool="runs"]').click();
  await page.waitForTimeout(3000);

  await expect(page.getByRole('heading', { name: 'Runs centre' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Live runs' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Run history' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Artifacts' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Refresh runs and artifacts' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Delete stale artifacts' })).toBeVisible();
  // Every button inside the Runs tab must carry an accessible label.
  const unlabeled = await page.evaluate(() => {
    const section = [...document.querySelectorAll('section')].find((s) =>
      (s.textContent || '').includes('Runs centre'));
    if (!section) return ['Runs section not found'];
    return [...section.querySelectorAll('button')]
      .filter((b) => !(b.getAttribute('aria-label') || (b.textContent || '').trim()))
      .map((b) => b.outerHTML.slice(0, 120));
  });
  expect(unlabeled, `unlabeled buttons in Runs tab: ${JSON.stringify(unlabeled)}`).toEqual([]);

  await page.screenshot({ path: 'tests/e2e/screenshots/phase1-runs.png' });
  // Phase 1 remainder, visual regression: Playwright's built-in
  // screenshot comparison. The baseline lives in
  // tests/e2e/runs.spec.ts-snapshots/ (committed) and is compared on
  // every run; 2% pixel tolerance absorbs font anti-aliasing only.
  // The Runs tab is deterministic on a fresh DB (empty states), so a
  // diff here means the layout actually changed.
  await expect(page).toHaveScreenshot('runs-centre.png', { maxDiffPixelRatio: 0.02 });
  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.consoleErrors, `console.error: ${JSON.stringify(ctx.consoleErrors)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
});

test('Runs centre: mobile 390px via composer Runs button', async ({ page }) => {
  test.setTimeout(180000);
  ctx.badResponses = []; ctx.consoleErrors = []; ctx.pageErrors = [];
  attachGuards(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await register(page);
  // Phase 1 remainder composition: the composer Runs pill opens the
  // Runs tab without the tab picker — the chat -> runs path.
  await page.locator('#runsBtn').click();
  await page.waitForTimeout(3000);
  await expect(page.getByRole('heading', { name: 'Runs centre' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Refresh runs and artifacts' })).toBeVisible();
  // No horizontal overflow on a narrow viewport (responsive rule).
  const overflow = await page.evaluate(() => {
    const el = document.documentElement;
    return el.scrollWidth - el.clientWidth;
  });
  expect(overflow, `horizontal overflow at 390px: ${overflow}px`).toBeLessThanOrEqual(1);
  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.consoleErrors, `console.error: ${JSON.stringify(ctx.consoleErrors)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
});
