import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const setup = path.join(root, 'scripts', 'setup.sh');

test('setup.sh is idempotent — second run does not re-clone existing vendor repos', () => {
  // Mock the presence of a vendor clone (CI checks out WITHOUT the gitignored
  // clones, so we synthesise a fake .git). --dry-run must then report it skipped,
  // never re-cloned. Only the fake dir we created is removed — a real local clone
  // is left untouched.
  const openshortsDir = path.join(root, 'vendor', 'openshorts');
  const gitDir = path.join(openshortsDir, '.git');
  const createdByTest = !existsSync(gitDir);
  if (createdByTest) {
    mkdirSync(gitDir, { recursive: true });
  }
  try {
    const result = spawnSync('bash', [setup, '--dry-run'], { cwd: root, encoding: 'utf8' });
    const output = `${result.stdout ?? ''}${result.stderr ?? ''}`;
    assert.equal(result.status, 0, `setup.sh --dry-run exited non-zero:\n${output}`);
    assert.match(output, /skip .*openshorts/i, 'present vendor repo must be skipped, not re-cloned');
  } finally {
    if (createdByTest) {
      rmSync(openshortsDir, { recursive: true, force: true });
    }
  }
});

test('STATE.md marks P0 complete and points to P1', () => {
  const state = readFileSync(path.join(root, 'STATE.md'), 'utf8');
  // P0 phase header must be complete (✅) and the next-step pointer must name P1.
  assert.match(state, /P0[^\n]*✅/, 'STATE.md must mark phase P0 complete (✅)');
  assert.match(state, /Следующ[^\n]*P1/i, 'STATE.md must point the next step at P1');
});
