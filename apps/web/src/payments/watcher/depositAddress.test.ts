import { fileURLToPath } from 'node:url';
import { PGlite } from '@electric-sql/pglite';
import { drizzle } from 'drizzle-orm/pglite';
import { migrate } from 'drizzle-orm/pglite/migrator';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { BillingDatabase } from '@/features/billing/balance';
import { ensureSubscription, getBalance } from '@/features/billing/balance';
import { mockPaymentProvider } from '@/features/billing/provider/mock';
import * as schema from '@/models/Schema';
import {
  getOrCreateDepositAddress,
  resolveUserIdByDepositAddress,
} from './depositAddress';

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
