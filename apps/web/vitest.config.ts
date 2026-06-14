import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    // Unit tests only. Playwright e2e specs live in e2e/ and run via `playwright test`.
    include: ['src/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      all: true,
      // Business logic only. Presentational app/ surfaces (page, route) are
      // covered by Playwright e2e per the test protocol §1.4.
      include: ['src/lib/**/*.ts'],
      exclude: ['**/*.test.ts'],
      thresholds: { statements: 100, branches: 100, functions: 100, lines: 100 },
    },
  },
});
