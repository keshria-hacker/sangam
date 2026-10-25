/**
 * Batch 2 security spec: Work > Security renders, allowlist add works,
 * and a run created for an allowlisted target stays pending until
 * approved. No real scanning happens here (recon runs against the
 * smoke backend would need a reachable target); the approve/execute
 * path is covered by tests/test_batch2_security.py with mocked fetch.
 */
import { test, expect } from '@playwright/test';

const FRONTEND_URL = process.env.E2E_FRONTEND_URL || 'http://127.0.0.1:5500';
const BACKEND_URL = process.env.E2E_BACKEND_URL || 'http://127.0.0.1:8001';
const PASS = 'Security-Test-Password-123';
const USER = 'secuser';

test('Security: section renders, allowlist add, pending run', async ({ page }) => {
  test.setTimeout(180000);
  let resp = await page.request.post(`${BACKEND_URL}/api/auth/register`, {
    data: { username: USER, password: PASS },
  });
  if (resp.status() === 403) {
    resp = await page.request.post(`${BACKEND_URL}/api/auth/login`, {
      data: { username: USER, password: PASS },
    });
  }
  expect(resp.ok()).toBe(true);
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
    await page.waitForTimeout(1500);
  } else {
    await page.fill('#authUsername', USER);
    await page.fill('#authPassword', PASS);
    await page.click('#authSubmit');
    await expect(page.locator('#authOverlay')).toHaveClass(/hidden/, { timeout: 20000 });
    await page.waitForTimeout(1500);
  }

  await page.locator('[data-nav="agents"]').click();
  await page.waitForTimeout(2000);
  await page.locator('[data-dest-section="security"]').click();
  await expect(page.getByRole('heading', { name: 'Security' })).toBeVisible({ timeout: 20000 });
  await expect(page.locator('#secAllowForm')).toBeVisible();
  await expect(page.locator('#secCatalog')).not.toBeEmpty();

  await page.fill('#secAllowHost', 'staging.example.com');
  await page.fill('#secAllowNote', 'My own staging site');
  await page.locator('#secAllowForm button[type="submit"]').click();
  await expect(page.locator('#secAllowList')).toContainText('staging.example.com', { timeout: 20000 });

  await page.fill('#secRunTarget', 'https://staging.example.com');
  await page.fill('#secRunScope', 'Staging only');
  await page.locator('#secRunForm button[type="submit"]').click();
  await expect(page.locator('#secRuns')).toContainText('pending', { timeout: 20000 });
});
