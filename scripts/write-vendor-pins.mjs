// Generates vendor/PINS.lock — one pinned record per vendored upstream repo.
// Run: node scripts/write-vendor-pins.mjs > vendor/PINS.lock
//
// Format (pipe-delimited): `name | url | sha | license | mode`
// - sha:     full 40-hex HEAD of the shallow clone at vendoring time.
// - license: verified against each clone's LICENSE file (NONE = no license file).
// - mode:    how P1+ may use it. `reference-only` = no-license, clean-room only,
//            NEVER lifted into production (docs/00–01 legal discipline).

import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const vendorDir = path.join(root, 'vendor');

// Curated map — license values verified against each clone's LICENSE file.
// Order is the canonical listing order in PINS.lock.
const VENDORS = [
  { name: 'openshorts', url: 'https://github.com/mutonby/openshorts', license: 'MIT', mode: 'lift+edit' },
  {
    name: 'samuraigpt-shorts',
    url: 'https://github.com/SamurAIGPT/AI-Youtube-Shorts-Generator',
    license: 'NONE',
    mode: 'reference-only',
  },
  { name: 'captacity', url: 'https://github.com/unconv/captacity', license: 'MIT', mode: 'lift+patch' },
  { name: 'lr-asd', url: 'https://github.com/Junhua-Liao/LR-ASD', license: 'MIT', mode: 'wrap' },
  { name: 'tusd', url: 'https://github.com/tus/tusd', license: 'MIT', mode: 'lift-verbatim' },
  {
    name: 'saas-boilerplate',
    url: 'https://github.com/ixartz/SaaS-Boilerplate',
    license: 'MIT',
    mode: 'lift+extend',
  },
  { name: 'launch-ui', url: 'https://github.com/launch-ui/launch-ui', license: 'MIT', mode: 'lift-sections' },
  {
    name: 'ai-elements',
    url: 'https://github.com/vercel/ai-elements',
    license: 'Apache-2.0',
    mode: 'lift-promptinput',
  },
  { name: 'kibo', url: 'https://github.com/shadcnblocks/kibo', license: 'MIT', mode: 'lift-dropzone' },
  { name: 'shadergradient', url: 'https://github.com/ruucm/shadergradient', license: 'MIT', mode: 'lift/ref' },
  { name: 'cliq', url: 'https://github.com/org-quicko/cliq', license: 'NONE', mode: 'reference-only' },
];

function headSha(name) {
  const out = execFileSync('git', ['-C', path.join(vendorDir, name), 'rev-parse', 'HEAD'], {
    encoding: 'utf8',
  });
  return out.trim();
}

function buildPins() {
  const header = '# name | url | sha | license | mode';
  const rows = VENDORS.map((v) => `${v.name} | ${v.url} | ${headSha(v.name)} | ${v.license} | ${v.mode}`);
  return [header, ...rows].join('\n') + '\n';
}

process.stdout.write(buildPins());
