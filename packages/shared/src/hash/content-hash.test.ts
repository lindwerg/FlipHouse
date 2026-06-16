import { expect, test } from 'vitest';

import {
  BULLMQ_JOBID_RE,
  flowJobId,
  isValidContentHash,
  sha256Hex,
  stageJobId,
} from './content-hash.js';

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

test('isValidContentHash accepts a 64-char lowercase hex digest', () => {
  expect(isValidContentHash(sha256Hex(encode('fliphouse')))).toBe(true);
});

test('isValidContentHash rejects uppercase, wrong length, and non-hex', () => {
  expect(isValidContentHash('A'.repeat(64))).toBe(false);
  expect(isValidContentHash('abc')).toBe(false);
  expect(isValidContentHash(`${'a'.repeat(63)}z`)).toBe(false);
});

test('flowJobId prefixes hash with flow- and contains no illegal colon', () => {
  const hash = sha256Hex(encode('fliphouse'));

  expect(flowJobId(hash)).toBe(`flow-${hash}`);
  expect(flowJobId(hash)).not.toContain(':');
  expect(flowJobId(hash)).toMatch(BULLMQ_JOBID_RE);
});

test('stageJobId joins stage and hash with a hyphen and stays jobId-legal', () => {
  const hash = sha256Hex(encode('fliphouse'));

  expect(stageJobId('transcode', hash)).toBe(`transcode-${hash}`);
  expect(stageJobId('asr', hash)).toMatch(BULLMQ_JOBID_RE);
});

test('flowJobId throws when the derived id is not a legal BullMQ jobId', () => {
  // A colon in the hash would reproduce the original spec footgun.
  expect(() => flowJobId('bad:hash')).toThrow(/illegal BullMQ jobId/);
});

test('stageJobId throws when the stage carries an illegal character', () => {
  const hash = sha256Hex(encode('fliphouse'));

  expect(() => stageJobId('score:multimodal', hash)).toThrow(/illegal BullMQ jobId/);
});
