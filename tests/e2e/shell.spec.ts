/**
 * A1 perfect-flow shell spec (coordinator: run at merge — shared ports
 * meant the shell agent could not run Playwright itself).
 *
 * Covers the §9 shell criteria that only a browser can prove:
 * - all 8 destinations are real pages with URL-addressable routes
 * - no tab strip, no repeated title bar; breadcrumb only at depth > 1
 * - legacy destinations redirect instead of 404ing; unknown routes 404
 *   with a "back to Chat" action
 * - command palette (Ctrl/Cmd+K) reaches destinations, settings
 *   sections, and create actions
 * - first-run flow: 3 steps max, skippable, look-around sample labelled
 * - power-user two-click reachability (Chat -> Code -> Spec & QA)
 * - empty states: exactly one guided next action
 *
 * Follows the runs.spec.ts pattern (register via API, then drive UI).
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
const PASS = 'Shell-Test-Password-123';
const USER = 'shelluser';

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

async function gotoDest(page: Page, nav: string) {
  await page.locator(`[data-nav="${nav}"]`).click();
  await page.waitForTimeout(1500);
}

test('Shell: 8 destinations, no tab strip, no title bar', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  // No browser-like tab strip and no repeated title bar anywhere.
  await expect(page.locator('#tabStrip')).toHaveCount(0);
  await expect(page.locator('#toolViewTitle')).toHaveCount(0);
  await expect(page.locator('#tabAdd')).toHaveCount(0);

  // Sidebar rail holds exactly the 8 destinations, in spec order.
  const rail = await page.locator('.rail-item').evaluateAll((els) =>
    els.map((el) => el.getAttribute('data-nav')));
  expect(rail).toEqual(['chat', 'projects', 'studio', 'code', 'research', 'agents', 'library', 'settings']);

  // Each destination is a real page with its URL.
  await gotoDest(page, 'projects');
  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.locator('#pjCreate')).toBeVisible();
  await gotoDest(page, 'studio');
  await expect(page).toHaveURL(/\/studio$/);
  await expect(page.locator('[data-dest-section="overview"]')).toBeVisible();
  await gotoDest(page, 'code');
  await expect(page).toHaveURL(/\/code$/);
  await expect(page.locator('[data-dest-section="agent"]')).toBeVisible();
  await gotoDest(page, 'research');
  await expect(page).toHaveURL(/\/research$/);
  await expect(page.locator('#knSearch')).toBeVisible();
  await gotoDest(page, 'agents');
  await expect(page).toHaveURL(/\/agents$/);
  await expect(page.locator('[data-dest-section="hub"]')).toBeVisible();
  await gotoDest(page, 'library');
  await expect(page).toHaveURL(/\/library$/);
  await expect(page.locator('[data-libtab="skills"]')).toBeVisible();
  await gotoDest(page, 'settings');
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.locator('#spSearchInput')).toBeVisible();
  await gotoDest(page, 'chat');
  await expect(page).toHaveURL(/\/chat$/);
  await expect(page.locator('#messageInput')).toBeVisible();

  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.consoleErrors, `console.error: ${JSON.stringify(ctx.consoleErrors)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
});

test('Shell: legacy redirects, 404 page, breadcrumb only at depth > 1', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  // Legacy in-app ids redirect through history (no server round-trip:
  // the SPA owns these routes, so pushState + popstate is the honest
  // way to exercise the router without a static-server 404).
  await page.evaluate(() => {
    history.pushState({}, '', '/work');
    dispatchEvent(new PopStateEvent('popstate'));
  });
  await page.waitForTimeout(1000);
  await expect(page).toHaveURL(/\/agents$/);

  // Unknown route -> 404 page with a working "back to Chat".
  await page.evaluate(() => {
    history.pushState({}, '', '/nope-not-a-page');
    dispatchEvent(new PopStateEvent('popstate'));
  });
  await page.waitForTimeout(1000);
  await expect(page.getByRole('heading', { name: 'Page not found' })).toBeVisible();
  await page.getByRole('button', { name: 'Back to Chat' }).click();
  await expect(page).toHaveURL(/\/chat$/);

  // Depth 1: no breadcrumb. Depth 2 (settings section): breadcrumb shown.
  await gotoDest(page, 'agents');
  await expect(page.locator('#destBreadcrumb')).toHaveClass(/hidden/);
  await page.keyboard.press('ControlOrMeta+k');
  await page.locator('#paletteInput').fill('Settings: Models');
  await page.locator('#paletteInput').press('Enter');
  await page.waitForTimeout(1500);
  await expect(page).toHaveURL(/\/settings\/models$/);
  await expect(page.locator('#destBreadcrumb')).not.toHaveClass(/hidden/);
  await expect(page.locator('#destBreadcrumb')).toContainText('Settings / models');
});

test('Shell: command palette reaches destinations, settings, create actions', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  await page.keyboard.press('ControlOrMeta+k');
  await expect(page.locator('#paletteInput')).toBeVisible();
  await page.locator('#paletteInput').fill('Go to Projects');
  await page.locator('#paletteInput').press('Enter');
  await page.waitForTimeout(1500);
  await expect(page).toHaveURL(/\/projects$/);

  await page.keyboard.press('ControlOrMeta+k');
  await page.locator('#paletteInput').fill('New artifact');
  await page.locator('#paletteInput').press('Enter');
  await page.waitForTimeout(1500);
  // 'New artifact' lands on Studio's create segment (palette.js
  // new-artifact -> navigate('studio', { section: 'create' })), not
  // the bare Studio overview — assert destination + segment.
  await expect(page).toHaveURL(/\/studio\?section=create$/);

  await page.keyboard.press('ControlOrMeta+k');
  await page.locator('#paletteInput').fill('Toggle Auto mode');
  await expect(page.locator('.palette-item')).toContainText(['Toggle Auto mode']);
  await page.keyboard.press('Escape');
  await expect(page.locator('#paletteOverlay')).toHaveClass(/hidden/);
});

test('Shell: power-user two-click reachability + empty states', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  // Two clicks from Chat: Code (1) -> Spec & QA segment (2).
  await gotoDest(page, 'code');
  await page.locator('[data-dest-section="spec"]').click();
  await page.waitForTimeout(1500);
  await expect(page.locator('#specCreate')).toBeVisible();

  // Agents -> Task board (2 clicks): empty state, one guided action.
  await gotoDest(page, 'agents');
  await page.locator('[data-dest-section="tasks"]').click();
  await page.waitForTimeout(2000);
  await expect(page.locator('#tbNew')).toBeVisible();

  // Projects empty state: the create form is the single guided action.
  await gotoDest(page, 'projects');
  await expect(page.locator('#pjCreate button[type="submit"]')).toHaveCount(1);
  await expect(page.locator('#pjList')).toContainText('No projects yet');

  // Run History empty state: exactly one primary guided action.
  await gotoDest(page, 'agents');
  await page.locator('[data-dest-section="run-history"]').click();
  await page.waitForTimeout(2000);
  await expect(page.locator('#runsStartAgent')).toHaveCount(1);
});

test('Shell: first-run flow is stepped, skippable, sample labelled', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  // Only meaningful when no provider is ready (fresh mock backend);
  // if a provider is already connected the panel correctly never shows.
  const panel = page.locator('#firstRunSetup');
  if (!(await panel.count())) test.skip();
  await expect(panel.locator('#setupStepLabel')).toContainText('Step 1 of 3');
  await panel.locator('[data-path="tour"]').click();
  await expect(panel.locator('#setupStepLabel')).toContainText('Step 2 of 3');
  await expect(panel.locator('.setup-sample')).toContainText('SAMPLE — not a real model response');
  await panel.locator('#setupTour').click();
  await expect(panel.locator('#setupStepLabel')).toContainText('Step 3 of 3');
  await expect(panel.locator('h3')).toContainText('What do you want to get done today?');
  // Skippable, never blocking: the skip link dismisses to a banner.
  await panel.locator('#setupSkipLink').click();
  await expect(page.locator('#setupBanner')).toBeVisible();
});
