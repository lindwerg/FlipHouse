import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const ciLocal = path.join(root, 'scripts', 'ci-local.sh');
const ciYaml = path.join(root, '.github', 'workflows', 'ci.yml');

test('ci-local.sh runs lint, typecheck, coverage, pytest, e2e and state-check in order', () => {
  const script = readFileSync(ciLocal, 'utf8');
  // Each pipeline stage announces itself with `### STEP: <name>`; their order in
  // the script is the order they execute under `set -e`.
  const orderedSteps = ['lint', 'typecheck', 'coverage', 'pytest', 'e2e', 'state'];
  let prevIdx = -1;
  for (const step of orderedSteps) {
    const idx = script.indexOf(`### STEP: ${step}`);
    assert.ok(idx !== -1, `ci-local.sh is missing step marker: ${step}`);
    assert.ok(idx > prevIdx, `ci-local.sh step "${step}" is out of order`);
    prevIdx = idx;
  }
});

test('workflow yaml triggers on pull_request and runs ci-local steps', () => {
  const yaml = readFileSync(ciYaml, 'utf8');
  assert.match(yaml, /pull_request/, 'workflow must trigger on pull_request');
  assert.match(
    yaml,
    /scripts\/ci-local\.sh/,
    'workflow must invoke scripts/ci-local.sh (single source of truth)',
  );
});

test(
  'ci fails fast when a TS test is red',
  // Skip when running *inside* ci-local's own node-test step — this test spawns
  // ci-local, which would otherwise recurse.
  { skip: process.env.FLIPHOUSE_CI_LOCAL ? 'recursion guard: running under ci-local' : false },
  () => {
    const probe = path.join(root, 'packages', 'shared', 'src', 'hash', 'content-hash.test.ts');
    const original = readFileSync(probe, 'utf8');
    // Reuses the file's existing `test`/`expect` imports so it lints clean and
    // fails only at the test/coverage stage.
    const injected = `${original}\ntest('___ci_failfast_probe___', () => {\n  expect(1).toBe(2);\n});\n`;
    try {
      writeFileSync(probe, injected);
      const result = spawnSync('bash', [ciLocal], { cwd: root, encoding: 'utf8', timeout: 300_000 });
      const output = `${result.stdout ?? ''}${result.stderr ?? ''}`;
      assert.match(output, /### STEP: lint/, `ci-local.sh did not start:\n${output}`);
      assert.notEqual(result.status, 0, `ci-local must fail when a TS test is red:\n${output}`);
      assert.doesNotMatch(
        output,
        /### STEP: e2e/,
        'fail-fast violated: e2e step was reached despite a red TS test',
      );
    } finally {
      writeFileSync(probe, original);
    }
  },
);
