/**
 * Batch 5 Skills + Engineering spec (not part of the smoke gate — run it
 * the same way run_smoke.sh runs smoke.spec.ts, against a fresh mock
 * backend).
 *
 * - Library > Skills shows the engineering pack (and the Skills v2
 *   sections: recommendations, packs, individual skills).
 * - Run checks on one individual skill and see results.
 * - Create an engineering pipeline, advance grill -> brainstorm, see stages.
 * - Generate a docx via the generate endpoint with the browser session
 *   (no Library generate button exists in v1, so the endpoint is
 *   asserted through page.request with the session token).
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
const PASS = 'Skills-Test-Password-123';
const USER = 'skillsuser';

const ctx = { badResponses: [] as string[], consoleErrors: [] as string[], pageErrors: [] as string[], loggedIn: false, csrfToken: '' };

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
  try {
    const body = await resp.json();
    if (body.csrf_token) ctx.csrfToken = body.csrf_token;
  } catch { /* session token comes from localStorage instead */ }
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

async function openLibrary(page: Page) {
  await page.locator('#tabAdd').click();
  await page.locator('[data-tab-tool="library"]').click();
  await page.waitForTimeout(3000);
}

async function openEngineering(page: Page) {
  await page.locator('#tabAdd').click();
  await page.locator('[data-tab-tool="work"]').click();
  await page.waitForTimeout(2000);
  await page.locator('[data-worksection="engineering"]').click();
  await page.waitForTimeout(2000);
}

test('Library Skills shows the engineering pack and Skills v2 sections', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);
  await openLibrary(page);

  await expect(page.getByRole('heading', { name: 'Skills v2 — server scan, lockfile, checks, packs, recommendations' })).toBeVisible({ timeout: 20000 });
  // The engineering pack card (registered into the extension registry).
  await expect(page.locator('[data-pack="engineering"]')).toBeVisible({ timeout: 20000 });
  await expect(page.locator('#libRecommend')).toContainText('Detected stack', { timeout: 20000 });
  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.consoleErrors, `console.error: ${JSON.stringify(ctx.consoleErrors)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
});

test('Run checks on one skill and see results', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);
  await openLibrary(page);

  const firstCard = page.locator('[data-ind-skill]').first();
  await expect(firstCard).toBeVisible({ timeout: 20000 });
  await firstCard.locator('[data-skill-checks]').click();
  await expect(firstCard.locator('[data-ind-detail]')).toContainText('passed', { timeout: 20000 });
  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
});

test('Engineering pipeline: create, advance grill -> brainstorm, see stages', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);
  await openEngineering(page);

  await expect(page.getByRole('heading', { name: 'Engineering' })).toBeVisible({ timeout: 20000 });
  await page.fill('#engTitleInput', 'E2E Pipeline');
  await page.fill('#engGoalInput', 'Prove the pipeline UI works');
  await page.locator('#engCreateForm button[type="submit"]').click();
  await expect(page.locator('.eng-card')).toContainText('E2E Pipeline', { timeout: 20000 });

  const card = page.locator('.eng-card', { hasText: 'E2E Pipeline' });
  await card.locator('[data-artifact]').fill('Grill decisions: scope agreed');
  await card.locator('[data-advance] button[type="submit"]').click();
  // Wait for the rendered stage block, not the "→ grill" header text
  // (which is visible before the advance lands — a race in v1 of this spec).
  await expect(card.locator('.eng-stage', { hasText: 'grill' }).first()).toBeVisible({ timeout: 20000 });
  await card.locator('[data-artifact]').fill('Brainstorm notes: three options');
  await card.locator('[data-advance] button[type="submit"]').click();
  await expect(card.locator('.eng-stage', { hasText: 'brainstorm' }).first()).toBeVisible({ timeout: 20000 });
  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
});

test('Generate a docx via the session-backed endpoint', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);
  // Session for page.request: fresh API login (its token + csrf), rather
  // than guessing which localStorage key the UI login stored the token in.
  const login = await page.request.post(`${BACKEND_URL}/api/auth/login`, {
    data: { username: USER, password: PASS },
  });
  expect(login.ok(), `API login failed: ${login.status()}`).toBe(true);
  const session = await login.json();
  const token = session.access_token;
  expect(token, 'no session token from login').toBeTruthy();
  const resp = await page.request.post(`${BACKEND_URL}/api/skills/documents/generate`, {
    headers: { Authorization: `Bearer ${token}`, 'X-CSRF-Token': session.csrf_token || ctx.csrfToken },
    data: { format: 'docx', title: 'E2E Doc', sections: [{ heading: 'Intro', body: 'Hello' }] },
  });
  expect(resp.status(), `generate failed: ${resp.status()}`).toBe(200);
  const disposition = resp.headers()['content-disposition'] || '';
  expect(disposition).toContain('E2E-Doc.docx');
  const body = await resp.body();
  expect(body.subarray(0, 2).toString()).toBe('PK');
  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
});
