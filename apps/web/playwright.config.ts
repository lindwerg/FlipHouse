import { defineConfig, devices } from '@playwright/test';

// Minimal Playwright baseline for FlipHouse P1.1. The upstream boilerplate's
// auth/visual e2e (Clerk setup/teardown, Chromatic snapshots) is deferred to the
// later auth + e2e steps (1.11 / 1.16). For the fork baseline we boot the app on
// an ephemeral PGlite server and assert the public landing renders — no Clerk
// credentials required (Clerk runs in keyless mode on public routes).
const PORT = process.env.PORT ?? '3008';
const baseURL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: './tests',
  testMatch: '*.@(e2e|smoke).?(c|m)[jt]s?(x)',
  timeout: 30 * 1000,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? 'github' : 'list',
  expect: {
    timeout: 15 * 1000,
  },
  webServer: {
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
