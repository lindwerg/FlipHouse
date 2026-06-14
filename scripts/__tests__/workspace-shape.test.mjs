import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');

function readJson(relPath) {
  return JSON.parse(readFileSync(path.join(root, relPath), 'utf8'));
}

// Minimal dependency-free parse of the `packages:` sequence in pnpm-workspace.yaml.
function parseWorkspacePackages(yamlText) {
  const lines = yamlText.split(/\r?\n/);
  const packages = [];
  let inPackages = false;
  for (const line of lines) {
    if (/^packages:\s*$/.test(line)) {
      inPackages = true;
      continue;
    }
    if (!inPackages) continue;
    const item = line.match(/^\s*-\s*['"]?([^'"#]+?)['"]?\s*$/);
    if (item) {
      packages.push(item[1]);
    } else if (/^\S/.test(line)) {
      break; // reached the next top-level key
    }
  }
  return packages;
}

test('pnpm-workspace.yaml lists apps, services, packages globs', () => {
  const yamlText = readFileSync(path.join(root, 'pnpm-workspace.yaml'), 'utf8');
  const packages = parseWorkspacePackages(yamlText);
  assert.ok(packages.includes('apps/*'), 'missing apps/* glob');
  assert.ok(packages.includes('services/*'), 'missing services/* glob');
  assert.ok(packages.includes('packages/*'), 'missing packages/* glob');
});

test('root package.json pins pnpm and node engine', () => {
  const pkg = readJson('package.json');
  assert.ok(
    typeof pkg.packageManager === 'string' && pkg.packageManager.startsWith('pnpm@'),
    'packageManager must start with pnpm@',
  );
  assert.ok(pkg.engines && pkg.engines.node, 'engines.node must be present');
});

test('root package.json exposes aggregate scripts', () => {
  const pkg = readJson('package.json');
  for (const name of ['lint', 'typecheck', 'test', 'test:e2e', 'coverage']) {
    assert.ok(
      pkg.scripts && Object.prototype.hasOwnProperty.call(pkg.scripts, name),
      `missing aggregate script: ${name}`,
    );
  }
});
