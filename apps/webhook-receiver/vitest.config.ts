import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      all: true,
      include: ['src/**/*.ts'],
      // server.ts is the HTTP bootstrap (real http.createServer + process.env +
      // signals) — integration-only. Every pure unit (verify-hmac, handle-callback,
      // gpu-callback-types) is fully covered.
      exclude: ['**/*.test.ts', 'src/server.ts'],
      thresholds: { statements: 100, branches: 100, functions: 100, lines: 100 },
    },
  },
});
