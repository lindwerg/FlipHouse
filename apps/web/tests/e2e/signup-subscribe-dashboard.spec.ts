import { setupClerkTestingToken } from '@clerk/testing/playwright';
import { expect, test } from '@playwright/test';

// The phase's headline e2e (P1.16): the full money path on the stitched-together
// app — sign up → onboard as creator → top up the prepaid USDT balance → see the
// funded balance on the dashboard. The deposit is funded via the dev-only
// /api/dev/payments/fund route, which replays a CONFIRMED on-chain transfer
// through the real watcher (confirmations gate → address→userId → idempotent
// credit) — deterministic, no TRON network.
//
// LOCAL-ONLY: needs real dev Clerk keys (.env.local). Self-skips in CI and on
// fresh checkouts (no secret) — same constraint as onboarding.e2e.ts; the founder
// runs this live at checkpoint G.
const hasClerkSecret
  = !!process.env.CLERK_SECRET_KEY
    && process.env.CLERK_SECRET_KEY !== 'sk_test_placeholder';

test.describe('signup → subscribe → dashboard', () => {
  test.skip(
    !!process.env.CI || !hasClerkSecret,
    'requires live Clerk keys (local/staging; founder runs at checkpoint G)',
  );

  test('signup → top up balance → lands on creator dashboard with funded balance / active plan', async ({ page }) => {
    // New-user path + dev-mode first-compile of each route exceeds the default.
    test.setTimeout(240_000);

    await setupClerkTestingToken({ page });

    const email = `creator_${Date.now()}+clerk_test@example.com`;
    const password = `Fh-${Date.now()}-Pw!`;

    // 1. Sign up a fresh user.
    await page.goto('/sign-up');
    await page.locator('input[name="emailAddress"]').fill(email);
    await page.locator('input[name="password"]').fill(password);
    await page.getByRole('button', { name: /continue/i }).click();

    // 2. Email verification — Clerk test mode accepts the fixed code 424242.
    const otp = page.getByRole('textbox', { name: /verification code/i });
    await otp.waitFor({ state: 'visible' });
    await otp.pressSequentially('424242');

    // 3. No org requirement → /dashboard routes a role-less user to /onboarding.
    await page.waitForURL(/\/onboarding(\?|$|\/)/);
    await page.locator('button[data-account-type="creator"]').click();

    // 4. Land on the creator dashboard with a zero starting balance.
    await page.waitForURL(/\/dashboard\/creator/);
    await expect(page.locator('[data-slot="balance"]')).toContainText('0.00');
    await expect(page.locator('[data-slot="deposit-address"]')).toBeVisible();

    // 5. Top up: the dev route funds a confirmed deposit through the real watcher.
    //    page.request shares the browser's Clerk session cookies, so the route
    //    credits THIS user's deposit address.
    const res = await page.request.post('/api/dev/payments/fund', {
      data: { amountUsdt: 50 },
    });

    expect(res.ok()).toBeTruthy();
    expect((await res.json()).credited).toBe(1);

    // 6. Reload → the funded balance shows on the dashboard.
    await page.reload();
    await expect(page.locator('[data-slot="balance"]')).toContainText('50.00');
  });
});
