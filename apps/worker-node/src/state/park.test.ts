import { expect, test, vi } from 'vitest';
import { ZodError } from 'zod';

import {
  PARK_KEY_TTL_SEC,
  decideParkMode,
  parkJob,
  parkKeyFor,
  resumeParkedJob,
} from './park.js';
import type { ParkableJob, RedisParker } from './park.js';

// ── decideParkMode ──────────────────────────────────────────────────────────

test('decideParkMode returns inline when GPU park is disabled (the P2 CPU path)', () => {
  expect(decideParkMode({ gpuParkEnabled: false })).toEqual({ mode: 'inline' });
});

test('decideParkMode returns a park decision carrying the providerRequestId', () => {
  expect(decideParkMode({ gpuParkEnabled: true, providerRequestId: 'rep_abc123' })).toEqual({
    mode: 'park',
    providerRequestId: 'rep_abc123',
  });
});

test('decideParkMode throws ZodError when a park is requested without a providerRequestId', () => {
  expect(() => decideParkMode({ gpuParkEnabled: true, providerRequestId: '' })).toThrow(ZodError);
});

// ── parkKeyFor ──────────────────────────────────────────────────────────────

test('parkKeyFor builds the canonical Redis key', () => {
  expect(parkKeyFor('rep_abc123')).toBe('park:rep_abc123');
});

// ── parkJob ─────────────────────────────────────────────────────────────────

test('parkJob runs inline without touching Redis when the decision is inline', async () => {
  // Arrange
  const redis = { set: vi.fn(), getdel: vi.fn() } satisfies RedisParker;
  const job: ParkableJob = { id: 'asr-abc', moveToWaitingChildren: vi.fn() };

  // Act
  const result = await parkJob({ decision: { mode: 'inline' }, job, token: 'tok', redis });

  // Assert
  expect(result).toEqual({ parked: false });
  expect(redis.set).not.toHaveBeenCalled();
  expect(job.moveToWaitingChildren).not.toHaveBeenCalled();
});

test('parkJob stores the mapping with a TTL and parks the job for the GPU path', async () => {
  // Arrange
  const redis = {
    set: vi.fn(async () => 'OK' as const),
    getdel: vi.fn(),
  } satisfies RedisParker;
  const job: ParkableJob = { id: 'asr-abc', moveToWaitingChildren: vi.fn(async () => true) };

  // Act
  const result = await parkJob({
    decision: { mode: 'park', providerRequestId: 'rep_abc123' },
    job,
    token: 'tok',
    redis,
  });

  // Assert
  expect(result).toEqual({ parked: true });
  expect(redis.set).toHaveBeenCalledWith('park:rep_abc123', 'asr-abc', 'EX', PARK_KEY_TTL_SEC);
  expect(job.moveToWaitingChildren).toHaveBeenCalledWith('tok');
});

test('parkJob rejects when the job has no id to map against', async () => {
  // Arrange
  const redis = { set: vi.fn(async () => 'OK' as const), getdel: vi.fn() } satisfies RedisParker;
  const job: ParkableJob = { id: undefined, moveToWaitingChildren: vi.fn() };

  // Act + Assert
  await expect(
    parkJob({ decision: { mode: 'park', providerRequestId: 'rep_abc123' }, job, token: 'tok', redis }),
  ).rejects.toThrow(/job\.id missing/);
  expect(redis.set).not.toHaveBeenCalled();
});

// ── resumeParkedJob ─────────────────────────────────────────────────────────

test('resumeParkedJob resumes the mapped job when the atomic GETDEL finds the key', async () => {
  // Arrange
  const redis = {
    set: vi.fn(),
    getdel: vi.fn(async () => 'asr-abc123'),
  } satisfies RedisParker;
  const resumeJob = vi.fn(async () => {});
  const result = { ok: true };

  // Act
  const outcome = await resumeParkedJob({
    providerRequestId: 'rep_abc123',
    result,
    redis,
    resumeJob,
  });

  // Assert
  expect(outcome).toEqual({ jobId: 'asr-abc123', resumed: true });
  expect(redis.getdel).toHaveBeenCalledWith('park:rep_abc123');
  expect(resumeJob).toHaveBeenCalledWith('asr-abc123', result);
});

test('resumeParkedJob is a no-op when the key is gone (duplicate/late webhook lost the race)', async () => {
  // Arrange
  const redis = { set: vi.fn(), getdel: vi.fn(async () => null) } satisfies RedisParker;
  const resumeJob = vi.fn(async () => {});

  // Act
  const outcome = await resumeParkedJob({
    providerRequestId: 'rep_abc123',
    result: { ok: true },
    redis,
    resumeJob,
  });

  // Assert
  expect(outcome).toEqual({ jobId: null, resumed: false });
  expect(resumeJob).not.toHaveBeenCalled();
});

test('resumeParkedJob propagates a failure from the underlying resume', async () => {
  // Arrange
  const redis = { set: vi.fn(), getdel: vi.fn(async () => 'asr-abc123') } satisfies RedisParker;
  const resumeJob = vi.fn(async () => {
    throw new Error('BullMQ error');
  });

  // Act + Assert
  await expect(
    resumeParkedJob({ providerRequestId: 'rep_abc123', result: { ok: true }, redis, resumeJob }),
  ).rejects.toThrow('BullMQ error');
});
