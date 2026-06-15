import { beforeEach, expect, test, vi } from 'vitest';
import { db } from '@/libs/DB';
import { buildHealth, probeDb, probeRedis } from '@/libs/health';
import { redis } from '@/libs/Redis';

vi.mock('@/libs/DB', () => ({ db: { execute: vi.fn() } }));
vi.mock('@/libs/Redis', () => ({ redis: { ping: vi.fn() } }));

beforeEach(() => {
  vi.mocked(db.execute).mockReset();
  vi.mocked(redis.ping).mockReset();
});

test('buildHealth maps db up to status ok and http 200', () => {
  expect(buildHealth({ db: 'up', redis: 'up' })).toEqual({
    payload: { status: 'ok', db: 'up', redis: 'up' },
    httpStatus: 200,
  });
});

test('buildHealth maps db down to status down and http 503 regardless of redis', () => {
  expect(buildHealth({ db: 'down', redis: 'up' })).toEqual({
    payload: { status: 'down', db: 'down', redis: 'up' },
    httpStatus: 503,
  });
});

test('probeRedis returns up when ping resolves', async () => {
  vi.mocked(redis.ping).mockResolvedValue('PONG');
  expect(await probeRedis()).toBe('up');
});

test('probeRedis returns down when ping rejects', async () => {
  vi.mocked(redis.ping).mockRejectedValue(new Error('connection refused'));
  expect(await probeRedis()).toBe('down');
});

test('probeDb returns up when select 1 resolves', async () => {
  vi.mocked(db.execute).mockResolvedValue(undefined as never);
  expect(await probeDb()).toBe('up');
});

test('probeDb returns down when the query throws', async () => {
  vi.mocked(db.execute).mockRejectedValue(new Error('connection refused'));
  expect(await probeDb()).toBe('down');
});
