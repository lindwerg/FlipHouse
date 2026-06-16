import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { defineConfig, devices } from '@playwright/test';

// Load .env.local (live dev Clerk keys) into the Playwright process so
// globalSetup (clerkSetup) and the authenticated onboarding spec can see them.
// Next loads these for the dev server itself; @next/env / dotenv aren't exposed
// to this process under pnpm, so we parse the file directly (KEY=VALUE only).
// The public smoke spec needs none of this; the auth spec self-skips without keys.
function loadEnvLocal(): void {
  const file = path.resolve(process.cwd(), '.env.local');

  if (!existsSync(file)) {
    return;
  }

  for (const line of readFileSync(file, 'utf8').split('\n')) {
    const match = line.match(/^\s*([\w.]+)\s*=\s*(.*?)\s*$/);
    const key = match?.[1];

    if (!key || process.env[key] !== undefined) {
      continue;
    }

    const raw = match[2] ?? '';
    const value
      = (raw.startsWith('"') && raw.endsWith('"'))
        || (raw.startsWith('\'') && raw.endsWith('\''))
        ? raw.slice(1, -1)
        : raw;
    process.env[key] = value;
  }
}

loadEnvLocal();

// Playwright baseline for FlipHouse. P1.11 adds an authenticated onboarding spec
// driven by @clerk/testing (Testing Token + clerk_test sign-up). It runs locally
// against the live dev Clerk instance and self-skips in CI (no secrets there);
// heavy auth/visual e2e is otherwise consolidated in P1.16. The public landing
// smoke needs no Clerk credentials (keyless on public routes).
const PORT = process.env.PORT ?? '3008';
const baseURL = `http://localhost:${PORT}`;

// The staging deploy smoke (deploy-smoke.e2e.ts) hits an external https domain
// via STAGING_URL and needs no local server; skip booting the pglite dev server
// in that mode. Local/CI e2e (STAGING_URL unset) keeps the webServer as before.
const isStagingSmoke = !!process.env.STAGING_URL;

export default defineConfig({
  testDir: './tests',
  testMatch: '*.@(e2e|smoke).?(c|m)[jt]s?(x)',
  timeout: 30 * 1000,
  forbidOnly: !!process.env.CI,
  globalSetup: './tests/global-setup',
  reporter: process.env.CI ? 'github' : 'list',
  expect: {
    timeout: 15 * 1000,
  },
  webServer: isStagingSmoke
    ? undefined
    : {
        command: 'pglite-server -m 100 -p 54329 --run \'run-s db:migrate dev:next\'',
        url: baseURL,
        timeout: 180 * 1000,
        reuseExistingServer: !process.env.CI,
        gracefulShutdown: { signal: 'SIGTERM', timeout: 2 * 1000 },
        env: {
          BROWSER_TO_TERMINAL_DISABLED: 'true',
          NEXT_PUBLIC_APP_URL: baseURL,
          PORT,
        },
      },
  use: {
    baseURL,
    trace: process.env.CI ? 'on-first-retry' : 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
