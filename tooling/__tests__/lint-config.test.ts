import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { ESLint } from 'eslint';
import { test, expect } from 'vitest';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');

test('eslint flags an unused variable in a fixture file', async () => {
  const eslint = new ESLint({ ignore: false, cwd: root });
  const fixture = path.join(root, 'tooling/__fixtures__/bad-unused.ts');
  const results = await eslint.lintFiles([fixture]);
  const messages = results.flatMap((result) => result.messages);
  const hasUnusedVar = messages.some((message) =>
    (message.ruleId ?? '').includes('no-unused-vars'),
  );
  expect(hasUnusedVar).toBe(true);
});

test('tsconfig.base enables strict and noUncheckedIndexedAccess', () => {
  const tsconfig = JSON.parse(readFileSync(path.join(root, 'tsconfig.base.json'), 'utf8'));
  expect(tsconfig.compilerOptions.strict).toBe(true);
  expect(tsconfig.compilerOptions.noUncheckedIndexedAccess).toBe(true);
});
