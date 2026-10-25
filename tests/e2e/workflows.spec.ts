/**
 * Phase 3 workflows spec (not part of the smoke gate — run it the same
 * way run_smoke.sh runs smoke.spec.ts, against a fresh mock backend).
 *
 * Creates a workflow from the pre-filled example, runs it through the
 * UI, and checks the run shows succeeded with per-node results —
 * the full chat-free path: build -> run -> inspect, in the browser.
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
const PASS = 'Workflows-Test-Password-123';
const USER = 'workflowsuser';

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

test('Workflows: create, run, inspect nodes', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  // Batch 1: Workflows is now a section inside Work.
  await page.locator('#tabAdd').click();
  await page.locator('[data-tab-tool="work"]').click();
  await page.waitForTimeout(2000);
  await page.locator('[data-worksection="workflows"]').click();
  await page.waitForTimeout(3000);

  await expect(page.getByRole('heading', { name: 'Workflows', exact: true })).toBeVisible();
  await page.fill('#wfName', 'Browser greet');
  await page.locator('#wfCreateBtn').click();
  await expect(page.locator('#wfCreateStatus')).toContainText('Created', { timeout: 20000 });
  await expect(page.locator('#wfList')).toContainText('Browser greet', { timeout: 20000 });

  // Run with input Ada; the example workflow uppercases the greeting.
  const row = page.locator('#wfList .kn-mem', { hasText: 'Browser greet' }).first();
  await row.locator('.wf-run-input').fill('{"name": "Ada"}');
  await row.locator('.wf-run-btn').click();
  await page.waitForTimeout(2000);
  await expect(page.locator('#wfRuns')).toContainText('succeeded', { timeout: 20000 });
  await expect(page.locator('#wfRuns')).toContainText('greet: succeeded', { timeout: 20000 });
  await expect(page.locator('#wfRuns')).toContainText('shout: succeeded', { timeout: 20000 });

  // Batch 3: canvas opens for the same workflow, shows both nodes, saves.
  await row.locator('.wf-canvas-btn').click();
  await expect(page.locator('#wfCanvasArea [data-node="greet"]')).toBeVisible({ timeout: 20000 });
  await expect(page.locator('#wfCanvasArea [data-node="shout"]')).toBeVisible();
  await page.locator('#wfCanvasSaveBtn').click();
  await expect(page.locator('#wfCanvasStatus')).toContainText('Saved', { timeout: 20000 });

  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.consoleErrors, `console.error: ${JSON.stringify(ctx.consoleErrors)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
});
