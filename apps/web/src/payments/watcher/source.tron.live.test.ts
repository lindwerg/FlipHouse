import { fileURLToPath } from 'node:url';
import { PGlite } from '@electric-sql/pglite';
import { eq } from 'drizzle-orm';
import { drizzle } from 'drizzle-orm/pglite';
import { migrate } from 'drizzle-orm/pglite/migrator';
import { beforeAll, describe, expect, it } from 'vitest';
import type { BillingDatabase } from '@/features/billing/balance';
import { ensureSubscription, getBalance } from '@/features/billing/balance';
import * as schema from '@/models/Schema';
import { subscriptionSchema } from '@/models/Schema';
import { inMemoryCursorStore } from './cursor';
import { resolveUserIdByDepositAddress } from './depositAddress';
import { makeTronChainSource } from './source.tron';
import { runWatcherTick } from './watcher';

// Live Nile-testnet harness for CHECKPOINT F. Skipped in CI and normal runs —
// only runs with TRON_LIVE=1 and a TRONGRID_API_KEY, hitting the real chain. It
// proves the full deposit path (real chain → poller → confirmations → balance
// credit, idempotent by txid) end-to-end against live data, using an existing
// on-chain USDT transfer instead of one we freshly broadcast.
//
//   TRON_LIVE=1 TRONGRID_API_KEY=… pnpm --filter web exec vitest run \
//     src/payments/watcher/source.tron.live.test.ts
//
// TRON_LIVE_ADDRESS overrides the watched address (default: a known Nile address
// with confirmed USDT TRC-20 receipts). The founder's own derived deposit address
// can be passed here once funded.

const LIVE = process.env.TRON_LIVE === '1';
const RPC = process.env.TRON_RPC_URL ?? 'https://nile.trongrid.io';
const USDT = process.env.USDT_CONTRACT ?? 'TXYZopYRdj2D9XRtbG411XZZ3kM5VkAeBf';
const API_KEY = process.env.TRONGRID_API_KEY;
const WATCHED =
  process.env.TRON_LIVE_ADDRESS ?? 'TE8vjSBY5x45MWKUsVv8UEyW7iCRA3mF7p';
const CONFIRMATIONS = Number(process.env.TRON_CONFIRMATIONS ?? 19);

const MIGRATIONS_DIR = fileURLToPath(
  new URL('../../../migrations', import.meta.url),
);

(LIVE ? describe : describe.skip)('tron source against live Nile testnet', () => {
  let client: PGlite;
  let db: BillingDatabase;

  beforeAll(async () => {
    client = new PGlite();
    db = drizzle({ client, schema }) as unknown as BillingDatabase;
    await migrate(db as never, { migrationsFolder: MIGRATIONS_DIR });
  });

  function source() {
    return makeTronChainSource({
      fetch: globalThis.fetch as never,
      rpcUrl: RPC,
      usdtContract: USDT,
      apiKey: API_KEY,
      listAddresses: () => Promise.resolve([WATCHED]),
    });
  }

  it('reads a real block height from the node', async () => {
    const block = await source().getCurrentBlock();
    expect(block).toBeGreaterThan(0);
  });

  it('parses real USDT transfers to the watched address', async () => {
    const head = await source().getCurrentBlock();
    const events = await source().getTransferEvents({ fromBlock: 1, toBlock: head });
    // The default address has confirmed receipts; every parsed event must be a
    // positive USDT transfer to our address with a resolved block height.
    for (const e of events) {
      expect(e.tokenContract).toBe(USDT);
      expect(e.toAddress).toBe(WATCHED);
      expect(e.amount > BigInt(0)).toBe(true);
      expect(e.blockNumber).toBeGreaterThan(0);
    }
    expect(events.length).toBeGreaterThan(0);
  });

  it('credits a confirmed on-chain deposit to the mapped user, idempotently', async () => {
    const userId = 'live_test_user';
    await ensureSubscription(db, userId, { plan: 'payg' });
    await db
      .update(subscriptionSchema)
      .set({ depositAddress: WATCHED, depositIndex: 0 })
      .where(eq(subscriptionSchema.userId, userId));

    const cursor = inMemoryCursorStore();
    const resolveUserId = (a: string) => resolveUserIdByDepositAddress(db, a);
    const args = {
      source: source(),
      cursor,
      usdtContract: USDT,
      confirmations: CONFIRMATIONS,
      resolveUserId,
    };

    const first = await runWatcherTick(db, args);
    const balanceAfter = await getBalance(db, userId);
    expect(first.credited).toBeGreaterThan(0);
    expect(balanceAfter).toBeGreaterThan(0);

    // A second tick re-scans the same blocks (pending re-scan) but credit is
    // idempotent by txid → no double credit.
    cursor.setLastBlock(0);
    const second = await runWatcherTick(db, { ...args, cursor });
    expect(second.credited).toBe(0);
    expect(await getBalance(db, userId)).toBe(balanceAfter);
  });
});
