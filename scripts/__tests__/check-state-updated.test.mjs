import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const script = path.resolve(here, '../check-state-updated.sh');

function runGuard(changedFiles) {
  return spawnSync('bash', [script], {
    env: { ...process.env, CHANGED_FILES: changedFiles },
    encoding: 'utf8',
  });
}

test('check-state-updated exits 0 when STATE.md is among changed files', () => {
  const result = runGuard('STATE.md\nfoo.ts');
  assert.equal(result.status, 0);
});

test('check-state-updated exits 1 when STATE.md missing from changed files', () => {
  const result = runGuard('foo.ts\nbar.ts');
  assert.equal(result.status, 1);
  assert.match(result.stderr, /STATE.md not updated/);
});
