import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import importPlugin from 'eslint-plugin-import';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: [
      '**/node_modules/**',
      '**/dist/**',
      '**/.next/**',
      '**/coverage/**',
      '**/.venv/**',
      'vendor/**',
      // apps/web is the ixartz/SaaS-Boilerplate fork (P1.1) and carries its own
      // toolchain; it is validated via `pnpm --filter web ...`, not the root
      // flat-config lint. See STATE.md P1.1 notes.
      'apps/web/**',
      'tooling/__fixtures__/**',
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    languageOptions: {
      globals: { ...globals.node },
    },
    plugins: { import: importPlugin },
    rules: {
      'import/order': ['error', { 'newlines-between': 'always', alphabetize: { order: 'asc' } }],
    },
  },
  prettier,
);
