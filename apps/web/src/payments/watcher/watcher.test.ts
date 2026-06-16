import { fileURLToPath } from 'node:url';
import { PGlite } from '@electric-sql/pglite';
import { drizzle } from 'drizzle-orm/pglite';
import { migrate } from 'drizzle-orm/pglite/migrator';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { BillingDatabase } from '@/features/billing/balance';
import { ensureSubscription, getBalance } from '@/features/billing/balance';
import { mockPaymentProvider } from '@/features/billing/provider/mock';
import { chargeMonthlySubscription } from '@/features/billing/subscription';
import * as schema from '@/models/Schema';
import { inMemoryCursorStore } from './cursor';
import {
  getOrCreateDepositAddress,
  resolveUserIdByDepositAddress,
} from './depositAddress';
import { fakeChainSource, makeTransfer } from './fixtures';
import { processTransfers, runWatcherTick } from './watcher';

// Integration harness on ephemeral in-memory PGlite (pattern from balance.test.ts).
// Each test gets a fresh migrated database — no shared state, no real Postgres,
// no TRON network: the chain source is a fixture and the address map is real DB.
const MIGRATIONS_DIR = fileURLToPath(
  new URL('../../../migrations', import.meta.url),
);

// USDT TRC-20 contract (mainnet); any other string models a non-USDT token.
const USDT = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t';
const OTHER_TOKEN = 'TXYZotherTokenContractAddr0000000000';
const CONFIRMATIONS = 19;

let client: PGlite;
let db: BillingDatabase;

// Closes over the current `db` so the watcher reverse-maps addresses via the DB.
const resolveUserId = (toAddress: string): Promise<string | null> =>
  resolveUserIdByDepositAddress(db, toAddress);

beforeEach(async () => {
  client = new PGlite();
  db = drizzle({ client, schema }) as unknown as BillingDatabase;
  await migrate(db as never, { migrationsFolder: MIGRATIONS_DIR });
});

afterEach(async () => {
  await client.close();
});

describe('TRON deposit watcher', () => {
  it('credits balanceUsdt when a confirmed USDT TRC-20 transfer to a user deposit address is seen', async () => {
    const address = await getOrCreateDepositAddress(
      db,
      mockPaymentProvider,
      'user_1',
    );

    // confirmations = 100 - 80 + 1 = 21 ≥ 19 → final, credited.
    const event = makeTransfer({
      txid: 'tx_1',
      blockNumber: 80,
      toAddress: address,
      tokenContract: USDT,
      amount: BigInt(5_000_000), // 5 USDT (6 on-chain decimals)
    });

    const summary = await processTransfers(db, {
      events: [event],
      currentBlock: 100,
      usdtContract: USDT,
      confirmations: CONFIRMATIONS,
      resolveUserId,
    });

    expect(summary.credited).toBe(1);
    expect(await getBalance(db, 'user_1')).toBe(5);
  });

  it('does NOT credit on < N confirmations (pending) or wrong token contract', async () => {
    const address = await getOrCreateDepositAddress(
      db,
      mockPaymentProvider,
      'user_1',
    );

    // confirmations = 100 - 90 + 1 = 11 < 19 → pending, not credited.
    const pending = makeTransfer({
      txid: 'tx_pending',
      blockNumber: 90,
      toAddress: address,
      tokenContract: USDT,
      amount: BigInt(5_000_000),
    });
    // Final by confirmations but the wrong token contract → not credited.
    const wrongToken = makeTransfer({
      txid: 'tx_wrong_token',
      blockNumber: 50,
      toAddress: address,
      tokenContract: OTHER_TOKEN,
      amount: BigInt(5_000_000),
    });

    const summary = await processTransfers(db, {
      events: [pending, wrongToken],
      currentBlock: 100,
      usdtContract: USDT,
      confirmations: CONFIRMATIONS,
      resolveUserId,
    });

    expect(summary.credited).toBe(0);
    expect(summary.skippedPending).toBe(1);
    expect(summary.skippedWrongToken).toBe(1);
    expect(await getBalance(db, 'user_1')).toBe(0);
  });

  it('duplicate txid is idempotent (credited once)', async () => {
    const address = await getOrCreateDepositAddress(
      db,
      mockPaymentProvider,
      'user_1',
    );
    const event = makeTransfer({
      txid: 'tx_dup',
      blockNumber: 80,
      toAddress: address,
      tokenContract: USDT,
      amount: BigInt(4_000_000),
    });
    const args = {
      events: [event],
      currentBlock: 100,
      usdtContract: USDT,
      confirmations: CONFIRMATIONS,
      resolveUserId,
    };

    const first = await processTransfers(db, args);
    const second = await processTransfers(db, args);

    expect(first.credited).toBe(1);
    expect(second.credited).toBe(0);
    expect(second.skippedDuplicate).toBe(1);
    // Charged exactly once.
    expect(await getBalance(db, 'user_1')).toBe(4);
  });

  it('credits the correct userId by mapping deposit address → user', async () => {
    const addrA = await getOrCreateDepositAddress(
      db,
      mockPaymentProvider,
      'user_a',
    );
    const addrB = await getOrCreateDepositAddress(
      db,
      mockPaymentProvider,
      'user_b',
    );
    expect(addrA).not.toBe(addrB);

    const toB = makeTransfer({
      txid: 'tx_to_b',
      blockNumber: 80,
      toAddress: addrB,
      tokenContract: USDT,
      amount: BigInt(3_000_000),
    });
    // A transfer to an address that maps to no user is skipped, not credited.
    const stray = makeTransfer({
      txid: 'tx_stray',
      blockNumber: 80,
      toAddress: 'TstrayUnmappedAddress00000000000000',
      tokenContract: USDT,
      amount: BigInt(9_000_000),
    });

    const summary = await processTransfers(db, {
      events: [toB, stray],
      currentBlock: 100,
      usdtContract: USDT,
      confirmations: CONFIRMATIONS,
      resolveUserId,
    });

    expect(summary.credited).toBe(1);
    expect(summary.skippedUnknownAddress).toBe(1);
    expect(await getBalance(db, 'user_b')).toBe(3);
    expect(await getBalance(db, 'user_a')).toBe(0);
  });

  it('underpaid/overpaid amount credits the actual on-chain amount, not the invoice', async () => {
    const address = await getOrCreateDepositAddress(
      db,
      mockPaymentProvider,
      'user_1',
    );

    // Invoice was notionally 10 USDT, but the chain shows 7 → credit 7.
    const under = makeTransfer({
      txid: 'tx_under',
      blockNumber: 80,
      toAddress: address,
      tokenContract: USDT,
      amount: BigInt(7_000_000),
    });
    await processTransfers(db, {
      events: [under],
      currentBlock: 100,
      usdtContract: USDT,
      confirmations: CONFIRMATIONS,
      resolveUserId,
    });
    expect(await getBalance(db, 'user_1')).toBe(7);

    // A later overpayment of 13 → credit the actual 13 on top.
    const over = makeTransfer({
      txid: 'tx_over',
      blockNumber: 85,
      toAddress: address,
      tokenContract: USDT,
      amount: BigInt(13_000_000),
    });
    await processTransfers(db, {
      events: [over],
      currentBlock: 110,
      usdtContract: USDT,
      confirmations: CONFIRMATIONS,
      resolveUserId,
    });
    expect(await getBalance(db, 'user_1')).toBe(20);
  });

  it('subscription renewal: monthly debit from balance flips status active/past_due', async () => {
    // Enough balance: active ($24) charged from $30 → $6, status active.
    await ensureSubscription(db, 'rich_user', { plan: 'active', balanceUsdt: 30 });
    const active = await chargeMonthlySubscription(db, 'rich_user');
    expect(active.subscriptionStatus).toBe('active');
    expect(await getBalance(db, 'rich_user')).toBe(6);

    // Insufficient balance: active ($24) but only $10 → downgrade free, past_due.
    await ensureSubscription(db, 'poor_user', { plan: 'active', balanceUsdt: 10 });
    const pastDue = await chargeMonthlySubscription(db, 'poor_user');
    expect(pastDue.plan).toBe('free');
    expect(pastDue.subscriptionStatus).toBe('past_due');
  });
});

describe('runWatcherTick (cursor-driven)', () => {
  it('scans from the cursor, credits final transfers, skips pending, and advances the cursor', async () => {
    const address = await getOrCreateDepositAddress(
      db,
      mockPaymentProvider,
      'user_1',
    );
    const final = makeTransfer({
      txid: 'f1',
      blockNumber: 50,
      toAddress: address,
      tokenContract: USDT,
      amount: BigInt(6_000_000),
    });
    const pending = makeTransfer({
      txid: 'p1',
      blockNumber: 95,
      toAddress: address,
      tokenContract: USDT,
      amount: BigInt(9_000_000),
    });
    const source = fakeChainSource([final, pending], 100);
    const cursor = inMemoryCursorStore();

    const summary = await runWatcherTick(db, {
      source,
      cursor,
      usdtContract: USDT,
      confirmations: CONFIRMATIONS,
      resolveUserId,
    });

    expect(summary.credited).toBe(1);
    expect(summary.skippedPending).toBe(1);
    expect(await getBalance(db, 'user_1')).toBe(6);
    // Advanced to currentBlock - confirmations = 81; the pending block 95 is
    // re-scanned next tick (idempotent by txid).
    expect(await cursor.getLastBlock()).toBe(81);
  });

  it('does nothing when the cursor is already at the chain head', async () => {
    const source = fakeChainSource([], 100);
    const cursor = inMemoryCursorStore(100);

    const summary = await runWatcherTick(db, {
      source,
      cursor,
      usdtContract: USDT,
      confirmations: CONFIRMATIONS,
      resolveUserId,
    });

    expect(summary.credited).toBe(0);
    expect(await cursor.getLastBlock()).toBe(100);
  });
});
