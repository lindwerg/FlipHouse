import { expect, test } from '@playwright/test';

// Smoke e2e — proves the web Playwright harness works end-to-end (P0.8).
test('landing page renders an h1', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('h1')).toBeVisible();
});

test('GET /api/health returns 200 with status ok', async ({ request }) => {
  const response = await request.get('/api/health');
  expect(response.status()).toBe(200);
  expect(await response.json()).toMatchObject({ status: 'ok' });
});
