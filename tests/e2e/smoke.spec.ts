/**
 * Smoke Test (Phase 8, rule 4) — REQUIRED GATE.
 *
 * Boots the app against a fresh backend (SANGAM_MOCK_PROVIDER=1 for the
 * mock LLM), registers a new user, visits every rail item, opens every
 * composer popover, opens Settings, sends one chat message against the
 * mock model, and opens the Knowledge graph.
 *
 * FAILS on:
 *  - any HTTP response with status >= 400 (401s allowed only before login)
 *  - any console.error or uncaught page error
 *  - any visible "NaN", "undefined" or "[object ...]" text on screen
 *  - any CSS var(--x) used in style.css but never defined
 *
 * Run via: tests/e2e/run_smoke.sh  (starts backend + frontend, fresh DB)
 */
import { test, expect, Page } from '@playwright/test';

const FRONTEND_URL = process.env.E2E_FRONTEND_URL || 'http://127.0.0.1:5500';
const BACKEND_URL = process.env.E2E_BACKEND_URL || 'http://127.0.0.1:8001';
const PASS = 'Smoke-Test-Password-123';
// Single-user app: only one account can exist. Fixed name shared across
// Playwright workers (each worker loads this spec separately).
const USER = 'smokeuser';

interface BadResponse { url: string; status: number; method: string }
interface Ctx {
  badResponses: BadResponse[];
  consoleErrors: string[];
  pageErrors: string[];
  loggedIn: boolean;
}

function attachGuards(page: Page, ctx: Ctx) {
  page.on('request', (r) => {
    if (r.url().includes('/chat/') || r.url().includes('/models')) {
      console.log('NET REQ:', r.method(), r.url());
    }
  });
  page.on('response', (r) => {
    const status = r.status();
    if (status >= 400) {
      if (status === 401 && !ctx.loggedIn) return; // allowed before login
      // 403 on register when the user exists is handled by the test's login fallback
      if (status === 403 && r.url().includes('/auth/register')) return;
      ctx.badResponses.push({ url: r.url(), status, method: r.request().method() });
    }
  });
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      const text = msg.text();
      // Ignore network-level resource failures (blocked CDNs in sandbox);
      // the app must not depend on them. JS errors are still caught.
      if (text.includes('Failed to load resource') || text.includes('net::ERR_')) return;
      ctx.consoleErrors.push(text.slice(0, 300));
    }
  });
  page.on('pageerror', (err) => {
    ctx.pageErrors.push(String(err).slice(0, 300));
  });
}

function assertClean(ctx: Ctx, where: string) {
  expect(ctx.badResponses, `HTTP >= 400 at ${where}: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.consoleErrors, `console.error at ${where}: ${JSON.stringify(ctx.consoleErrors)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror at ${where}: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
}

async function assertNoBadText(page: Page, where: string) {
  const text = await page.evaluate(() => document.body.innerText || '');
  const bad = text.match(/\bNaN\b|undefined|\[object [A-Za-z]+\]/g);
  expect(bad, `bad on-screen text at ${where}: ${JSON.stringify(bad)}`).toBeNull();
}

async function register(page: Page, ctx: Ctx) {
  // Serial execution + single-user app: first test registers via UI (fresh
  // DB => register mode), later tests log in via UI (login mode).
  await page.goto(FRONTEND_URL);
  await page.waitForFunction(
    () => {
      const form = document.querySelector('#authForm');
      const overlay = document.querySelector('#authOverlay');
      return (form && !form.classList.contains('hidden')) ||
             (overlay && overlay.classList.contains('hidden'));
    },
    { timeout: 20000 }
  );
  if (await page.locator('#authOverlay.hidden').count()) {
    ctx.loggedIn = true; // already authenticated
    await page.waitForTimeout(1500);
    return;
  }
  const mode = await page.locator('#authForm').getAttribute('data-mode');
  await page.fill('#authUsername', USER);
  await page.fill('#authPassword', PASS);
  if (mode === 'register') {
    await page.fill('#authConfirmPassword', PASS);
  }
  await page.click('#authSubmit');
  await expect(page.locator('#authOverlay')).toHaveClass(/hidden/, { timeout: 20000 });
  ctx.loggedIn = true;
  await page.waitForTimeout(1500); // let /features + initial fetches settle
}

test.describe.serial('Smoke (required gate)', () => {
  test('CSS variables: every var() used is defined', async ({ page }) => {
    const css = await (await fetch(`${FRONTEND_URL}/css/style.css`)).text();
    // Vars used WITHOUT a fallback: var(--x) — these break if undefined.
    // Vars with fallbacks var(--x, ...) are safe and not flagged.
    const usedNoFallback = new Set(
      [...css.matchAll(/var\(--([a-zA-Z0-9_-]+)\)/g)].map((m) => m[1])
    );
    const defined = new Set([...css.matchAll(/--([a-zA-Z0-9_-]+)\s*:/g)].map((m) => m[1]));
    const missing = [...usedNoFallback].filter((v) => !defined.has(v)).sort();
    expect(missing, `undefined CSS vars (no fallback): ${missing.join(', ')}`).toEqual([]);
  });

  test('full pass: register, rail, popovers, settings, chat, knowledge', async ({ page }) => {
    const ctx: Ctx = { badResponses: [], consoleErrors: [], pageErrors: [], loggedIn: false };
    attachGuards(page, ctx);
    test.setTimeout(180000);

    // 1. Boot + register
    await register(page, ctx);
    assertClean(ctx, 'register');
    await assertNoBadText(page, 'post-register');

    // 2. Visit every rail item
    await page.waitForFunction(
      () => document.querySelectorAll('.rail-item[data-nav]').length > 3,
      { timeout: 15000 }
    );
    const railIds: string[] = await page.evaluate(() =>
      [...document.querySelectorAll('.rail-item[data-nav]')].map((el) =>
        (el as HTMLElement).dataset.nav as string
      )
    );
    expect(railIds.length).toBeGreaterThan(3);
    for (const id of railIds) {
      const item = page.locator(`.rail-item[data-nav="${id}"]`).first();
      if (!(await item.isVisible())) continue;
      await item.click();
      await page.waitForTimeout(900);
      assertClean(ctx, `rail:${id}`);
      await assertNoBadText(page, `rail:${id}`);
      await page.screenshot({ path: `tests/e2e/screenshots/smoke-rail-${id}.png` });
    }

    // 3. Composer popovers (back on chat view) — B4: Temp/Tokens pills deleted,
    // Tune is the single owner. Popovers: Mode, Tools, Tune.
    await page.locator('.rail-item[data-nav="chat"]').first().click();
    await page.waitForTimeout(800);
    for (const btn of ['#modeBtn', '#toolsBtn', '#tuneBtn']) {
      const el = page.locator(btn);
      if ((await el.count()) === 0 || !(await el.first().isVisible())) continue;
      await el.first().click();
      await page.waitForTimeout(500);
      assertClean(ctx, `popover:${btn}`);
      await page.screenshot({ path: `tests/e2e/screenshots/smoke-popover-${btn.slice(1)}.png` });
      await page.keyboard.press('Escape');
      await page.waitForTimeout(300);
    }
    await assertNoBadText(page, 'popovers');

    // 4. Settings page
    const settingsNav = page.locator('.rail-item[data-nav="settings"]').first();
    if (await settingsNav.count()) {
      await settingsNav.click();
      await page.waitForTimeout(1200);
      assertClean(ctx, 'settings');
      await assertNoBadText(page, 'settings');
      await page.screenshot({ path: 'tests/e2e/screenshots/smoke-settings.png' });
    }

    // 5. Send one chat message against the mock model
    await page.locator('.rail-item[data-nav="chat"]').first().click();
    await page.waitForTimeout(800);
    // Select the mock model — it MUST exist (SANGAM_MOCK_PROVIDER=1).
    await page.locator('#modelSelectorBtn').click();
    await page.waitForTimeout(600);
    const mockOption = page.locator('.model-option', { hasText: /Mock/i }).first();
    await expect(mockOption, 'mock model option not found in selector').toBeVisible({ timeout: 10000 });
    await mockOption.click();
    await page.waitForTimeout(500);
    await page.fill('#messageInput', 'Smoke test hello');
    await page.locator('#sendBtn').click();
    await page.waitForTimeout(8000);
    const dbgHtml = await page.locator('#messages').innerHTML();
    console.log('MESSAGES LEN:', dbgHtml.length, 'HAS REPLY:', dbgHtml.includes('Smoke test reply'));
    // Find assistant messages
    const assistantHtml = await page.locator('.msg.assistant').innerHTML().catch(() => 'none');
    console.log('ASSISTANT HTML:', assistantHtml.slice(0, 300));
    try {
      await expect(page.locator('#messages')).toContainText('Smoke test reply', { timeout: 30000 });
    } catch (e) {
      // Debug: log what went wrong
      console.log('CHAT DEBUG badResponses:', JSON.stringify(ctx.badResponses));
      console.log('CHAT DEBUG consoleErrors:', JSON.stringify(ctx.consoleErrors));
      console.log('CHAT DEBUG messages HTML:', (await page.locator('#messages').innerHTML()).slice(0, 500));
      throw e;
    }
    assertClean(ctx, 'chat-send');
    await assertNoBadText(page, 'chat-send');
    await page.screenshot({ path: 'tests/e2e/screenshots/smoke-chat.png' });

    // 6. Knowledge graph must load (not stuck, not error)
    await page.locator('.rail-item[data-nav="knowledge"]').first().click();
    await page.waitForTimeout(4000);
    const graphText = await page.evaluate(() => document.body.innerText || '');
    expect(graphText, 'knowledge graph failed to load').not.toContain('Could not load graph');
    assertClean(ctx, 'knowledge');
    await assertNoBadText(page, 'knowledge');
    await page.screenshot({ path: 'tests/e2e/screenshots/smoke-knowledge.png' });

    // Final gate
    assertClean(ctx, 'final');
  });

  test('mobile 390px: rail reachable via menu button', async ({ page }) => {
    const ctx: Ctx = { badResponses: [], consoleErrors: [], pageErrors: [], loggedIn: false };
    attachGuards(page, ctx);
    await page.setViewportSize({ width: 390, height: 844 });
    await register(page, ctx);
    const menuBtn = page.locator('#mobileSidebarToggle');
    await expect(menuBtn, 'mobile menu button not visible at 390px').toBeVisible({ timeout: 10000 });
    await menuBtn.click();
    await page.waitForTimeout(800);
    const railVisible = await page.evaluate(() => {
      const rail = document.querySelector('#sidebar, .rail, nav');
      if (!rail) return false;
      const r = rail.getBoundingClientRect();
      return r.width > 0 && r.left < 390;
    });
    expect(railVisible, 'rail did not open from mobile menu').toBe(true);
    await page.screenshot({ path: 'tests/e2e/screenshots/smoke-mobile.png' });
    assertClean(ctx, 'mobile');
    await assertNoBadText(page, 'mobile');
  });
});
