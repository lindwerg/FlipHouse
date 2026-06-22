import type { OwnerClips } from '@fliphouse/db';
import { auth } from '@clerk/nextjs/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// /clips route: Clerk auth → validate contentHash → owner-scoped clip read.
// listClipsForOwner is mocked (its DB behaviour is covered by the PGlite repo
// test); db + auth are the only seams. The route reads db from @/libs/DB and the
// repo fn from @fliphouse/db at call-time, so hoisted holders let each test swap
// the listClipsForOwner result.
const holder = vi.hoisted(() => ({
  result: null as OwnerClips | null,
  listClipsForOwner: vi.fn(),
}));

vi.mock('@/libs/DB', () => ({ db: {} }));
vi.mock('@clerk/nextjs/server', () => ({ auth: vi.fn() }));
vi.mock('@fliphouse/db', () => ({
  listClipsForOwner: holder.listClipsForOwner,
}));
// The clip bucket is private: clipUrl is resolved to a presigned GET URL. Mock the
// AWS presign seam (its logic is covered in r2-presign.test.ts) so this route test
// asserts auth/fetch/response wiring deterministically, without a live S3 client.
vi.mock('@/features/results/r2-presign', () => ({
  presignClipUrl: vi.fn(async (key: string) => `https://signed.example.com/${key}`),
}));

const { GET } = await import('./route');

const HASH = 'a'.repeat(64);

function req(): Request {
  return new Request(`http://localhost/api/uploads/${HASH}/clips`, { method: 'GET' });
}

function params(contentHash = HASH): { params: Promise<{ contentHash: string }> } {
  return { params: Promise.resolve({ contentHash }) };
}

const OWNED: OwnerClips = {
  status: 'done',
  clips: [
    {
      rank: 0,
      score: '87.5000',
      startTime: '12.000',
      endTime: '41.500',
      durationS: '29.500',
      width: 1080,
      height: 1920,
      clipUrl: 'clips/a/clip_00.mp4',
      title: 'best',
    },
  ],
};

beforeEach(() => {
  vi.mocked(auth).mockResolvedValue({ userId: 'user_1' } as never);
  holder.listClipsForOwner.mockReset();
  holder.listClipsForOwner.mockResolvedValue(OWNED);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('GET /api/uploads/[contentHash]/clips', () => {
  it('returns 401 when there is no signed-in user', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: null } as never);

    const res = await GET(req(), params());

    expect(res.status).toBe(401);
    expect(holder.listClipsForOwner).not.toHaveBeenCalled();
  });

  it('returns 400 for an invalid contentHash and never touches the DB', async () => {
    const res = await GET(req(), params('not-a-hash'));

    expect(res.status).toBe(400);
    expect(holder.listClipsForOwner).not.toHaveBeenCalled();
  });

  it('returns 404 when the row is missing or owned by another user', async () => {
    holder.listClipsForOwner.mockResolvedValue(null);

    const res = await GET(req(), params());

    expect(res.status).toBe(404);
  });

  it('returns 200 with the status and dashboard-shaped clips (coerced + URL-built)', async () => {
    const res = await GET(req(), params());
    const json = await res.json();

    expect(res.status).toBe(200);
    expect(res.headers.get('cache-control')).toContain('no-store');
    expect(json.status).toBe('done');
    expect(json.clips).toHaveLength(1);
    expect(json.clips[0]).toEqual({
      rank: 0,
      score: 87.5,
      startTime: 12,
      endTime: 41.5,
      durationS: 29.5,
      width: 1080,
      height: 1920,
      clipUrl: 'https://signed.example.com/clips/a/clip_00.mp4',
      title: 'best',
    });
  });

  it('passes the authed userId as the ownership key to listClipsForOwner', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: 'owner_x' } as never);

    await GET(req(), params());

    expect(holder.listClipsForOwner).toHaveBeenCalledWith(expect.anything(), HASH, 'owner_x');
  });
});
