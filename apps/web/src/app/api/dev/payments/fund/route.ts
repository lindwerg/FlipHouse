import { randomUUID } from 'node:crypto';
import { auth } from '@clerk/nextjs/server';
import * as z from 'zod';
import { toMicro } from '@/features/billing/money';
import { getPaymentProvider } from '@/features/billing/PaymentProvider';
import { db } from '@/libs/DB';
import { Env } from '@/libs/Env';
import { inMemoryCursorStore } from '@/payments/watcher/cursor';
import {
  getOrCreateDepositAddress,
  resolveUserIdByDepositAddress,
} from '@/payments/watcher/depositAddress';
import { fakeChainSource, makeTransfer } from '@/payments/watcher/fixtures';
import { runWatcherTick } from '@/payments/watcher/watcher';

// DEV/E2E-ONLY: deterministically funds the signed-in user's balance by replaying
// a CONFIRMED on-chain USDT transfer to their deposit address through the real
// watcher (confirmations gate, address→userId resolve, idempotent credit by txid)
// — no TRON network. The signup→fund→dashboard e2e POSTs here instead of waiting
// on a real testnet deposit. Hard 403 in production so the surface never ships.
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const DEFAULT_AMOUNT_USDT = 50;
const FIXTURE_BLOCK = 1000;

const bodySchema = z.object({
  amountUsdt: z.number().positive().default(DEFAULT_AMOUNT_USDT),
  // Optional idempotency key so a test can assert no double-credit; omitted in
  // normal top-ups so each call credits a fresh deposit.
  txid: z.string().min(1).optional(),
});

export async function POST(req: Request): Promise<Response> {
  if (process.env.NODE_ENV === 'production') {
    return Response.json({ error: 'not found' }, { status: 403 });
  }

  const { userId } = await auth();
  if (!userId) {
    return Response.json({ error: 'unauthenticated' }, { status: 401 });
  }

  const raw = await req.json().catch(() => ({}));
  const { amountUsdt, txid } = bodySchema.parse(raw ?? {});

  const address = await getOrCreateDepositAddress(db, getPaymentProvider(), userId);

  const confirmations = Env.TRON_CONFIRMATIONS;
  const transfer = makeTransfer({
    txid: txid ?? randomUUID(),
    blockNumber: FIXTURE_BLOCK,
    toAddress: address,
    tokenContract: Env.USDT_CONTRACT,
    amount: toMicro(amountUsdt),
  });

  // head = block + N guarantees the confirmations gate (currentBlock - block + 1 ≥ N) passes.
  const summary = await runWatcherTick(db, {
    source: fakeChainSource([transfer], FIXTURE_BLOCK + confirmations),
    cursor: inMemoryCursorStore(),
    usdtContract: Env.USDT_CONTRACT,
    confirmations,
    resolveUserId: addr => resolveUserIdByDepositAddress(db, addr),
  });

  return Response.json(summary, { status: 200 });
}
