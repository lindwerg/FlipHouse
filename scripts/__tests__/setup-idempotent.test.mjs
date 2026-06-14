import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const setup = path.join(root, 'scripts', 'setup.sh');

test('setup.sh is idempotent — second run does not re-clone existing vendor repos', () => {
  // vendor/openshorts already exists (vendored in Шаг 0.9), so a --dry-run must
  // report it as a skip, not a clone.
  const result = spawnSync('bash', [setup, '--dry-run'], { cwd: root, encoding: 'utf8' });
  const output = `${result.stdout ?? ''}${result.stderr ?? ''}`;
  assert.equal(result.status, 0, `setup.sh --dry-run exited non-zero:\n${output}`);
  assert.match(output, /skip .*openshorts/i, 'existing vendor repo must be skipped, not re-cloned');
});

test('STATE.md marks P0 complete and points to P1', () => {
  const state = readFileSync(path.join(root, 'STATE.md'), 'utf8');
  // P0 phase header must be complete (✅) and the next-step pointer must name P1.
  assert.match(state, /P0[^\n]*✅/, 'STATE.md must mark phase P0 complete (✅)');
  assert.match(state, /Следующ[^\n]*P1/i, 'STATE.md must point the next step at P1');
});
