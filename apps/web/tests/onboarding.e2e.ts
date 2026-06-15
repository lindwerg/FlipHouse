import { setupClerkTestingToken } from '@clerk/testing/playwright';
import { expect, test } from '@playwright/test';

// Authenticated onboarding e2e. Drives the full new-user path against the live
// dev Clerk instance: sign up (clerk_test email + 424242 code) → pick a role →
// land on the typed dashboard. No organizations — the role is written to the
// Clerk user's publicMetadata (founder decision 2026-06-15). Account type is
// immutable, so each run uses a unique clerk_test email (a fresh user).
//
// REQUIRES: Organizations disabled in the Clerk dashboard (otherwise Clerk
// injects a "choose-organization" task into sign-up and this flow can't reach
// onboarding).
//
// LOCAL-ONLY: needs real dev Clerk keys (.env.local). Self-skips in CI and on
// fresh checkouts (no secret); heavy auth e2e is otherwise consolidated in P1.16.
const hasClerkSecret
  = !!process.env.CLERK_SECRET_KEY
    && process.env.CLERK_SECRET_KEY !== 'sk_test_placeholder';

test.describe('onboarding', () => {
  test.skip(
    !!process.env.CI || !hasClerkSecret,
    'requires live Clerk keys (local-only; auth e2e consolidated in P1.16)',
  );

  test('new user picks creator and lands on creator dashboard', async ({ page }) => {
    // The new-user path (sign up → verify → pick role) exceeds the default 30s,
    // and dev-mode first-compile of each route adds latency.
    test.setTimeout(240_000);

    await setupClerkTestingToken({ page });

    // Unique base local-part keeps the user fresh; the exact `+clerk_test`
    // subaddress is what Clerk recognizes as a test email (code 424242 works).
    const email = `creator_${Date.now()}+clerk_test@example.com`;
    const password = `Fh-${Date.now()}-Pw!`;

    // 1. Sign up a fresh user.
    await page.goto('/sign-up');
    await page.locator('input[name="emailAddress"]').fill(email);
    await page.locator('input[name="password"]').fill(password);
    await page.getByRole('button', { name: /continue/i }).click();

    // 2. Email verification: Clerk test mode accepts the fixed code 424242.
    const otp = page.getByRole('textbox', { name: /verification code/i });
    await otp.waitFor({ state: 'visible' });
    await otp.pressSequentially('424242');

    // 3. With no org requirement, sign-up lands on /dashboard, which routes a
    //    user without a role to /onboarding.
    await page.waitForURL(/\/onboarding(\?|$|\/)/);
    await expect(
      page.getByRole('heading', { name: 'Кто вы на FlipHouse?' }),
    ).toBeVisible();

    // 4. Pick creator → typed dashboard.
    await page.locator('button[data-account-type="creator"]').click();

    await page.waitForURL(/\/dashboard\/creator/);
    await expect(
      page.getByRole('heading', { name: 'Кабинет креатора' }),
    ).toBeVisible();
  });
});
