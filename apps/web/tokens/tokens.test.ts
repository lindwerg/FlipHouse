import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeAll, describe, expect, test } from 'vitest';

// The token pipeline is dev-tooling: tokens/*.json (source of truth) ->
// style-dictionary.config.mjs -> src/styles/tokens.css. We exercise the real
// `pnpm tokens` code path by spawning the generator as a subprocess (type-safe,
// no .mjs import into TS) and asserting on the emitted CSS.
//
// Direction (approved by founder at checkpoint B): "Swiss Pop" — warm off-white
// paper, near-black ink, hairline grid rules, a single hot-vermillion signal
// (action / virality) plus a cobalt secondary (marketplace / revenue). Light
// base. Reference: docs/design-reference/swiss-pop.html.
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

  test('generated tokens.css contains all semantic shadcn and signal tokens', () => {
    const required = [
      '--background',
      '--foreground',
      '--primary',
      '--ring',
      '--card',
      '--border',
      '--muted',
      '--pop',
      '--cobalt',
      '--rule-strong',
    ];

    for (const name of required) {
      expect(css).toContain(name);
    }
  });

  test('primary equals vermillion accent oklch(63% 0.244 26)', () => {
    expect(css).toContain('--primary: oklch(63% 0.244 26)');
  });

  test('cobalt signal equals oklch(48% 0.210 258)', () => {
    expect(css).toContain('--cobalt: oklch(48% 0.210 258)');
  });

  test('non-color tokens include --text-hero clamp and --ease-out-expo', () => {
    expect(css).toContain('--text-hero: clamp(3.4rem, 1.2rem + 8.6vw, 10.5rem)');
    expect(css).toContain('--ease-out-expo: cubic-bezier(0.16, 1, 0.3, 1)');
  });

  test('tokens.css is regenerable and deterministic', () => {
    const first = generate();
    const second = generate();

    expect(second).toBe(first);
  });
});
