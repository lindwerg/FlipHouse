import { describe, expect, it } from 'vitest';

// The URL-ingestion route is DISABLED: server-side downloads (YouTube blocks our
// server IP) are switched off and the UI no longer offers a paste-a-link field.
// POST now returns a 410 Gone with a clear Russian message and never enqueues a
// job — there is no auth/Redis/BullMQ seam left to mock.
const { POST } = await import('./route');

describe('POST /api/uploads/ingest (disabled)', () => {
  it('returns 410 Gone with a clear disabled message', async () => {
    const res = POST();

    expect(res.status).toBe(410);
    const json = await res.json();
    expect(json.error).toMatch(/по ссылке временно отключена/i);
  });

  it('marks the response no-store so a stale client never caches it', () => {
    const res = POST();

    expect(res.headers.get('cache-control')).toContain('no-store');
  });
});
