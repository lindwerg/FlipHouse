import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const adr = path.resolve(here, '../0001-design-dependency-sources.md');

function readAdr() {
  return readFileSync(adr, 'utf8');
}

test('ADR-0001 lists ai-elements, kibo, shadergradient, motion install commands', () => {
  const text = readAdr();
  // Exact install commands from docs/02 §3.1 / §6 — P-phases must not re-invent the source.
  const commands = [
    'npx ai-elements add prompt-input',
    'npx kibo-ui add dropzone',
    '@shadergradient/react',
    'npm i motion',
  ];
  for (const cmd of commands) {
    assert.ok(text.includes(cmd), `ADR-0001 must list install command: ${cmd}`);
  }
});

test('ADR-0001 marks paper-design/shaders and whatamesh as avoided', () => {
  const text = readAdr();
  const lower = text.toLowerCase();
  assert.ok(
    lower.includes('paper-design/shaders'),
    'ADR-0001 must mention paper-design/shaders in the avoided list',
  );
  assert.ok(lower.includes('whatamesh'), 'ADR-0001 must mention whatamesh in the avoided list');
  // Each avoided entry must be explicitly flagged as avoided.
  assert.ok(
    lower.includes('avoid') || lower.includes('избег'),
    'ADR-0001 must explicitly mark avoided dependencies',
  );
});
