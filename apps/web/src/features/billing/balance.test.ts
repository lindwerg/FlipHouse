import { fileURLToPath } from 'node:url';
import { PGlite } from '@electric-sql/pglite';
import { eq } from 'drizzle-orm';
import { drizzle } from 'drizzle-orm/pglite';
import { migrate } from 'drizzle-orm/pglite/migrator';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import * as schema from '@/models/Schema';
import type { BillingDatabase } from './balance';
import {
  credit,
  debit,
  ensureSubscription,
  getBalance,
  getSubscriptionSummary,
} from './balance';
import { paygCostUsdt } from './plans';
import { chargeMonthlySubscription } from './subscription';
import { assertCanClip } from './usageGate';

// Integration harness on ephemeral in-memory PGlite (pattern from P1.10). Each
// test gets a fresh migrated database — no shared state, no real Postgres.
const MIGRATIONS_DIR = fileURLToPath(new URL('../../../migrations', import.meta.url));

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

describe('balance ledger', () => {
  it('PAYG debit charges $0.25 per source-minute from balance', async () => {
    await ensureSubscription(db, 'user_1', { plan: 'payg', balanceUsdt: 10 });

    const cost = paygCostUsdt(4); // 4 min × $0.25 = $1.00

    expect(cost).toBe(1);

    const result = await debit(db, {
      userId: 'user_1',
      amountUsdt: cost,
      kind: 'payg',
      reason: 'clip job',
      jobId: 'job_1',
    });

    expect(result.charged).toBe(true);
    expect(result.balanceUsdt).toBe(9);
    expect(await getBalance(db, 'user_1')).toBe(9);
  });

  it('ensureSubscription defaults to the free plan with a zero balance', async () => {
    await ensureSubscription(db, 'fresh_user');

    expect(await getBalance(db, 'fresh_user')).toBe(0);
  });

  it('getBalance returns 0 for a user with no billing row', async () => {
    expect(await getBalance(db, 'unknown_user')).toBe(0);
  });

  it('debit is idempotent per job (retry does not double-charge)', async () => {
    await ensureSubscription(db, 'user_1', { plan: 'payg', balanceUsdt: 10 });

    const first = await debit(db, {
      userId: 'user_1',
      amountUsdt: 1,
      kind: 'payg',
      reason: 'clip job',
      jobId: 'job_1',
    });
    const retry = await debit(db, {
      userId: 'user_1',
      amountUsdt: 1,
      kind: 'payg',
      reason: 'clip job',
      jobId: 'job_1',
    });

    expect(first.charged).toBe(true);
    expect(retry.charged).toBe(false);
    // Charged exactly once.
    expect(await getBalance(db, 'user_1')).toBe(9);
  });
});

describe('deposit credit', () => {
  it('credits the balance and is idempotent per txid', async () => {
    const first = await credit(db, {
      userId: 'user_1',
      amountUsdt: 5,
      txid: 'tx_1',
      reason: 'usdt-trc20 deposit',
    });

    expect(first.credited).toBe(true);
    expect(first.balanceUsdt).toBe(5);

    // Same on-chain txid → already credited, no second credit.
    const retry = await credit(db, {
      userId: 'user_1',
      amountUsdt: 5,
      txid: 'tx_1',
      reason: 'usdt-trc20 deposit',
    });

    expect(retry.credited).toBe(false);
    // Credited exactly once.
    expect(await getBalance(db, 'user_1')).toBe(5);
  });

  it('a deposit (NULL jobId) does not collide with a PAYG debit', async () => {
    await ensureSubscription(db, 'user_1', { plan: 'payg', balanceUsdt: 0 });

    await credit(db, {
      userId: 'user_1',
      amountUsdt: 10,
      txid: 'dep_1',
      reason: 'usdt-trc20 deposit',
    });
    const charged = await debit(db, {
      userId: 'user_1',
      amountUsdt: 1,
      kind: 'payg',
      reason: 'clip job',
      jobId: 'job_1',
    });

    expect(charged.charged).toBe(true);
    expect(await getBalance(db, 'user_1')).toBe(9);
  });
});

describe('subscription summary', () => {
  it('defaults to the free plan with a zero balance for a user with no billing row', async () => {
    const summary = await getSubscriptionSummary(db, 'ghost');

    expect(summary).toEqual({
      plan: 'free',
      balanceUsdt: 0,
      subscriptionStatus: null,
    });
  });

  it('reports the persisted plan, balance and status', async () => {
    await ensureSubscription(db, 'user_1', { plan: 'active', balanceUsdt: 30 });
    await chargeMonthlySubscription(db, 'user_1'); // active charge $24 → $6, status active

    const summary = await getSubscriptionSummary(db, 'user_1');

    expect(summary.plan).toBe('active');
    expect(summary.balanceUsdt).toBe(6);
    expect(summary.subscriptionStatus).toBe('active');
  });
});

describe('usage gate', () => {
  it('clipping is blocked when balance < cost (PAYG) or minute cap exceeded (subscription)', async () => {
    // PAYG with insufficient balance → blocked.
    await ensureSubscription(db, 'payg_user', { plan: 'payg', balanceUsdt: 0.5 });
    await expect(assertCanClip(db, 'payg_user', 4)).rejects.toThrow(/insufficient balance/);

    // Subscription over the monthly minute cap → blocked.
    await ensureSubscription(db, 'sub_user', {
      plan: 'start',
      minutesUsedThisPeriod: 149,
    });
    await expect(assertCanClip(db, 'sub_user', 5)).rejects.toThrow(/minute cap exceeded/);

    // Enough balance / under cap → allowed (does not throw).
    await ensureSubscription(db, 'ok_user', { plan: 'payg', balanceUsdt: 10 });
    await expect(assertCanClip(db, 'ok_user', 4)).resolves.toBeUndefined();
  });

  it('defaults a user with no billing row to the free plan cap', async () => {
    // No subscription row → free plan (30 min cap).
    await expect(assertCanClip(db, 'ghost', 5)).resolves.toBeUndefined();
    await expect(assertCanClip(db, 'ghost', 40)).rejects.toThrow(/minute cap exceeded/);
  });
});

describe('subscription monthly charge', () => {
  it('subscription monthly charge debits balance; insufficient balance → downgrade to payg/free', async () => {
    // Enough balance: active ($24) charged from $30 → $6, status active.
    await ensureSubscription(db, 'rich_user', { plan: 'active', balanceUsdt: 30 });
    const charged = await chargeMonthlySubscription(db, 'rich_user');

    expect(charged.subscriptionStatus).toBe('active');
    expect(await getBalance(db, 'rich_user')).toBe(6);

    // Insufficient balance: active ($24) but only $10 → downgrade to free, past_due.
    await ensureSubscription(db, 'poor_user', { plan: 'active', balanceUsdt: 10 });
    const downgraded = await chargeMonthlySubscription(db, 'poor_user');

    expect(downgraded.plan).toBe('free');
    expect(downgraded.subscriptionStatus).toBe('past_due');
    // Balance untouched on downgrade.
    expect(await getBalance(db, 'poor_user')).toBe(10);
  });

  it('throws when charging a user that has no billing row', async () => {
    await expect(chargeMonthlySubscription(db, 'nobody')).rejects.toThrow(
      /no subscription/,
    );
  });

  it('renewal arithmetic stays EXACT on a fractional balance (BILL-4: integer micros, no float drift)', async () => {
    // A fractional prepaid balance: active ($24) charged from $30.123456 must land
    // on EXACTLY $6.123456 — a float path would drift in the last micro digit.
    await ensureSubscription(db, 'frac_user', { plan: 'active', balanceUsdt: 30.123456 });
    const charged = await chargeMonthlySubscription(db, 'frac_user');

    expect(charged.subscriptionStatus).toBe('active');
    expect(await getBalance(db, 'frac_user')).toBeCloseTo(6.123456, 6);
    // The persisted numeric(20,6) string is exact (the load-bearing invariant).
    const rows = await db
      .select({ balanceUsdt: schema.subscriptionSchema.balanceUsdt })
      .from(schema.subscriptionSchema)
      .where(eq(schema.subscriptionSchema.userId, 'frac_user'));
    expect(rows[0]?.balanceUsdt).toBe('6.123456');
    // The subscription debit ledger row carries the exact negative price.
    const entries = await db
      .select({ amountUsdt: schema.balanceEntrySchema.amountUsdt })
      .from(schema.balanceEntrySchema)
      .where(eq(schema.balanceEntrySchema.userId, 'frac_user'));
    expect(entries[0]?.amountUsdt).toBe('-24.000000');
  });
});
