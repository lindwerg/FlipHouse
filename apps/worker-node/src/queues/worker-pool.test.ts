import { expect, test } from 'vitest';

import { GPU_GLOBAL_CONCURRENCY } from './queue-config.js';
import { isGpuQueue, planWorkerPool, redisConnectionFromUrl } from './worker-pool.js';

test('isGpuQueue flags only the two GPU queues', () => {
  expect(isGpuQueue('gpu-asr')).toBe(true);
  expect(isGpuQueue('gpu-score')).toBe(true);
  expect(isGpuQueue('cpu')).toBe(false);
  expect(isGpuQueue('transcode')).toBe(false);
  expect(isGpuQueue('publish')).toBe(false);
});

test('planWorkerPool sizes one plan per queue in order', () => {
  expect(planWorkerPool().map((p) => p.queue)).toEqual([
    'transcode',
    'gpu-asr',
    'gpu-score',
    'cpu',
    'publish',
  ]);
});

test('GPU queues carry the cluster-wide valve; CPU queues do not', () => {
  const byQueue = new Map(planWorkerPool().map((p) => [p.queue, p]));

  expect(byQueue.get('gpu-asr')).toMatchObject({ concurrency: 1, globalConcurrency: GPU_GLOBAL_CONCURRENCY });
  expect(byQueue.get('gpu-score')).toMatchObject({ concurrency: 1, globalConcurrency: GPU_GLOBAL_CONCURRENCY });
  expect(byQueue.get('cpu')?.globalConcurrency).toBeUndefined();
  expect(byQueue.get('publish')?.globalConcurrency).toBeUndefined();
});

test('redisConnectionFromUrl parses host + port with the worker blocking knob', () => {
  expect(redisConnectionFromUrl('redis://localhost:6379')).toEqual({
    host: 'localhost',
    port: 6379,
    maxRetriesPerRequest: null,
  });
});

test('redisConnectionFromUrl defaults the port to 6379 when omitted', () => {
  expect(redisConnectionFromUrl('redis://cache')).toMatchObject({ host: 'cache', port: 6379 });
});

test('redisConnectionFromUrl carries credentials when present', () => {
  expect(redisConnectionFromUrl('redis://user:s3cret@h:6380')).toEqual({
    host: 'h',
    port: 6380,
    maxRetriesPerRequest: null,
    username: 'user',
    password: 's3cret',
  });
});

test('redisConnectionFromUrl enables TLS for the rediss scheme', () => {
  const conn = redisConnectionFromUrl('rediss://secure-host:6379') as { tls?: unknown };
  expect(conn.tls).toEqual({});
});
