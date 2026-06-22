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
  // Required client var (src/libs/Env.ts) — a non-secret tusd endpoint so unit
  // tests importing Env boot without a real .env (e.g. fresh CI checkout).
  NEXT_PUBLIC_TUS_ENDPOINT: 'http://localhost:1080/files/',
  DATABASE_URL: 'postgresql://postgres:postgres@127.0.0.1:54329/postgres',
  REDIS_PRIVATE_URL: 'redis://127.0.0.1:6379',
  // Canonical BIP39 test vector mnemonic — NOT a real wallet. Lets the tron
  // provider derive its published deposit-address vector in unit tests with no
  // network and no real key material.
  TRON_HD_MNEMONIC:
    'abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about',
};

export default defineConfig({
  plugins: [react()],
  resolve: {
    tsconfigPaths: true,
  },
  test: {
    // Default env is node (API routes, libs, token pipeline). Component tests
    // (*.test.tsx) opt into jsdom per-file via a `// @vitest-environment jsdom`
    // docblock — this keeps node tests fast and avoids nested vitest projects
    // (the root aggregate references this config directly).
    environment: 'node',
    // globals:true lets @testing-library/react auto-register its afterEach
    // cleanup (unmounts between tests so repeated render() calls don't stack).
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    // Token-pipeline tests live in tokens/ (dev-tooling, outside src/) and infra
    // config-contract tests in tests/infra/ (e.g. railway.json validation); the
    // rest of the suite lives under src/. All are picked up by the root aggregate.
    // (Playwright owns tests/*.e2e.ts via its own testMatch — no overlap.)
    include: [
      'src/**/*.test.ts',
      'src/**/*.test.tsx',
      'tokens/**/*.test.ts',
      'tests/infra/**/*.test.ts',
    ],
    // Hook tests target the browser environment in the upstream "ui" project.
    exclude: ['src/hooks/**/*.test.ts', 'node_modules/**', '.next/**'],
    coverage: {
      include: ['src/**/*'],
      exclude: [
        'src/**/*.stories.{js,jsx,ts,tsx}',
        // Web Worker entry: runs only in a real Worker context (not jsdom/node),
        // so it is covered by E2E, not unit tests. The hashing it delegates to
        // (streaming-hash.ts) IS unit-tested at 100%.
        'src/features/upload/hash.worker.ts',
      ],
    },
    env: TEST_ENV_DEFAULTS,
  },
});
