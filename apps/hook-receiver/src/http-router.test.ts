import { EventEmitter } from 'node:events';

import { expect, test } from 'vitest';

import { mapOutcomeToStatus, parseRequestBody, MAX_BODY_BYTES } from './http-router.js';

const HASH = 'a'.repeat(64);

test('mapOutcomeToStatus: enqueued → 200', () => {
  expect(mapOutcomeToStatus({ kind: 'enqueued', contentHash: HASH })).toBe(200);
});

test('mapOutcomeToStatus: duplicate → 200', () => {
  expect(mapOutcomeToStatus({ kind: 'duplicate', contentHash: HASH, existing: undefined })).toBe(200);
});

test('mapOutcomeToStatus: hash-required → 422', () => {
  expect(mapOutcomeToStatus({ kind: 'hash-required', uploadId: 'tus_1' })).toBe(422);
});

test('mapOutcomeToStatus: invalid-payload → 400 (client fault, never a retryable 5xx)', () => {
  expect(mapOutcomeToStatus({ kind: 'invalid-payload' })).toBe(400);
});

test('mapOutcomeToStatus: missing-owner → 422', () => {
  expect(mapOutcomeToStatus({ kind: 'missing-owner', uploadId: 'tus_1' })).toBe(422);
});

/** A minimal readable stand-in: emits the given chunks then `end`. */
function fakeReadable(chunks: readonly Buffer[]): NodeJS.ReadableStream {
  const emitter = new EventEmitter() as unknown as NodeJS.ReadableStream;
  queueMicrotask(() => {
    for (const chunk of chunks) {
      emitter.emit('data', chunk);
    }
    emitter.emit('end');
  });
  return emitter;
}

test('parseRequestBody: valid JSON → returns the parsed object', async () => {
  const body = JSON.stringify({ Type: 'post-finish' });

  const parsed = await parseRequestBody(fakeReadable([Buffer.from(body)]));

  expect(parsed).toEqual({ Type: 'post-finish' });
});

test('parseRequestBody: body over the limit → rejects', async () => {
  const oversize = Buffer.alloc(MAX_BODY_BYTES + 1, 0x61);

  await expect(parseRequestBody(fakeReadable([oversize]))).rejects.toThrow(/too large/);
});

test('parseRequestBody: invalid JSON → rejects', async () => {
  await expect(parseRequestBody(fakeReadable([Buffer.from('{ not json')]))).rejects.toThrow();
});

test('parseRequestBody: a stream error → rejects', async () => {
  const emitter = new EventEmitter() as unknown as NodeJS.ReadableStream;
  queueMicrotask(() => emitter.emit('error', new Error('socket reset')));

  await expect(parseRequestBody(emitter)).rejects.toThrow(/socket reset/);
});
