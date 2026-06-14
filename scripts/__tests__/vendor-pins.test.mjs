import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const vendorDir = path.join(root, 'vendor');

// The full set vendored in Шаг 0.9 — these names are the lift sources for P1+.
const EXPECTED_VENDORS = [
  'openshorts',
  'samuraigpt-shorts',
  'captacity',
  'lr-asd',
  'tusd',
  'saas-boilerplate',
  'launch-ui',
  'ai-elements',
  'kibo',
  'shadergradient',
  'cliq',
];

const SHA_RE = /^[0-9a-f]{40}$/;

// PINS.lock is pipe-delimited: `name | url | sha | license | mode`, one record
// per line. Comment (`#`) and blank lines are skipped.
function parsePins() {
  const raw = readFileSync(path.join(vendorDir, 'PINS.lock'), 'utf8');
  return raw
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0 && !line.startsWith('#'))
    .map((line) => {
      const [name, url, sha, license, mode] = line.split('|').map((cell) => cell.trim());
      return { name, url, sha, license, mode };
    });
}

test(
  'all 11 expected vendor repos are present as directories',
  // Vendor clones are git-ignored (pinned in PINS.lock, materialized locally by
  // setup.sh). CI checks out the repo WITHOUT them, so this local-integrity
  // check is skipped there — PINS.lock structure is still fully validated below.
  { skip: process.env.CI ? 'vendor clones are not materialized in CI' : false },
  () => {
    for (const name of EXPECTED_VENDORS) {
      assert.ok(
        existsSync(path.join(vendorDir, name, '.git')),
        `vendor/${name}/.git is missing — repo not cloned`,
      );
    }
  },
);

test('PINS.lock has a 40-hex SHA, url and license for every vendor', () => {
  const pins = parsePins();
  assert.equal(pins.length, EXPECTED_VENDORS.length, 'PINS.lock must have one record per vendor');

  const names = pins.map((p) => p.name).sort();
  assert.deepEqual(names, [...EXPECTED_VENDORS].sort(), 'PINS.lock names must match the expected set');

  for (const pin of pins) {
    assert.match(pin.sha, SHA_RE, `${pin.name}: sha must be 40-hex`);
    assert.ok(pin.url && pin.url.length > 0, `${pin.name}: url must be non-empty`);
    assert.ok(pin.license && pin.license.length > 0, `${pin.name}: license field must be present`);
  }
});

test('no-license vendors are marked reference-only', () => {
  const pins = parsePins();
  const byName = new Map(pins.map((p) => [p.name, p]));

  for (const name of ['samuraigpt-shorts', 'cliq']) {
    const pin = byName.get(name);
    assert.ok(pin, `${name} must be in PINS.lock`);
    assert.equal(pin.license, 'NONE', `${name}: no-license repo must be license=NONE`);
    assert.equal(pin.mode, 'reference-only', `${name}: no-license repo must be mode=reference-only`);
  }
});
