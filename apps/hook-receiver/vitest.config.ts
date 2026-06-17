import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      all: true,
      include: ['src/**/*.ts'],
      // server.ts / reconcile-sweep.ts: real HTTP/Redis bootstrap — integration-only.
      exclude: ['**/*.test.ts', 'src/server.ts', 'src/reconcile-sweep.ts'],
      thresholds: { statements: 100, branches: 100, functions: 100, lines: 100 },
    },
  },
});
