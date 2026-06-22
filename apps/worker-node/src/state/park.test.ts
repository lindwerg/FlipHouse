import { expect, test, vi } from 'vitest';
import { ZodError } from 'zod';

import {
  MAX_PARK_MS,
  PARK_INDEX_KEY,
  PARK_KEY_TTL_SEC,
  decideParkMode,
  parkJob,
  parkKeyFor,
  parkValueSchema,
} from './park.js';
import type { ParkableJob, RedisParker } from './park.js';

// ── decideParkMode ──────────────────────────────────────────────────────────

test('decideParkMode returns inline when GPU park is disabled (the inline/CPU path)', () => {
  expect(decideParkMode({ gpuParkEnabled: false })).toEqual({ mode: 'inline' });
});

test('decideParkMode returns a park decision carrying the providerRequestId', () => {
  expect(decideParkMode({ gpuParkEnabled: true, providerRequestId: 'req_abc123' })).toEqual({
    mode: 'park',
    providerRequestId: 'req_abc123',
  });
});

test('decideParkMode throws ZodError when a park is requested without a providerRequestId', () => {
  expect(() => decideParkMode({ gpuParkEnabled: true, providerRequestId: '' })).toThrow(ZodError);
});

// ── parkKeyFor ──────────────────────────────────────────────────────────────

test('parkKeyFor builds the canonical Redis key', () => {
  expect(parkKeyFor('req_abc123')).toBe('park:req_abc123');
});

// ── parkValueSchema ─────────────────────────────────────────────────────────

test('parkValueSchema accepts the {jobId, contentHash, outputPrefix} shape', () => {
  const value = { jobId: 'asr-abc', contentHash: 'h', outputPrefix: 'intermediate/h/asr' };
  expect(parkValueSchema.parse(value)).toEqual(value);
});

test('parkValueSchema rejects a bare jobId string (legacy value shape)', () => {
  expect(parkValueSchema.safeParse('asr-abc').success).toBe(false);
});

// ── parkJob ─────────────────────────────────────────────────────────────────

function fakeRedis(): RedisParker & { set: ReturnType<typeof vi.fn>; zadd: ReturnType<typeof vi.fn> } {
  return {
    set: vi.fn(async () => 'OK' as const),
    zadd: vi.fn(async () => 1),
  };
}

test('parkJob stores the JSON value, indexes the request, and delays the job past MAX_PARK_MS', async () => {
  // Arrange
  const redis = fakeRedis();
  const moveToDelayed = vi.fn(async () => {});
  const job: ParkableJob = { id: 'asr-abc', moveToDelayed };
  const nowMs = (): number => 1_000_000;

  // Act
  const result = await parkJob({
    providerRequestId: 'req_abc123',
    job,
    token: 'tok',
    redis,
    contentHash: 'hhh',
    outputPrefix: 'intermediate/hhh/asr',
    nowMs,
  });

  // Assert
  expect(result).toEqual({ parked: true, jobId: 'asr-abc' });
  expect(redis.set).toHaveBeenCalledWith(
    'park:req_abc123',
    JSON.stringify({ jobId: 'asr-abc', contentHash: 'hhh', outputPrefix: 'intermediate/hhh/asr' }),
    'EX',
    PARK_KEY_TTL_SEC,
  );
  expect(redis.zadd).toHaveBeenCalledWith(PARK_INDEX_KEY, 1_000_000 + MAX_PARK_MS, 'req_abc123');
  expect(moveToDelayed).toHaveBeenCalledWith(1_000_000 + MAX_PARK_MS, 'tok');
});

test('parkJob rejects when the job has no id to map against', async () => {
  // Arrange
  const redis = fakeRedis();
  const job: ParkableJob = { id: undefined, moveToDelayed: vi.fn() };

  // Act + Assert
  await expect(
    parkJob({
      providerRequestId: 'req_abc123',
      job,
      token: 'tok',
      redis,
      contentHash: 'h',
      outputPrefix: 'p',
      nowMs: () => 0,
    }),
  ).rejects.toThrow(/job\.id missing/);
  expect(redis.set).not.toHaveBeenCalled();
});
