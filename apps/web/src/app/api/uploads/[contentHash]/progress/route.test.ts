import type { OwnerClips } from '@fliphouse/db';
import { auth } from '@clerk/nextjs/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// /progress SSE route: the testable surface is the pre-stream gate — Clerk auth
// (401), contentHash validation (400), ownership (404) — plus that a 200 returns
// an event-stream Response with the correct no-buffer headers. The polling loop /
// intervals / request.signal live behind a v8-ignore seam (covered by E2E), so
// the unit test asserts the headers + an immediately-aborted request closes
// cleanly without hanging.
const holder = vi.hoisted(() => ({ listClipsForOwner: vi.fn() }));

vi.mock('@/libs/DB', () => ({ db: {} }));
vi.mock('@clerk/nextjs/server', () => ({ auth: vi.fn() }));
vi.mock('@fliphouse/db', () => ({ listClipsForOwner: holder.listClipsForOwner }));

const { GET } = await import('./route');

const HASH = 'a'.repeat(64);

const OWNED: OwnerClips = { status: 'scoring', clips: [] };

function req(signal?: AbortSignal): Request {
  return new Request(`http://localhost/api/uploads/${HASH}/progress`, { method: 'GET', signal });
}

function params(contentHash = HASH): { params: Promise<{ contentHash: string }> } {
  return { params: Promise.resolve({ contentHash }) };
}

beforeEach(() => {
  vi.mocked(auth).mockResolvedValue({ userId: 'user_1' } as never);
  holder.listClipsForOwner.mockReset();
  holder.listClipsForOwner.mockResolvedValue(OWNED);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('GET /api/uploads/[contentHash]/progress', () => {
  it('returns 401 when there is no signed-in user', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: null } as never);

    const res = await GET(req(), params());

    expect(res.status).toBe(401);
  });

  it('returns 400 for an invalid contentHash', async () => {
    const res = await GET(req(), params('nope'));

    expect(res.status).toBe(400);
    expect(holder.listClipsForOwner).not.toHaveBeenCalled();
  });

  it('returns 404 when the row is missing or owned by another user', async () => {
    holder.listClipsForOwner.mockResolvedValue(null);

    const res = await GET(req(), params());

    expect(res.status).toBe(404);
  });

  it('returns a 200 event-stream with no-buffer headers for an owned row', async () => {
    // Abort immediately so the stream cleans up its timers and the test never hangs.
    const controller = new AbortController();
    controller.abort();

    const res = await GET(req(controller.signal), params());

    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toContain('text/event-stream');
    expect(res.headers.get('cache-control')).toContain('no-cache');
    expect(res.headers.get('x-accel-buffering')).toBe('no');
    // Drain to release the stream.
    await res.body?.cancel();
  });
});
