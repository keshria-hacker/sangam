/**
 * Tabs-on-top spec (2026-10-25 user correction: tabs on top, sidebar
 * buttons removed). Proves the tab bar BEHAVIOURALLY, not just by
 * element existence:
 * - the bar holds the 8 destinations, Chat pinned with no close control
 * - no sidebar and no sidebar destination button exists in the DOM
 * - opening a destination via the command palette creates its tab
 *   (and opening it again focuses it, never duplicates it)
 * - switching tabs pushes URL state; back/forward moves between tabs
 * - closing the active tab falls back to the most recently used tab,
 *   and closing can never leave a blank screen
 * - on mobile the tab bar is the only navigation (no drawer)
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
const PASS = 'Tabs-Test-Password-123';
const USER = 'tabsuser';

const ctx = { badResponses: [] as string[], consoleErrors: [] as string[], pageErrors: [] as string[], loggedIn: false };

function attachGuards(page: Page) {
  page.on('response', (r) => {
    const status = r.status();
    if (status >= 400) {
      if (status === 401 && !ctx.loggedIn) return;
      if (status === 403 && r.url().includes('/auth/register')) return;
      // Designed, not an error: /api/analytics/summary returns 404
      // when analytics is off (FEATURE_ANALYTICS defaults False,
      // opt-in for privacy) and the usage meter honestly shows
      // "unavailable" instead. This test reloads the app while logged
      // in (deep link), so unlike the other specs it sees the
      // post-login 404; pre-login the same fetch is a 401.
      if (status === 404 && r.url().includes('/api/analytics/summary')) return;
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
  // The API-login cookie alone does not hide the overlay on load in
  // this harness (same as shell/runs specs): log in through the UI.
  await page.fill('#authUsername', USER);
  await page.fill('#authPassword', PASS);
  await page.click('#authSubmit');
  await expect(page.locator('#authOverlay')).toHaveClass(/hidden/, { timeout: 20000 });
  ctx.loggedIn = true;
  await page.waitForTimeout(1500);
}

async function openViaPalette(page: Page, destLabel: string) {
  await page.keyboard.press('ControlOrMeta+K');
  await expect(page.locator('#paletteOverlay')).toBeVisible({ timeout: 10000 });
  await page.locator('#paletteInput').fill(`Go to ${destLabel}`);
  await page.waitForTimeout(500);
  await page.locator('.palette-item', { hasText: `Go to ${destLabel}` }).first().click();
  await page.waitForTimeout(1500);
}

function assertClean(stage: string) {
  expect(ctx.badResponses, `HTTP >= 400 at ${stage}: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.consoleErrors, `console.error at ${stage}: ${JSON.stringify(ctx.consoleErrors)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror at ${stage}: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
}

test('Tabs: bar on top, Chat pinned, no sidebar buttons', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  await expect(page.locator('#tabBar')).toBeVisible();
  await expect(page.locator('#sidebar')).toHaveCount(0);
  await expect(page.locator('.rail-item')).toHaveCount(0);
  // No element anywhere claims to be a sidebar destination button:
  // the only [data-nav] elements are the tab labels themselves.
  const navOwners = await page.locator('[data-nav]').evaluateAll((els) =>
    els.map((el) => el.closest('.tab-item') ? 'tab' : el.tagName));
  expect(navOwners.every((o) => o === 'tab'), `[data-nav] outside tabs: ${navOwners}`).toBe(true);

  const tabs = await page.locator('.tab-item').evaluateAll((els) =>
    els.map((el) => el.getAttribute('data-tab')));
  expect(tabs).toEqual(['chat', 'projects', 'studio', 'code', 'research', 'agents', 'library', 'settings']);
  // Chat pinned: first, selected, no close control, no duplicate.
  await expect(page.locator('.tab-item').first()).toHaveAttribute('data-tab', 'chat');
  await expect(page.locator('.tab-item[data-tab="chat"] [data-tab-close]')).toHaveCount(0);
  expect(await page.locator('.tab-item[data-tab="chat"]').count()).toBe(1);
  await expect(page.locator('.tab-item[data-tab="chat"]')).toHaveAttribute('aria-selected', 'true');
  // Relocated sidebar-footer items live in the tab bar, compact:
  // usage meter + avatar menu + palette hint as plain text (not a button).
  await expect(page.locator('#tabBar #usageMeter')).toBeVisible();
  await expect(page.locator('#tabBar #profileSection')).toBeVisible();
  await expect(page.locator('#tabBar #paletteHintBtn')).toHaveCount(0);
  const hintTag = await page.locator('.tabbar-kbd-hint').evaluate((el) => el.tagName);
  expect(hintTag).toBe('SPAN');
  assertClean('bar');
});

test('Tabs: palette open, switch changes URL, close falls back to MRU', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  // Start from a small bar: close Studio and Code, then reopen via palette.
  await page.locator('[data-tab-close="studio"]').click();
  await page.waitForTimeout(800);
  await page.locator('[data-tab-close="code"]').click();
  await page.waitForTimeout(800);
  expect(await page.locator('.tab-item[data-tab="studio"]').count()).toBe(0);
  expect(await page.locator('.tab-item[data-tab="code"]').count()).toBe(0);

  await openViaPalette(page, 'Studio');
  expect(await page.locator('.tab-item[data-tab="studio"]').count()).toBe(1);
  await expect(page.locator('.tab-item[data-tab="studio"]')).toHaveAttribute('aria-selected', 'true');
  expect(page.url()).toContain('/studio');

  // Opening the same destination again focuses it — never duplicates.
  await openViaPalette(page, 'Studio');
  expect(await page.locator('.tab-item[data-tab="studio"]').count()).toBe(1);
  expect(page.url()).toContain('/studio');

  await openViaPalette(page, 'Code');
  expect(page.url()).toContain('/code');
  await expect(page.locator('.tab-item[data-tab="code"]')).toHaveAttribute('aria-selected', 'true');

  // Switching tabs via the tab label pushes URL state.
  await page.locator('.tab-item[data-tab="studio"] .tab-item-label').click();
  await page.waitForTimeout(1000);
  expect(page.url()).toContain('/studio');
  await expect(page.locator('.tab-item[data-tab="studio"]')).toHaveAttribute('aria-selected', 'true');

  // Closing the active tab falls back to the most recently used tab
  // (Code was the last tab before Studio), not to a blank screen.
  await page.locator('[data-tab-close="studio"]').click();
  await page.waitForTimeout(1000);
  expect(await page.locator('.tab-item[data-tab="studio"]').count()).toBe(0);
  expect(page.url()).toContain('/code');
  await expect(page.locator('.tab-item[data-tab="code"]')).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#toolViewBody')).toBeVisible();

  // Closing the last non-Chat tab falls back to Chat.
  await page.locator('[data-tab-close="code"]').click();
  await page.waitForTimeout(1000);
  expect(page.url()).toContain('/chat');
  await expect(page.locator('#messageInput')).toBeVisible();
  assertClean('palette-switch-close');
});

test('Tabs: back/forward moves between tabs', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  await openViaPalette(page, 'Projects');
  expect(page.url()).toContain('/projects');
  await openViaPalette(page, 'Research');
  expect(page.url()).toContain('/research');

  await page.goBack();
  await page.waitForTimeout(1000);
  expect(page.url()).toContain('/projects');
  await expect(page.locator('.tab-item[data-tab="projects"]')).toHaveAttribute('aria-selected', 'true');

  await page.goForward();
  await page.waitForTimeout(1000);
  expect(page.url()).toContain('/research');
  await expect(page.locator('.tab-item[data-tab="research"]')).toHaveAttribute('aria-selected', 'true');
  assertClean('back-forward');
});

test('Tabs: deep link focuses the right tab on load', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  await page.goto(`${FRONTEND_URL}/agents`);
  await page.waitForTimeout(2000);
  await expect(page.locator('.tab-item[data-tab="agents"]')).toHaveAttribute('aria-selected', 'true');
  await expect(page.locator('#toolViewBody')).toBeVisible();
  assertClean('deep-link');
});

test('Tabs: mobile 390px — tab bar only, no drawer lingering', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await register(page);

  await expect(page.locator('#mobileSidebarToggle')).toHaveCount(0);
  await expect(page.locator('#sidebar')).toHaveCount(0);
  await expect(page.locator('#tabBar')).toBeVisible();
  // With all 8 tabs open on a narrow viewport the bar scrolls
  // horizontally instead of wrapping or breaking the page.
  const scrollable = await page.evaluate(() => {
    const el = document.querySelector('#tabBarScroll');
    return el ? el.scrollWidth > el.clientWidth : false;
  });
  expect(scrollable, 'tab bar should scroll horizontally on mobile').toBe(true);
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, `horizontal overflow at 390px: ${overflow}px`).toBeLessThanOrEqual(1);

  await page.locator('[data-nav="agents"]').click();
  await page.waitForTimeout(1500);
  await expect(page.locator('#toolViewBody')).toBeVisible();
  await expect(page.locator('#sidebarScrim.show')).toHaveCount(0);
  assertClean('mobile');
});
