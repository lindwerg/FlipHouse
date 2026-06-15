import type { NodePgDatabase } from 'drizzle-orm/node-postgres';
import { eq, sql } from 'drizzle-orm';
import * as schema from '@/models/Schema';
import { balanceEntrySchema, subscriptionSchema } from '@/models/Schema';
import type { PlanId } from './plans';
import { parseUsdt, usdtToNumericString } from './money';

// Off-chain prepaid-balance ledger over Drizzle. The drizzle instance is passed in
// so production uses the singleton (@/libs/DB) while tests use an in-memory PGlite
// database — no network at import time.
export type BillingDatabase = NodePgDatabase<typeof schema>;

type BalanceEntryKind = 'deposit' | 'payg' | 'subscription';

type SubscriptionInit = {
  plan?: PlanId;
  balanceUsdt?: number;
  minutesUsedThisPeriod?: number;
};

/**
 * Ensures a billing row exists for the user. Idempotent: an existing row is left
 * untouched. `init` seeds initial values (used to set up balances/plans).
 */
export async function ensureSubscription(
  db: BillingDatabase,
  userId: string,
  init: SubscriptionInit = {},
): Promise<void> {
  await db
    .insert(subscriptionSchema)
    .values({
      userId,
      plan: init.plan ?? 'free',
      balanceUsdt: usdtToNumericString(init.balanceUsdt ?? 0),
      minutesUsedThisPeriod: init.minutesUsedThisPeriod ?? 0,
    })
    .onConflictDoNothing();
}

/** Reads the user's current prepaid USDT balance (0 if no row yet). */
export async function getBalance(
  db: BillingDatabase,
  userId: string,
): Promise<number> {
  const rows = await db
    .select({ balanceUsdt: subscriptionSchema.balanceUsdt })
    .from(subscriptionSchema)
    .where(eq(subscriptionSchema.userId, userId));

  const row = rows[0];
  return row ? parseUsdt(row.balanceUsdt) : 0;
}

type DebitParams = {
  userId: string;
  amountUsdt: number;
  kind: BalanceEntryKind;
  reason: string;
  /** Required: idempotency key. A retried debit with the same jobId is a no-op. */
  jobId: string;
};

/**
 * Debits the user's balance and records a ledger entry. Idempotent per
 * (userId, jobId): a retried job inserts no second entry and does not re-charge.
 */
export async function debit(
  db: BillingDatabase,
  params: DebitParams,
): Promise<{ charged: boolean; balanceUsdt: number }> {
  const { userId, amountUsdt, kind, reason, jobId } = params;

  return db.transaction(async (tx) => {
    await tx
      .insert(subscriptionSchema)
      .values({ userId })
      .onConflictDoNothing();

    const inserted = await tx
      .insert(balanceEntrySchema)
      .values({
        userId,
        kind,
        amountUsdt: usdtToNumericString(-amountUsdt),
        reason,
        jobId,
      })
      .onConflictDoNothing()
      .returning({ id: balanceEntrySchema.id });

    // Duplicate (userId, jobId) → already charged, leave balance as-is.
    if (inserted.length === 0) {
      const rows = await tx
        .select({ balanceUsdt: subscriptionSchema.balanceUsdt })
        .from(subscriptionSchema)
        .where(eq(subscriptionSchema.userId, userId));
      return { charged: false, balanceUsdt: parseUsdt(rows[0]!.balanceUsdt) };
    }

    // Atomic decrement (balance = balance - amount) avoids lost updates when two
    // distinct jobs for the same user debit concurrently.
    const updated = await tx
      .update(subscriptionSchema)
      .set({
        balanceUsdt: sql`${subscriptionSchema.balanceUsdt} - ${usdtToNumericString(amountUsdt)}::numeric`,
      })
      .where(eq(subscriptionSchema.userId, userId))
      .returning({ balanceUsdt: subscriptionSchema.balanceUsdt });

    return { charged: true, balanceUsdt: parseUsdt(updated[0]!.balanceUsdt) };
  });
}
