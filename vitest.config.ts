import { defineConfig } from 'vitest/config';

// Root Vitest config — workspace aggregate via `test.projects` (Шаг 0.5).
// Each member package owns its vitest.config.ts; adding a new TS package is
// auto-discovered through these globs. `pnpm test`/`pnpm coverage` run the lot.
export default defineConfig({
  test: {
    projects: [
      // Tooling guard tests live at the root, not inside a package.
      {
        test: {
          name: 'tooling',
          root: import.meta.dirname,
          include: ['tooling/**/*.test.ts'],
        },
      },
      'packages/*/vitest.config.ts',
      'apps/*/vitest.config.ts',
    ],
  },
});
