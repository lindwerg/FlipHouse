import { auth } from '@clerk/nextjs/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Upload grant route: server-side Clerk auth() returns the signed-in user's id
// plus the configured tusd endpoint so the browser uploader knows whom to stamp
// the upload's `ownerId` metadata as. No DB, no network — auth is the only mock.
vi.mock('@clerk/nextjs/server', () => ({ auth: vi.fn() }));

const { GET } = await import('./route');

const TUS_ENDPOINT = 'http://localhost:1080/files/';

function grantRequest(): Request {
  return new Request('http://localhost/api/uploads/grant', { method: 'GET' });
}

beforeEach(() => {
  vi.mocked(auth).mockResolvedValue({ userId: 'user_42' } as never);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('GET /api/uploads/grant', () => {
  it('returns 401 unauthenticated when there is no signed-in user', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: null } as never);

    const res = await GET(grantRequest());
    const json = await res.json();

    expect(res.status).toBe(401);
    expect(json).toEqual({ error: 'unauthenticated' });
  });

  it('returns 200 with the ownerId and tus endpoint for a signed-in user', async () => {
    const res = await GET(grantRequest());
    const json = await res.json();

    expect(res.status).toBe(200);
    expect(json).toEqual({ ownerId: 'user_42', tusEndpoint: TUS_ENDPOINT });
  });

  it('stamps ownerId as the Clerk userId so it matches the hook contract', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: 'user_owner_contract' } as never);

    const res = await GET(grantRequest());
    const json = await res.json();

    expect(json.ownerId).toBe('user_owner_contract');
  });
});
