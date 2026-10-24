/**
 * UX-refine wave spec (Wave-1 frontend worker — NOT run by the worker:
 * Playwright and ports 8001/5500 are shared, so the parent runs this).
 *
 * Journeys covered, each against a fresh backend:
 *  1. Guided setup is stepped: Step 1 shows one choice (three path
 *     buttons + skip), Step 2 shows only the chosen path's single action,
 *     Back returns to Step 1, Skip leaves the dismissible banner.
 *  2. Composer slash menu: typing "/" lists real commands; Escape closes
 *     it; typing "/runs" filters to the Runs command.
 *  3. Message actions: an assistant message seeded via the API carries
 *     Save / Workflow / Inspect buttons; Inspect opens the Inspector
 *     showing the message's tool-call evidence in place (no tab hop).
 *  4. Global HTTP-fallback banner module: on loopback it must NOT render
 *     (local dev is not a LAN exposure); the module exports the guard so
 *     the non-loopback path is unit-checkable without a LAN host.
 *
 * Precondition for journey 1: the backend has NO provider configured,
 * otherwise the setup panel correctly does not appear. Follows the
 * runs.spec.ts guard pattern (console.error / pageerror / HTTP >= 400
 * after login fail the run).
 */
import { test, expect, Page } from '@playwright/test';

test.use({
  launchOptions: {
    args: ['--disable-http-cache', '--disk-cache-size=1'],
  },
});

const FRONTEND_URL = process.env.E2E_FRONTEND_URL || 'http://127.0.0.1:5500';
const BACKEND_URL = process.env.E2E_BACKEND_URL || 'http://127.0.0.1:8001';
const PASS = 'Ux-Refine-Password-123';
const USER = 'uxrefineuser';

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

function assertClean() {
  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.consoleErrors, `console.error: ${JSON.stringify(ctx.consoleErrors)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
}

test('Setup is stepped: one choice, then one action, with Back and Skip', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  const panel = page.locator('#firstRunSetup');
  await expect(panel).toBeVisible({ timeout: 20000 });
  // Step 1: visible progress + exactly one choice group, no form yet.
  await expect(page.locator('#setupStepLabel')).toContainText('Step 1 of 2');
  await expect(page.locator('#setupProgressBar')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Use a cloud provider' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Use a free local model' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Look around first' })).toBeVisible();
  await expect(page.locator('#setupKey')).toHaveCount(0);

  // Cloud path: Step 2 shows only that path's single action + Back.
  await page.getByRole('button', { name: 'Use a cloud provider' }).click();
  await expect(page.locator('#setupStepLabel')).toContainText('Step 2 of 2');
  await expect(page.locator('#setupKey')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save key & test it' })).toBeVisible();
  await expect(page.getByRole('button', { name: '← Back' })).toBeVisible();

  // Back returns to Step 1; Skip leaves the banner, not a dead chat.
  await page.getByRole('button', { name: '← Back' }).click();
  await expect(page.locator('#setupStepLabel')).toContainText('Step 1 of 2');
  await page.getByRole('button', { name: "I'll configure later" }).click();
  await expect(panel).toHaveCount(0);
  await expect(page.locator('#setupBanner')).toBeVisible();
  assertClean();
});

test('Slash menu lists real commands and filters', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  const input = page.locator('#messageInput');
  await input.click();
  await input.fill('/');
  await expect(page.locator('.slash-menu:not(.hidden)')).toBeVisible({ timeout: 10000 });
  await expect(page.locator('.slash-item[data-cmd="runs"]')).toBeVisible();
  await expect(page.locator('.slash-item[data-cmd="settings"]')).toBeVisible();
  await expect(page.locator('.slash-item[data-cmd="research"]')).toBeVisible();

  // Filtering narrows to the matching command.
  await input.fill('/run');
  await expect(page.locator('.slash-item[data-cmd="runs"]')).toBeVisible();
  await expect(page.locator('.slash-item[data-cmd="settings"]')).toHaveCount(0);

  // Escape closes without sending anything.
  await page.keyboard.press('Escape');
  await expect(page.locator('.slash-menu:not(.hidden)')).toHaveCount(0);
  await expect(page.locator('#messages .msg')).toHaveCount(0);
  assertClean();
});

test('Message actions: Save, Workflow, Inspect with evidence in place', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  // Seed one chat with a user question + an assistant answer via the
  // existing chats API (no model needed). NOTE: the append endpoint only
  // persists role/content — tool_calls are dropped server-side (a
  // backend gap flagged in BUILD_LOG2-ux.md, not fixable frontend-only).
  // So button visibility is checked on the reloaded message, while the
  // Inspector evidence rendering is checked by selecting an in-session
  // message object carrying a tool call (the shape chat.js builds live).
  const api = page.request;
  const chat = await api.post(`${BACKEND_URL}/api/chats`, {
    data: { title: 'UX refine seed', model: '' },
  });
  expect(chat.ok(), `create chat failed: ${chat.status()}`).toBe(true);
  const chatId = (await chat.json()).id;
  const appended = await api.post(`${BACKEND_URL}/api/chats/${chatId}/messages`, {
    data: {
      messages: [
        { role: 'user', content: 'What files changed in the last commit?' },
        { role: 'assistant', content: 'Two files changed.' },
      ],
    },
  });
  expect(appended.ok(), `append messages failed: ${appended.status()}`).toBe(true);

  await page.reload();
  await page.waitForTimeout(2000);
  // Open the seeded chat from the sidebar history.
  await page.locator('.chat-history-item, [data-chat-id]').first().click();
  await page.waitForTimeout(2000);

  const asst = page.locator('#messages .msg.assistant').last();
  await expect(asst).toBeVisible();
  await expect(asst.getByRole('button', { name: 'Save answer as a file' })).toBeVisible();
  await expect(asst.getByRole('button', { name: 'Turn this chat into a workflow' })).toBeVisible();

  // Inspect opens the Inspector next to chat (no tab hop). Then select
  // an in-session message with a tool call and check the evidence
  // section renders it in place.
  await asst.getByRole('button', { name: "Inspect this message's evidence" }).click();
  await expect(page.locator('#inspectorPanel:not(.hidden)')).toBeVisible({ timeout: 10000 });
  await page.evaluate(async () => {
    const mod = await import('/js/features/inspector/inspector.js');
    mod.setSelectedMessage({
      role: 'assistant',
      content: 'Two files changed.',
      tool_calls: [{ name: 'code_map', arguments: '{}', result: 'src/a.py, src/b.py', status: 'completed' }],
      citations: [{ title: 'Repo map', url: 'https://example.invalid/map' }],
    });
  });
  await expect(page.locator('#inspectorBody')).toContainText('Tool calls (1)');
  await expect(page.locator('#inspectorBody')).toContainText('code_map');
  await expect(page.locator('#inspectorBody')).toContainText('Sources (1)');
  assertClean();
});

test('Global HTTP banner module suppresses loopback, exports its guard', async ({ page }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  const result = await page.evaluate(async () => {
    const mod = await import('/js/features/settings/http-banner.js');
    return {
      shouldShow: mod.shouldShowHttpBanner(),
      shown: mod.showGlobalHttpBanner(),
      bannerInDom: !!document.getElementById('sangam-lan-http-banner'),
    };
  });
  // Served on 127.0.0.1 over http: loopback must never show the banner.
  expect(result.shouldShow).toBe(false);
  expect(result.shown).toBe(false);
  expect(result.bannerInDom).toBe(false);
  assertClean();
});
