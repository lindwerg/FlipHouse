import { fileURLToPath } from 'node:url';
import { auth } from '@clerk/nextjs/server';
import { PGlite } from '@electric-sql/pglite';
import { drizzle } from 'drizzle-orm/pglite';
import { migrate } from 'drizzle-orm/pglite/migrator';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { BillingDatabase } from '@/features/billing/balance';
import { getBalance } from '@/features/billing/balance';
import * as schema from '@/models/Schema';

// Dev-only deposit-funding route: drives the REAL watcher pipeline (confirmations
// gate, address→userId resolve, idempotent credit by txid) against a fake chain
// source so e2e can fund a balance deterministically — no network. Tested on the
// same ephemeral PGlite harness as the billing ledger; auth + the db singleton are
// mocked. The route reads `db` from @/libs/DB at call-time, so a hoisted holder
// lets each test swap in a freshly-migrated database.
const MIGRATIONS_DIR = fileURLToPath(new URL('../../../../../../migrations', import.meta.url));

const holder = vi.hoisted(() => ({ db: null as unknown as BillingDatabase }));

vi.mock('@/libs/DB', () => ({
  get db() {
    return holder.db;
  },
}));
vi.mock('@clerk/nextjs/server', () => ({ auth: vi.fn() }));

// Import after mocks are registered.
const { POST } = await import('./route');

let client: PGlite;

function postRequest(body?: unknown): Request {
  return new Request('http://localhost/api/dev/payments/fund', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

beforeEach(async () => {
  client = new PGlite();
  holder.db = drizzle({ client, schema }) as unknown as BillingDatabase;
  await migrate(holder.db as never, { migrationsFolder: MIGRATIONS_DIR });
  vi.mocked(auth).mockResolvedValue({ userId: 'user_1' } as never);
});

afterEach(async () => {
  await client.close();
  vi.clearAllMocks();
});

describe('POST /api/dev/payments/fund', () => {
  it('returns 403 in production (dev-only route)', async () => {
    vi.stubEnv('NODE_ENV', 'production');
    try {
      const res = await POST(postRequest({ amountUsdt: 50 }));

      expect(res.status).toBe(403);
    } finally {
      vi.unstubAllEnvs();
    }
  });

  it('returns 401 when there is no signed-in user', async () => {
    vi.mocked(auth).mockResolvedValue({ userId: null } as never);

    const res = await POST(postRequest({ amountUsdt: 50 }));

    expect(res.status).toBe(401);
  });

  it('runs the watcher and credits the confirmed deposit to the balance', async () => {
    const res = await POST(postRequest({ amountUsdt: 50 }));
    const json = await res.json();

    expect(res.status).toBe(200);
    expect(json.credited).toBe(1);
    expect(await getBalance(holder.db, 'user_1')).toBe(50);
  });

  it('is idempotent per txid (re-posting the same tx does not double-credit)', async () => {
    const first = await POST(postRequest({ amountUsdt: 50, txid: 'tx_fixed' }));
    const second = await POST(postRequest({ amountUsdt: 50, txid: 'tx_fixed' }));

    expect((await first.json()).credited).toBe(1);
    expect((await second.json()).credited).toBe(0);
    expect(await getBalance(holder.db, 'user_1')).toBe(50);
  });
});
