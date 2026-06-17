import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      all: true,
      include: ['src/**/*.ts'],
      // *.itest.ts: integration tests (real Redis/Docker) run in a separate job.
      // worker/: real-BullMQ-Worker bootstrap, verified by integration tests.
      exclude: ['**/*.test.ts', '**/*.itest.ts', 'src/worker/**'],
      thresholds: { statements: 100, branches: 100, functions: 100, lines: 100 },
    },
  },
});
