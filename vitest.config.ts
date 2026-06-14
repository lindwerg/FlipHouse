import { defineConfig } from 'vitest/config';

// Root Vitest config. Full workspace/projects wiring lands in Шаг 0.5;
// for now this discovers the tooling guard tests and seeds package globs.
export default defineConfig({
  test: {
    include: ['tooling/**/*.test.ts', 'packages/**/*.test.ts', 'apps/**/*.test.ts'],
  },
});
