import { fileURLToPath } from 'node:url';
import { PGlite } from '@electric-sql/pglite';
import { eq } from 'drizzle-orm';
import { drizzle } from 'drizzle-orm/pglite';
import { migrate } from 'drizzle-orm/pglite/migrator';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { BillingDatabase } from '@/features/billing/balance';
import { ensureSubscription, getBalance } from '@/features/billing/balance';
import { mockPaymentProvider } from '@/features/billing/provider/mock';
import { tronPaymentProvider } from '@/features/billing/provider/tron';
import { subscriptionSchema } from '@/models/Schema';
import * as schema from '@/models/Schema';
import {
  getOrCreateDepositAddress,
  resolveUserIdByDepositAddress,
} from './depositAddress';

async function readDepositIndex(
  db: BillingDatabase,
  userId: string,
): Promise<number | null> {
  const rows = await db
    .select({ depositIndex: subscriptionSchema.depositIndex })
    .from(subscriptionSchema)
    .where(eq(subscriptionSchema.userId, userId));
  return rows[0]?.depositIndex ?? null;
}

const MIGRATIONS_DIR = fileURLToPath(
  new URL('../../../migrations', import.meta.url),
);

let client: PGlite;
let db: BillingDatabase;

beforeEach(async () => {
  client = new PGlite();
  db = drizzle({ client, schema }) as unknown as BillingDatabase;
  await migrate(db as never, { migrationsFolder: MIGRATIONS_DIR });
});

afterEach(async () => {
  await client.close();
});

describe('deposit address persistence', () => {
  it('derives, persists, and resolves a deposit address for a user', async () => {
    const address = await getOrCreateDepositAddress(
      db,
      mockPaymentProvider,
      'user_1',
    );

    // TRC-20 shape: base58, starts with 'T', 34 chars.
    expect(address).toMatch(/^T[1-9A-HJ-NP-Za-km-z]{33}$/);
    expect(await resolveUserIdByDepositAddress(db, address)).toBe('user_1');
  });

  it('is idempotent: a second call returns the same persisted address', async () => {
    const first = await getOrCreateDepositAddress(
      db,
      mockPaymentProvider,
      'user_1',
    );
    const again = await getOrCreateDepositAddress(
      db,
      mockPaymentProvider,
      'user_1',
    );

    expect(again).toBe(first);
  });

  it('returns null for an unknown deposit address', async () => {
    expect(
      await resolveUserIdByDepositAddress(db, 'TunknownAddr0000000000000000000000'),
    ).toBeNull();
  });

  it('allocates a stable sequential deposit index per user (no address collisions, idempotent)', async () => {
    // Real HD provider: sequential indices map to the published BIP44 vector, so
    // the wallet stays recoverable by scanning m/44'/195'/0'/0/0..N.
    const addr1 = await getOrCreateDepositAddress(db, tronPaymentProvider, 'user_1');
    const addr2 = await getOrCreateDepositAddress(db, tronPaymentProvider, 'user_2');

    // First user → index 0, second user → index 1 (sequential, no gaps).
    expect(await readDepositIndex(db, 'user_1')).toBe(0);
    expect(await readDepositIndex(db, 'user_2')).toBe(1);
    expect(addr1).toBe('TUEZSdKsoDHQMeZwihtdoBiN46zxhGWYdH');
    expect(addr2).toBe('TSeJkUh4Qv67VNFwY8LaAxERygNdy6NQZK');
    // Distinct addresses → no derivation collision.
    expect(addr1).not.toBe(addr2);

    // Repeating a user is idempotent: same index, same address, no new allocation.
    const addr1Again = await getOrCreateDepositAddress(
      db,
      tronPaymentProvider,
      'user_1',
    );
    expect(addr1Again).toBe(addr1);
    expect(await readDepositIndex(db, 'user_1')).toBe(0);
    expect(await resolveUserIdByDepositAddress(db, addr1)).toBe('user_1');
  });

  it('persists onto an existing subscription row without touching its balance', async () => {
    await ensureSubscription(db, 'user_1', { plan: 'payg', balanceUsdt: 5 });

    const address = await getOrCreateDepositAddress(
      db,
      mockPaymentProvider,
      'user_1',
    );

    expect(await resolveUserIdByDepositAddress(db, address)).toBe('user_1');
    expect(await getBalance(db, 'user_1')).toBe(5);
  });
});
