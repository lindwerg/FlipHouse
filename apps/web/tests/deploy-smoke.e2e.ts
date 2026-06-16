import { expect, test } from '@playwright/test';

// Staging deploy smoke (P1.15). Runs against the live Railway staging domain via
// STAGING_URL (https). Self-skips when STAGING_URL is unset so local/CI e2e runs
// are unaffected (same pattern as the auth-gated onboarding spec). These assert
// the deployed artifact, not a local build: health probe, public landing render,
// and absence of server secrets in the shipped HTML.
const STAGING_URL = process.env.STAGING_URL?.replace(/\/$/, '');

test.describe('staging deploy smoke', () => {
  test.skip(!STAGING_URL, 'set STAGING_URL to run the staging deploy smoke');

  test('staging /api/health returns 200 ok over https', async ({ request }) => {
    expect(STAGING_URL?.startsWith('https://')).toBeTruthy();

    const response = await request.get(`${STAGING_URL}/api/health`);

    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.status).toBe('ok');
    expect(body.db).toBe('up');
  });

  test('staging landing renders h1 and primary CTA', async ({ page }) => {
    // The landing hero is CTA-based (HeroSection): the single <h1> plus the
    // primary "upload" call-to-action that routes to /sign-up — the real upload
    // surface lives in the dashboard after sign-up, not on the landing. (The
    // roadmap's "hero dropzone" wording predates the landing-system pass; the
    // dropzone now lives in the dashboard / tron-demo, not the marketing page.)
    // Wait for the document, not the full load event: the landing ships
    // animation/third-party JS that can keep the network busy past a smoke's
    // budget. Element visibility has its own deterministic wait.
    const response = await page.goto(`${STAGING_URL}/`, { waitUntil: 'domcontentloaded' });

    expect(response?.ok()).toBeTruthy();
    await expect(page.locator('h1').first()).toBeVisible();
    await expect(page.locator('a[href$="/sign-up"]').first()).toBeVisible();
  });

  test('no public env leakage: page source has no sk_/whsec_ secrets', async ({ page }) => {
    await page.goto(`${STAGING_URL}/`, { waitUntil: 'domcontentloaded' });
    const html = await page.content();

    expect(html).not.toMatch(/sk_(test|live)_/);
    expect(html).not.toMatch(/whsec_/);
  });
});
