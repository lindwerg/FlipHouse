import { describe, expect, it } from 'vitest';

// The ingest-status poll route is DISABLED alongside the submit route: the URL
// download path is switched off, so GET now returns a 410 Gone regardless of the
// ingestId. No auth/db seam remains to mock.
const { GET } = await import('./route');

describe('GET /api/uploads/ingest/[ingestId] (disabled)', () => {
  it('returns 410 Gone with a clear disabled message', async () => {
    const res = GET();

    expect(res.status).toBe(410);
    const json = await res.json();
    expect(json.error).toMatch(/по ссылке временно отключена/i);
  });

  it('marks the response no-store so a stale poll never caches it', () => {
    const res = GET();

    expect(res.headers.get('cache-control')).toContain('no-store');
  });
});
