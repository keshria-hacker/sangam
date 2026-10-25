/**
 * Batch 6 LAN pairing spec (not part of the smoke gate — run it the same
 * way run_smoke.sh runs smoke.spec.ts, against a fresh mock backend).
 *
 * Settings -> Devices section renders (LAN toggle, pairing area, threat
 * model text); starting a pairing shows a 6-digit code + a rendered QR
 * canvas (verified to contain dark modules, not just an empty canvas);
 * host approval via the host session + claim via page.request (one
 * browser cannot be two devices, so the phone side is API-driven);
 * the returned device token authenticates GET /api/devices; revoke via
 * API and the token stops working (401).
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
const PASS = 'Devices-Test-Password-123';
const USER = 'devuser';

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
  } else {
    await page.fill('#authUsername', USER);
    await page.fill('#authPassword', PASS);
    await page.click('#authSubmit');
    await expect(page.locator('#authOverlay')).toHaveClass(/hidden/, { timeout: 20000 });
    ctx.loggedIn = true;
    await page.waitForTimeout(1500);
  }
}

test('Devices: section renders, pairing QR + code, approve/claim/revoke', async ({ page, playwright }) => {
  test.setTimeout(180000);
  attachGuards(page);
  await register(page);

  await page.locator('[data-nav="settings"]').click();
  // No standalone Devices category: LAN pairing lives in the Security
  // category (settings_schema.js legacy map: devices -> security).
  await expect(page.locator('.sp-cat[data-cat="security"]')).toBeVisible({ timeout: 20000 });
  await page.locator('.sp-cat[data-cat="security"]').click();
  await expect(page.locator('[data-devices-section]')).toBeVisible({ timeout: 20000 });
  await expect(page.locator('[data-key="LAN_ENABLED"]')).toBeVisible();
  await expect(page.getByText('What this protects')).toBeVisible();
  await expect(page.getByText('NOT protected')).toBeVisible();

  // Turn LAN mode on in the UI (schema toggle) and wait for the debounced save.
  const putPromise = page.waitForResponse(
    (r) => r.url().includes('/user/settings') && r.request().method() === 'PUT',
    { timeout: 15000 },
  );
  await page.locator('[data-key="LAN_ENABLED"] label.switch').click();
  await putPromise;

  // Re-open the Security category (which hosts the Devices section) so
  // it re-reads the toggled setting.
  await page.locator('.sp-cat[data-cat="security"]').click();
  await expect(page.locator('[data-devices-pair]')).toBeVisible({ timeout: 20000 });

  await page.locator('[data-devices-pair]').click();
  const codeEl = page.locator('[data-pair-code]');
  await expect(codeEl).toBeVisible({ timeout: 20000 });
  const code = (await codeEl.textContent())?.trim() || '';
  expect(code).toMatch(/^\d{6}$/);

  // QR canvas must actually render dark modules (not just exist).
  const canvas = page.locator('canvas[data-qr-canvas]');
  await expect(canvas).toBeVisible();
  await page.waitForFunction(
    () => {
      const c = document.querySelector('canvas[data-qr-canvas]') as HTMLCanvasElement | null;
      if (!c) return false;
      try {
        const data = c.getContext('2d')?.getImageData(0, 0, c.width, c.height).data;
        if (!data) return false;
        for (let i = 0; i < data.length; i += 4) {
          if (data[i] < 50 && data[i + 1] < 50 && data[i + 2] < 50) return true;
        }
      } catch { return false; }
      return false;
    },
    { timeout: 20000 },
  );

  // Host approval via the host session, then the phone claims via API.
  // NOTE: the UI login above holds the single session; logging in via API
  // here creates a fresh host token (and retires the UI session, which
  // is fine — no UI steps remain after this point).
  const fresh = await page.request.post(`${BACKEND_URL}/api/auth/login`, {
    data: { username: USER, password: PASS },
  });
  expect(fresh.ok(), `API host login failed: ${fresh.status()}`).toBe(true);
  const freshBody = await fresh.json() as { access_token: string; csrf_token: string };
  // page.request shares the browser context's cookies, so state-changing
  // host calls must echo the CSRF cookie value (Batch 3 precedent).
  const hostHeaders = {
    Authorization: `Bearer ${freshBody.access_token}`,
    'X-CSRF-Token': freshBody.csrf_token,
  };
  const listResp = await page.request.get(`${BACKEND_URL}/api/devices/pairing`, { headers: hostHeaders });
  expect(listResp.ok()).toBe(true);
  const pairings = (await listResp.json()).pairings as Array<{ pairing_id: string; code: string; status: string }>;
  const pairing = pairings.find((p) => p.code === code);
  expect(pairing, `pairing with code ${code} not found`).toBeTruthy();
  const approveResp = await page.request.post(
    `${BACKEND_URL}/api/devices/pairing/${pairing!.pairing_id}/approve`,
    { headers: hostHeaders, data: {} },
  );
  expect(approveResp.ok()).toBe(true);

  // The phone is a separate device: its own request context with no
  // shared cookies. (page.request shares the laptop's cookies, and a
  // cookie-holding POST to /claim would trip the CSRF check — a real
  // phone browser has no Sangam cookies, so this is the faithful shape.)
  const phone = await playwright.request.newContext();
  const claimResp = await phone.post(`${BACKEND_URL}/api/devices/pairing/claim`, {
    data: { code },
  });
  expect(claimResp.ok(), `claim failed: ${claimResp.status()}`).toBe(true);
  const claim = await claimResp.json() as { token: string; device_id: string };
  expect(claim.token).toBeTruthy();
  expect(claim.device_id).toBeTruthy();

  const authed = await phone.get(`${BACKEND_URL}/api/devices`, {
    headers: { Authorization: `Bearer ${claim.token}` },
  });
  expect(authed.ok()).toBe(true);

  const revokeResp = await page.request.delete(`${BACKEND_URL}/api/devices/${claim.device_id}`, {
    headers: hostHeaders,
  });
  expect(revokeResp.ok()).toBe(true);
  const afterRevoke = await phone.get(`${BACKEND_URL}/api/devices`, {
    headers: { Authorization: `Bearer ${claim.token}` },
  });
  expect(afterRevoke.status()).toBe(401);

  expect(ctx.badResponses, `HTTP >= 400: ${JSON.stringify(ctx.badResponses)}`).toEqual([]);
  expect(ctx.consoleErrors, `console.error: ${JSON.stringify(ctx.consoleErrors)}`).toEqual([]);
  expect(ctx.pageErrors, `pageerror: ${JSON.stringify(ctx.pageErrors)}`).toEqual([]);
});
