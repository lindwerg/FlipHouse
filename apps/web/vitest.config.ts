import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Headless Node baseline for FlipHouse P1. The upstream boilerplate also ships a
// browser ("ui") Vitest project (chromium via @vitest/browser-playwright) for
// *.test.tsx and hook tests; that project is intentionally NOT wired here so the
// root `vitest run` aggregate (scripts/__tests__/aggregate-test.test.mjs) stays
// green in a pure Node/CI context. Component tests come with RTL/jsdom in the
// later UI steps (1.5–1.7).
//
// T3 Env (src/libs/Env.ts) validates required vars at import time. We provide
// non-secret test defaults so unit tests run even when .env / .env.local are
// absent (e.g. a fresh CI checkout).
const TEST_ENV_DEFAULTS = {
  NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY:
    'pk_test_b3Blbi1zdGlua2J1Zy04LmNsZXJrLmFjY291bnRzLmRldiQ',
  CLERK_SECRET_KEY: 'sk_test_placeholder',
  DATABASE_URL: 'postgresql://postgres:postgres@127.0.0.1:54329/postgres',
  REDIS_PRIVATE_URL: 'redis://127.0.0.1:6379',
};

export default defineConfig({
  plugins: [react()],
  resolve: {
    tsconfigPaths: true,
  },
  test: {
    environment: 'node',
    // Token-pipeline tests live in tokens/ (dev-tooling, outside src/); the rest
    // of the suite lives under src/. Both are picked up by the root aggregate.
    include: ['src/**/*.test.ts', 'tokens/**/*.test.ts'],
    // Hook tests target the browser environment in the upstream "ui" project.
    exclude: ['src/hooks/**/*.test.ts', 'node_modules/**', '.next/**'],
    coverage: {
      include: ['src/**/*'],
      exclude: ['src/**/*.stories.{js,jsx,ts,tsx}'],
    },
    env: TEST_ENV_DEFAULTS,
  },
});
