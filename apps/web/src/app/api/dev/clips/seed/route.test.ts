import { fileURLToPath } from 'node:url';
import { auth } from '@clerk/nextjs/server';
import { PGlite } from '@electric-sql/pglite';
import { listClipsForOwner, listUploadsForOwner } from '@fliphouse/db';
import type { Db } from '@fliphouse/db';
import { drizzle } from 'drizzle-orm/pglite';
import { migrate } from 'drizzle-orm/pglite/migrator';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as schema from '@/models/Schema';

// Dev-only clips-seed route: writes a finished upload + its ranked clips for the
// signed-in creator so the upload-to-clips e2e can assert the dashboard without a
// live tusd + GPU pipeline. Tested on the same ephemeral PGlite harness as the
// fund route — auth + the db singleton are mocked; the route reads `db` from
// @/libs/DB at call-time so a hoisted holder swaps in a freshly-migrated db.
const MIGRATIONS_DIR = fileURLToPath(new URL('../../../../../../migrations', import.meta.url));

const holder = vi.hoisted(() => ({ db: null as unknown as Db }));

vi.mock('@/libs/DB', () => ({
  get db() {
    return holder.db;
  },
}));
vi.mock('@clerk/nextjs/server', () => ({ auth: vi.fn() }));

const { POST } = await import('./route');

let client: PGlite;

function postRequest(body?: unknown): Request {
  return new Request('http://localhost/api/dev/clips/seed', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

beforeEach(async () => {
  client = new PGlite();
  holder.db = drizzle({ client, schema }) as unknown as Db;
  await migrate(holder.db as never, { migrationsFolder: MIGRATIONS_DIR });
  vi.mocked(auth).mockResolvedValue({ userId: 'user_1' } as never);
});

afterEach(async () => {
  await client.close();
  vi.clearAllMocks();
});

describe('POST /api/dev/clips/seed', () => {
  it('returns 403 in production (dev-only route)', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    try {
      expect((await POST(postRequest({}))).status).toBe(403);
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it('returns 401 when there is no signed-in user', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: null } as never);

    expect((await POST(postRequest({}))).status).toBe(401);
  });

  it('seeds a finished upload with ranked clips ordered best-first', async () => {
    const res = await POST(postRequest({ seed: 'ranked', clipCount: 3 }));
    const json = await res.json();

    expect(res.status).toBe(200);
    expect(json.claimed).toBe(true);
    expect(json.clipCount).toBe(3);

    const owned = await listClipsForOwner(holder.db, json.contentHash, 'user_1');
    expect(owned?.status).toBe('done');
    expect(owned?.clips.map(c => c.rank)).toEqual([0, 1, 2]);
    // rank asc must coincide with score desc — a correctly-ranked batch.
    const scores = owned!.clips.map(c => Number(c.score));
    expect(scores).toEqual([...scores].sort((a, b) => b - a));
    // 9:16 vertical dimensions for every clip.
    for (const clip of owned!.clips) {
      expect(clip.width).toBe(1080);
      expect(clip.height).toBe(1920);
    }
  });

  it('defaults seed + clipCount when the body is absent', async () => {
    // No body → req.json() rejects → the route falls back to {} and the schema
    // defaults (seed "e2e", 3 clips) apply.
    const res = await POST(postRequest());
    const json = await res.json();

    expect(res.status).toBe(200);
    expect(json.clipCount).toBe(3);

    const owned = await listClipsForOwner(holder.db, json.contentHash, 'user_1');
    expect(owned?.clips).toHaveLength(3);
  });

  it('is idempotent per (user, seed): re-seeding reuses the same upload', async () => {
    const first = await POST(postRequest({ seed: 'dup' }));
    const second = await POST(postRequest({ seed: 'dup' }));

    const firstJson = await first.json();
    const secondJson = await second.json();

    expect(firstJson.claimed).toBe(true);
    expect(secondJson.claimed).toBe(false);
    expect(secondJson.contentHash).toBe(firstJson.contentHash);

    // One upload row, not two — the content-hash claim deduped the re-seed.
    const uploads = await listUploadsForOwner(holder.db, 'user_1');
    expect(uploads).toHaveLength(1);
  });
});
