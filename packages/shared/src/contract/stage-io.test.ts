import { expect, test } from 'vitest';

import {
  FAILURE_KINDS,
  STAGE_REQUEST_VERSION,
  artifactRefSchema,
  stageRequestSchema,
  stageResultSchema,
} from './stage-io.js';

const validRequest = {
  version: STAGE_REQUEST_VERSION,
  stage: 'transcode',
  contentHash: 'a'.repeat(64),
  ownerId: 'user_1',
  inputs: { source: 'uploads/a.mp4' },
  outputPrefix: 'intermediate/abc/transcode',
  params: { threads: 2 },
};

test('stageRequestSchema parses a well-formed request', () => {
  expect(stageRequestSchema.parse(validRequest)).toEqual(validRequest);
});

test('stageRequestSchema rejects a wrong version', () => {
  expect(stageRequestSchema.safeParse({ ...validRequest, version: 2 }).success).toBe(false);
});

test('artifactRefSchema allows optional bytes and sha256', () => {
  expect(artifactRefSchema.parse({ key: 'k' })).toEqual({ key: 'k' });
  const full = { key: 'k', bytes: 10, sha256: 'deadbeef' };
  expect(artifactRefSchema.parse(full)).toEqual(full);
});

test('stageResultSchema parses a success result', () => {
  const ok = { ok: true, outputs: [{ key: 'out/clip_000.mp4' }], metrics: { durationMs: 1200 } };
  expect(stageResultSchema.parse(ok)).toEqual(ok);
});

test('stageResultSchema parses a failure result with a kind', () => {
  const fail = { ok: false, kind: 'fatal', code: 'OPENROUTER_402', message: 'credits exhausted' };
  expect(stageResultSchema.parse(fail)).toEqual(fail);
});

test('stageResultSchema rejects an unknown failure kind', () => {
  const bad = { ok: false, kind: 'maybe', code: 'X', message: '' };
  expect(stageResultSchema.safeParse(bad).success).toBe(false);
});

test('FAILURE_KINDS enumerates fatal and retryable', () => {
  expect(FAILURE_KINDS).toEqual(['fatal', 'retryable']);
});
