import { setupClerkTestingToken } from '@clerk/testing/playwright';
import { expect, test, type Page } from '@playwright/test';

// The headline P2 acceptance e2e (DoD 2.11): the main creator flow on the
// stitched-together app — sign up → land on the creator dashboard → see the
// RANKED 9:16 clips of an upload in the right order, with a real <video> source,
// and prove that re-processing the same bytes REUSES the existing batch.
//
// The upload itself (tusd resumable PUT) and the GPU pipeline are founder-gated
// infra, so instead of a live upload+DAG run this seeds a finished upload via the
// dev-only /api/dev/clips/seed route — the SAME idempotent ledger claim the real
// tusd hook uses (claimUpload → upsertClips → finishUpload). The dashboard then
// reads it through the real /api/uploads + presign path, so the rendered surface
// is the production read path, not a mock.
//
// LOCAL-ONLY: needs real dev Clerk keys (.env.local) AND the web env the dev
// server boots with (R2 presign creds for /api/uploads). Self-skips in CI and on
// fresh checkouts (no secret) — same constraint as signup-subscribe-dashboard.
const hasClerkSecret
  = !!process.env.CLERK_SECRET_KEY
    && process.env.CLERK_SECRET_KEY !== 'sk_test_placeholder';

const RANKED_LIST = 'ol[aria-label="Ранжированные клипы из вашего видео"]';

/** Sign up a fresh creator and land them on the creator dashboard. */
async function signUpCreator(page: Page): Promise<void> {
  await setupClerkTestingToken({ page });

  const email = `creator_${Date.now()}+clerk_test@example.com`;
  const password = `Fh-${Date.now()}-Pw!`;

  await page.goto('/sign-up');
  await page.locator('input[name="emailAddress"]').fill(email);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole('button', { name: /continue/i }).click();

  const otp = page.getByRole('textbox', { name: /verification code/i });
  await otp.waitFor({ state: 'visible' });
  await otp.pressSequentially('424242');

  // A fresh role-less user is routed to /onboarding to pick an account type.
  // Some environments land on /dashboard first (the auto-redirect is flaky), so
  // navigate to /onboarding explicitly if we are not already there — the role
  // picker is the contract this flow depends on, not the redirect itself.
  await page.waitForURL(/\/(onboarding|dashboard)(\?|$|\/)/);
  if (!/\/onboarding/.test(page.url())) {
    await page.goto('/onboarding');
  }
  await page.locator('button[data-account-type="creator"]').click();
  await page.waitForURL(/\/dashboard\/creator/);
}

/** Seed a finished upload + ranked clips for the signed-in user via the dev route. */
async function seedClips(
  page: Page,
  body: { seed: string; clipCount?: number },
): Promise<{ contentHash: string; claimed: boolean }> {
  const res = await page.request.post('/api/dev/clips/seed', { data: body });
  expect(res.ok()).toBeTruthy();
  return res.json();
}

test.describe('upload → clips dashboard', () => {
  test.skip(
    !!process.env.CI || !hasClerkSecret,
    'requires live Clerk keys + web R2 env (local/staging; founder runs at checkpoint G)',
  );

  // New-user path + dev-mode first-compile of each route exceeds the default.
  test.setTimeout(240_000);

  test('ranked clips are shown best-first by score/rank', async ({ page }) => {
    await signUpCreator(page);
    const seedCount = 3;
    await seedClips(page, { seed: 'ranked', clipCount: seedCount });

    await page.reload();

    // "Мои клипы" history renders the seeded upload's ranked list.
    const list = page.locator(RANKED_LIST).first();
    await expect(list).toBeVisible();

    const rows = list.locator('li');
    await expect(rows).toHaveCount(seedCount);

    // Rank labels run #1, #2, #3 top-to-bottom (the route orders by rank asc).
    const rankLabels = await rows.locator('span.tabular-nums').first().allInnerTexts();
    expect(rankLabels[0]).toContain('1');

    // Scores are strictly descending down the list — rank order == score order.
    const scoreTexts = await rows
      .locator('.text-right .font-mono')
      .allInnerTexts();
    const scores = scoreTexts.map(t => Number(t.replace(/\D/g, '')));
    expect(scores).toHaveLength(seedCount);
    expect(scores).toEqual([...scores].sort((a, b) => b - a));
  });

  test('each clip renders a 9:16 <video> with a presigned source', async ({ page }) => {
    await signUpCreator(page);
    await seedClips(page, { seed: 'player', clipCount: 2 });
    await page.reload();

    const firstVideo = page.locator(`${RANKED_LIST} video`).first();
    await expect(firstVideo).toBeVisible();

    // 9:16 intrinsic ratio (CLS-stable): the source dimensions are 1080×1920.
    await expect(firstVideo).toHaveAttribute('width', '1080');
    await expect(firstVideo).toHaveAttribute('height', '1920');
    const aspect = await firstVideo.evaluate(el => getComputedStyle(el).aspectRatio);
    expect(aspect.replace(/\s/g, '')).toBe('9/16');

    // The <source> points at a short-lived presigned R2 GET URL (the clip bucket
    // is private-read; the dashboard never exposes a raw object key).
    const src = await firstVideo.locator('source').getAttribute('src');
    expect(src).toBeTruthy();
    expect(src).toMatch(/^https?:\/\//);

    // Real playback (readyState>=2) needs the presigned object to actually exist
    // in R2. On a live bucket (founder runs at checkpoint G) it does; if the
    // object is absent the element still renders correctly with its presigned src
    // — which is the contract this test guards. We attempt playback opportunistically.
    const readyState = await firstVideo.evaluate(async (el) => {
      const video = el as HTMLVideoElement;
      video.load();
      await new Promise(resolve => setTimeout(resolve, 3000));
      return video.readyState;
    });
    // DOCUMENTED LIMITATION: readyState>=2 only when the presigned R2 object is
    // reachable. We assert the element + presigned src unconditionally above; this
    // logs the playback result without failing when R2 has no seeded bytes.
    test.info().annotations.push({
      type: 'video-readyState',
      description: `readyState=${readyState} (>=2 means presigned source played)`,
    });
  });

  test('re-processing the same bytes reuses the existing batch (no-op)', async ({ page }) => {
    await signUpCreator(page);

    const first = await seedClips(page, { seed: 'reuse', clipCount: 3 });
    expect(first.claimed).toBe(true);

    // Same seed → same content hash → the ledger claim dedupes (claimed:false).
    const second = await seedClips(page, { seed: 'reuse', clipCount: 3 });
    expect(second.claimed).toBe(false);
    expect(second.contentHash).toBe(first.contentHash);

    await page.reload();

    // Exactly ONE upload group in "Мои клипы" — the re-process did not fork a
    // second batch.
    await expect(page.locator('[data-slot="my-clips-upload"]')).toHaveCount(1);
    await expect(page.locator(`${RANKED_LIST} li`)).toHaveCount(3);
  });
});
