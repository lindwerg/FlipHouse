import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeAll, describe, expect, test } from 'vitest';

// The token pipeline is dev-tooling: tokens/*.json (source of truth) ->
// style-dictionary.config.mjs -> src/styles/tokens.css. We exercise the real
// `pnpm tokens` code path by spawning the generator as a subprocess (type-safe,
// no .mjs import into TS) and asserting on the emitted CSS.
const tokensDir = dirname(fileURLToPath(import.meta.url));
const webDir = resolve(tokensDir, '..');
const configPath = resolve(webDir, 'style-dictionary.config.mjs');
const cssPath = resolve(webDir, 'src/styles/tokens.css');

function generate(): string {
  execFileSync(process.execPath, [configPath], { cwd: webDir, stdio: 'pipe' });
  return readFileSync(cssPath, 'utf8');
}

describe('design tokens', () => {
  let css: string;

  beforeAll(() => {
    css = generate();
  });

  test('generated tokens.css contains all semantic shadcn tokens', () => {
    const required = [
      '--background',
      '--foreground',
      '--primary',
      '--ring',
      '--card',
      '--border',
      '--muted',
      '--color-glass',
      '--glow',
      '--grain',
    ];

    for (const name of required) {
      expect(css).toContain(name);
    }
  });

  test('primary equals violet accent oklch(68% 0.20 280)', () => {
    expect(css).toContain('--primary: oklch(68% 0.20 280)');
  });

  test('ring equals cyan accent-2 oklch(72% 0.18 200)', () => {
    expect(css).toContain('--ring: oklch(72% 0.18 200)');
  });

  test('non-color tokens include --text-hero clamp and --ease-out-expo', () => {
    expect(css).toContain('--text-hero: clamp(3rem, 1rem + 7vw, 8rem)');
    expect(css).toContain('--ease-out-expo: cubic-bezier(0.16, 1, 0.3, 1)');
  });

  test('tokens.css is regenerable and deterministic', () => {
    const first = generate();
    const second = generate();

    expect(second).toBe(first);
  });
});
