import { spawnSync } from 'node:child_process';
import { existsSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { afterEach, expect, test } from 'vitest';

const here = path.dirname(fileURLToPath(import.meta.url));
const pkgDir = path.resolve(here, '..', '..'); // packages/shared
const repoRoot = path.resolve(pkgDir, '..', '..');
const uncoveredFixture = path.join(pkgDir, 'src', '__uncovered_fixture__.ts');

function runCoverage() {
  return spawnSync('pnpm', ['--filter', '@fliphouse/shared', 'coverage'], {
    cwd: repoRoot,
    encoding: 'utf8',
  });
}

afterEach(() => {
  if (existsSync(uncoveredFixture)) {
    rmSync(uncoveredFixture);
  }
});

test('coverage run fails when an uncovered exported function is added', { timeout: 60_000 }, () => {
  writeFileSync(
    uncoveredFixture,
    'export function uncovered(): number {\n  return 42;\n}\n',
    'utf8',
  );

  const result = runCoverage();
  const output = `${result.stdout ?? ''}${result.stderr ?? ''}`;

  expect(result.status).not.toBe(0);
  expect(output).toMatch(/ERROR: Coverage|threshold/i);
});

test('coverage run passes on the real fully-tested module', { timeout: 60_000 }, () => {
  const result = runCoverage();

  expect(result.status).toBe(0);
});
