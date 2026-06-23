import type { IngestFailureRow } from '@fliphouse/db';
import { auth } from '@clerk/nextjs/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Ingest-status poll route: Clerk auth → validate ingestId shape → owner-scoped
// failure read. findIngestFailure is mocked (its DB behaviour is covered by the
// PGlite repo test); db + auth are the only seams. The route reads db from
// @/libs/DB and the repo fn from @fliphouse/db at call-time, so a hoisted holder
// lets each test swap the findIngestFailure result.
const holder = vi.hoisted(() => ({
  findIngestFailure: vi.fn(),
}));

vi.mock('@/libs/DB', () => ({ db: {} }));
vi.mock('@clerk/nextjs/server', () => ({ auth: vi.fn() }));
vi.mock('@fliphouse/db', () => ({
  findIngestFailure: holder.findIngestFailure,
}));

const { GET } = await import('./route');

const INGEST_ID = `ingest:${'a'.repeat(64)}`;

function req(): Request {
  return new Request(`http://localhost/api/uploads/ingest/${INGEST_ID}`, { method: 'GET' });
}

function params(ingestId = INGEST_ID): { params: Promise<{ ingestId: string }> } {
  return { params: Promise.resolve({ ingestId }) };
}

const FAILURE: IngestFailureRow = {
  code: 'ip-blocked',
  message: 'YouTube заблокировал загрузку с нашего сервера.',
  createdAt: new Date('2026-06-23T00:00:00Z'),
};

beforeEach(() => {
  vi.mocked(auth).mockResolvedValue({ userId: 'user_1' } as never);
  holder.findIngestFailure.mockReset();
  holder.findIngestFailure.mockResolvedValue(null);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('GET /api/uploads/ingest/[ingestId]', () => {
  it('returns 401 when there is no signed-in user', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: null } as never);

    const res = await GET(req(), params());

    expect(res.status).toBe(401);
    expect(holder.findIngestFailure).not.toHaveBeenCalled();
  });

  it('returns 400 for a malformed ingestId and never touches the DB', async () => {
    const res = await GET(req(), params('not-an-ingest-key'));

    expect(res.status).toBe(400);
    expect(holder.findIngestFailure).not.toHaveBeenCalled();
  });

  it('returns 200 pending when no failure is recorded (still downloading)', async () => {
    const res = await GET(req(), params());
    const json = await res.json();

    expect(res.status).toBe(200);
    expect(res.headers.get('cache-control')).toContain('no-store');
    expect(json).toEqual({ status: 'pending' });
  });

  it('returns 200 failed with the recorded Russian message and code', async () => {
    holder.findIngestFailure.mockResolvedValue(FAILURE);

    const res = await GET(req(), params());
    const json = await res.json();

    expect(res.status).toBe(200);
    expect(json).toEqual({
      status: 'failed',
      code: 'ip-blocked',
      error: 'YouTube заблокировал загрузку с нашего сервера.',
    });
  });

  it('passes the authed userId as the ownership key to findIngestFailure', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: 'owner_x' } as never);

    await GET(req(), params());

    expect(holder.findIngestFailure).toHaveBeenCalledWith(expect.anything(), 'owner_x', INGEST_ID);
  });
});
