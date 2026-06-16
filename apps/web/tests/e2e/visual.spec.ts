import { expect, test } from '@playwright/test';

// Landing visual regression (P1.16, web/testing.md breakpoints). Two layers:
//  1. No horizontal overflow at 320/768/1024/1440 — a layout measurement that is
//     platform-independent, so it runs everywhere incl. CI and is the DoD guard.
//  2. Pixel snapshots at the same breakpoints — platform-specific (font hinting
//     differs macOS↔Linux), so baselines are committed for local review and the
//     founder's checkpoint G; guard-skipped in CI to stay non-flaky.
const BREAKPOINTS = [320, 768, 1024, 1440] as const;
const HEIGHT = 900;

test.describe('landing — no horizontal overflow', () => {
  for (const width of BREAKPOINTS) {
    test(`no horizontal overflow at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: HEIGHT });
      await page.goto('/');
      await expect(page.locator('h1')).toBeVisible();
      await page.evaluate(() => document.fonts.ready);

      const overflow = await page.evaluate(() => {
        const el = document.documentElement;
        return el.scrollWidth - el.clientWidth;
      });

      // Allow ≤1px for sub-pixel rounding; anything larger is real overflow.
      expect(overflow).toBeLessThanOrEqual(1);
    });
  }
});

test.describe('landing — pixel snapshots', () => {
  test.skip(
    !!process.env.CI,
    'pixel snapshots are platform-specific; baselines are macOS — reviewed locally / at checkpoint G. CI guards layout via the no-overflow test.',
  );

  test('landing matches snapshot at 320/768/1024/1440', async ({ page }) => {
    // Reduced motion disables GSAP/Lenis on the landing → deterministic capture.
    await page.emulateMedia({ reducedMotion: 'reduce' });

    for (const width of BREAKPOINTS) {
      await page.setViewportSize({ width, height: HEIGHT });
      await page.goto('/');
      await expect(page.locator('h1')).toBeVisible();
      await page.evaluate(() => document.fonts.ready);

      await expect(page).toHaveScreenshot(`landing-${width}.png`, {
        fullPage: true,
        animations: 'disabled',
        maxDiffPixelRatio: 0.01,
      });
    }
  });
});
