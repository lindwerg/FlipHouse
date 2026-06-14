import { expect, test } from '@playwright/test';

// Baseline smoke for the forked SaaS-Boilerplate landing (P1.1).
// The public marketing route renders without Clerk credentials (keyless mode);
// the navbar exposes the Clerk sign-in entry point, proving the auth-enabled fork
// rendered. A semantic <h1> and FlipHouse hero arrive with the P1 landing (1.8).
test('forked landing renders with a sign-in entry point', async ({ page }) => {
  const response = await page.goto('/');
  expect(response?.ok()).toBeTruthy();
  await expect(page.locator('a[href$="/sign-in"]').first()).toBeVisible();
});
