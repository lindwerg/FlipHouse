import { beforeEach, expect, test, vi } from 'vitest';
import { GET } from '@/app/api/health/route';
import { probeDb, probeRedis } from '@/libs/health';

// Mock only the IO probes; the pure buildHealth aggregation stays real.
vi.mock('@/libs/health', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/libs/health')>();
  return { ...actual, probeDb: vi.fn(), probeRedis: vi.fn() };
});

beforeEach(() => {
  vi.mocked(probeDb).mockReset();
  vi.mocked(probeRedis).mockReset();
});

test('GET /api/health returns 200 with status ok when db and redis reachable', async () => {
  vi.mocked(probeDb).mockResolvedValue('up');
  vi.mocked(probeRedis).mockResolvedValue('up');

  const res = await GET();
  const body = await res.json();

  expect(res.status).toBe(200);
  expect(body.status).toBe('ok');
  expect(body.db).toBe('up');
  expect(body.redis).toBe('up');
});

test('GET /api/health returns 503 when db ping fails', async () => {
  vi.mocked(probeDb).mockResolvedValue('down');
  vi.mocked(probeRedis).mockResolvedValue('up');

  const res = await GET();
  const body = await res.json();

  expect(res.status).toBe(503);
  expect(body.db).toBe('down');
});

test('health check does not require auth', async () => {
  vi.mocked(probeDb).mockResolvedValue('up');
  vi.mocked(probeRedis).mockResolvedValue('down');

  // No Clerk session exists in this unit context; the route must still answer 200.
  const res = await GET();

  expect(res.status).toBe(200);
});
