import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');

// Read the root Vitest projects/workspace config, wherever it lives.
function readVitestConfig() {
  for (const rel of ['vitest.workspace.ts', 'vitest.config.ts']) {
    try {
      return readFileSync(path.join(root, rel), 'utf8');
    } catch {
      // try the next candidate
    }
  }
  throw new Error('no root vitest config found');
}

test('root pnpm test discovers and runs shared package tests', () => {
  // `pnpm test` runs the vitest projects aggregate; the verbose reporter makes
  // the executed files observable so we can prove the shared content-hash suite
  // actually ran (and was not merely configured).
  const result = spawnSync('pnpm', ['exec', 'vitest', 'run', '--reporter=verbose'], {
    cwd: root,
    encoding: 'utf8',
    timeout: 120_000,
  });
  const output = `${result.stdout ?? ''}${result.stderr ?? ''}`;
  assert.equal(result.status, 0, `aggregate run exited non-zero:\n${output}`);
  assert.match(output, /content-hash/, 'shared content-hash tests were not run');
  assert.doesNotMatch(output, /[1-9]\d* failed/, 'at least one test failed');

  // And `pnpm test` is wired to that same vitest aggregate (not `pnpm -r`).
  const pkg = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'));
  assert.match(pkg.scripts.test, /vitest/, 'root test script must run vitest');
});

test('vitest projects config includes packages and apps globs', () => {
  const cfg = readVitestConfig();
  assert.match(cfg, /packages\/\*/, 'missing packages/* project glob');
  assert.match(cfg, /apps\/\*/, 'missing apps/* project glob');
});
