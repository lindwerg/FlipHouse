import { clerkSetup } from '@clerk/testing/playwright';

// Playwright global setup. Fetches a Clerk Testing Token (bypasses bot
// protection so automated sign-up/sign-in works) using the live dev keys from
// .env.local — loaded by playwright.config.ts via @next/env before this runs.
// When no real secret is present (fresh checkout / CI), we skip: the
// authenticated onboarding spec self-skips under the same condition, so the
// public smoke spec still runs.
export default async function globalSetup() {
  const secret = process.env.CLERK_SECRET_KEY;

  if (!secret || secret === 'sk_test_placeholder') {
    return;
  }

  await clerkSetup();
}
