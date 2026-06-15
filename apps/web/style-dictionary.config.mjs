// FlipHouse design-token generator (docs/02 §4).
//
// Source of truth: tokens/*.json. This script is the ONLY producer of
// src/styles/tokens.css and tokens/COLORS.md — both are build artifacts and are
// never hand-edited (immutability). Run via `pnpm tokens`.
//
// Determinism guarantees (tested by tokens/tokens.test.ts):
//   - custom CSS format with NO timestamp header,
//   - no color transform, so oklch values are emitted verbatim,
//   - output paths anchored to this file (cwd-independent).
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import StyleDictionary from 'style-dictionary';

const webDir = dirname(fileURLToPath(import.meta.url));

// CSS custom-property name from a namespaced token path: the first segment is the
// namespace (semantic / nonColor / primitive) and is dropped, e.g.
// ['semantic', 'color', 'glass'] -> --color-glass, ['nonColor', 'text-hero'] -> --text-hero.
const cssVarName = token => `--${token.path.slice(1).join('-')}`;
// DTCG tokens carry the resolved value on $value; fall back to .value for safety.
const cssValue = token => token.$value ?? token.value;
const cssDeclaration = token => `  ${cssVarName(token)}: ${cssValue(token)};`;

const isSemantic = token => token.path[0] === 'semantic';
const isNonColor = token => token.path[0] === 'nonColor';

// :root carries the dark AI-tech palette as the baseline (dark is the default
// direction) plus the non-color tokens; .dark mirrors the colour tokens so the
// explicit `<html class="dark">` is authoritative too.
StyleDictionary.registerFormat({
  name: 'fliphouse/css',
  format: ({ dictionary }) => {
    const colorTokens = dictionary.allTokens.filter(isSemantic);
    const nonColorTokens = dictionary.allTokens.filter(isNonColor);
    const root = [...colorTokens, ...nonColorTokens].map(cssDeclaration).join('\n');
    const dark = colorTokens.map(cssDeclaration).join('\n');

    return `:root {\n${root}\n}\n\n.dark {\n${dark}\n}\n`;
  },
});

// Human-readable colour reference for design review (checkpoint B).
StyleDictionary.registerFormat({
  name: 'fliphouse/colors-md',
  format: ({ dictionary }) => {
    const rows = dictionary.allTokens
      .filter(isSemantic)
      .filter(token => String(cssValue(token)).includes('oklch'))
      .map(token => `| \`${cssVarName(token)}\` | \`${cssValue(token)}\` |`)
      .join('\n');

    return `# FlipHouse Colors (generated — do not edit)\n\n`
      + `Dark AI-tech palette. Source of truth: \`tokens/*.json\`. `
      + `Regenerate with \`pnpm tokens\`.\n\n`
      + `| Token | oklch |\n|---|---|\n${rows}\n`;
  },
});

const sd = new StyleDictionary({
  source: [resolve(webDir, 'tokens/*.json')],
  log: { verbosity: 'silent', warnings: 'disabled' },
  platforms: {
    css: {
      // Only a name transform (avoids token-name collisions); deliberately NO
      // color transform so oklch strings stay byte-for-byte from the JSON.
      transforms: ['name/kebab'],
      buildPath: `${webDir}/`,
      files: [
        { destination: 'src/styles/tokens.css', format: 'fliphouse/css' },
        { destination: 'tokens/COLORS.md', format: 'fliphouse/colors-md' },
      ],
    },
  },
});

await sd.buildAllPlatforms();
