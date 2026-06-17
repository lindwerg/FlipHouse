import { defineConfig } from 'vitest/config';

// Integration tests spin real Redis/Postgres via testcontainers (Docker). They
// live in *.itest.ts, run in a separate job, and are NOT under the unit
// 100%-coverage gate — they verify cross-component behavior on a real broker.
export default defineConfig({
  test: {
    include: ['src/**/*.itest.ts'],
    testTimeout: 60_000,
    hookTimeout: 180_000,
  },
});
