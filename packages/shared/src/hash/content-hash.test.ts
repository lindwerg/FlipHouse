import { expect, test } from 'vitest';

import { jobIdFromHash, sha256Hex } from './content-hash.js';

const encode = (text: string): Uint8Array => new TextEncoder().encode(text);

test('sha256Hex returns deterministic 64-char lowercase hex for given bytes', () => {
  const bytes = encode('fliphouse');
  const hash = sha256Hex(bytes);

  expect(hash).toHaveLength(64);
  expect(hash).toMatch(/^[0-9a-f]{64}$/);
  expect(sha256Hex(bytes)).toBe(hash);
});

test('sha256Hex differs for different inputs', () => {
  expect(sha256Hex(encode('fliphouse'))).not.toBe(sha256Hex(encode('fliphouse!')));
});

test('jobIdFromHash prefixes hash with flow:', () => {
  const hash = sha256Hex(encode('fliphouse'));

  expect(jobIdFromHash(hash)).toBe(`flow:${hash}`);
});
