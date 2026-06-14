import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      all: true,
      include: ['src/**/*.ts'],
      // *.test.ts: tests are not coverage targets; __meta__: the gate meta-test;
      // index.ts: a pure re-export barrel that the unit tests import through, not directly.
      exclude: ['**/*.test.ts', 'src/__meta__/**', 'src/index.ts'],
      thresholds: { statements: 100, branches: 100, functions: 100, lines: 100 },
    },
  },
});
