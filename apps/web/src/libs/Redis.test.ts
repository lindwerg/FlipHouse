import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { Redis } from 'ioredis';
import { Env } from '@/libs/Env';
import { logger } from '@/libs/Logger';

// Mock the ioredis driver so no socket is opened during unit tests; each
// `new Redis()` returns a fresh stub instance with the methods we exercise.
// The implementation must be constructable (a class), since ioredis is `new`-ed.
vi.mock('ioredis', () => {
  class RedisMock {
    on = vi.fn();
    ping = vi.fn();
  }
  return { Redis: vi.fn(RedisMock) };
});

// Keep the singleton's error logging deterministic and assertable.
vi.mock('@/libs/Logger', () => ({ logger: { error: vi.fn() } }));

beforeEach(() => {
  vi.mocked(logger.error).mockReset();
});

afterEach(() => {
  vi.unstubAllEnvs();
});

test('Redis client connects using REDIS_PRIVATE_URL', async () => {
  const { redis } = await import('@/libs/Redis');

  expect(Redis).toHaveBeenCalledWith(
    Env.REDIS_PRIVATE_URL,
    expect.objectContaining({ maxRetriesPerRequest: null, lazyConnect: true }),
  );
  expect(redis).toBeDefined();
});

test('returns the same singleton on repeated import', async () => {
  const first = await import('@/libs/Redis');
  const second = await import('@/libs/Redis');

  expect(first.redis).toBe(second.redis);
});

test('attaches an error listener that logs without crashing the process', async () => {
  const { redis } = await import('@/libs/Redis');

  const errorCall = vi.mocked(redis.on).mock.calls.find(([event]) => event === 'error');
  expect(errorCall).toBeDefined();

  const handler = errorCall![1] as (error: Error) => void;
  expect(() => handler(new Error('boom'))).not.toThrow();
  expect(logger.error).toHaveBeenCalled();
});

test('throws at startup when REDIS_PRIVATE_URL is missing', async () => {
  vi.stubEnv('REDIS_PRIVATE_URL', '');
  vi.resetModules();

  await expect(import('@/libs/Env')).rejects.toThrow(/REDIS_PRIVATE_URL/);
});
