import { auth } from '@clerk/nextjs/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

// The URL-ingestion route: auth-gates the request, validates the pasted link, and
// enqueues a server-side yt-dlp download job. The Clerk auth + the enqueue seam
// are mocked so the route's wiring (401 / 400 / 202 / 502) is tested with no
// Redis and no real BullMQ.
vi.mock('@clerk/nextjs/server', () => ({ auth: vi.fn() }));

const enqueueMock = vi.hoisted(() => vi.fn());
vi.mock('@/features/ingest/enqueueIngest', () => ({ enqueueIngest: enqueueMock }));

const { POST } = await import('./route');

function postRequest(body?: unknown): Request {
  return new Request('http://localhost/api/uploads/ingest', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('POST /api/uploads/ingest', () => {
  it('returns 401 when there is no signed-in user', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: null } as never);

    const res = await POST(postRequest({ url: 'https://youtu.be/abc' }));

    expect(res.status).toBe(401);
    expect(enqueueMock).not.toHaveBeenCalled();
  });

  it('returns 400 for a missing/blank url body', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: 'user_1' } as never);

    const res = await POST(postRequest({}));

    expect(res.status).toBe(400);
    expect(enqueueMock).not.toHaveBeenCalled();
  });

  it('returns 400 for a non-ingestable url (not a video host/file)', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: 'user_1' } as never);

    const res = await POST(postRequest({ url: 'https://example.com/page.html' }));

    expect(res.status).toBe(400);
    expect(enqueueMock).not.toHaveBeenCalled();
  });

  it('returns 400 for a non-JSON body', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: 'user_1' } as never);
    const req = new Request('http://localhost/api/uploads/ingest', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: 'not json',
    });

    const res = await POST(req);

    expect(res.status).toBe(400);
  });

  it('enqueues an ingest job with the server-trusted ownerId and returns 202', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: 'user_1' } as never);
    enqueueMock.mockResolvedValue(undefined);

    const res = await POST(postRequest({ url: '  https://youtu.be/abc  ' }));

    expect(res.status).toBe(202);
    const json = await res.json();
    expect(json.status).toBe('queued');
    // The ingestId is the deterministic poll key (`ingest:` + 64-hex sha256(url)).
    expect(json.ingestId).toMatch(/^ingest:[0-9a-f]{64}$/);
    // The url is trimmed; the ownerId is the Clerk userId, never the client body.
    expect(enqueueMock).toHaveBeenCalledWith({ url: 'https://youtu.be/abc', ownerId: 'user_1' });
  });

  it('returns 502 when the enqueue fails (Redis/infra)', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: 'user_1' } as never);
    enqueueMock.mockRejectedValue(new Error('redis down'));

    const res = await POST(postRequest({ url: 'https://youtu.be/abc' }));

    expect(res.status).toBe(502);
    const json = await res.json();
    expect(json.error).toBeTruthy();
  });
});
