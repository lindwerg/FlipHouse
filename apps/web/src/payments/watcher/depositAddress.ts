import { and, eq, isNull, sql } from 'drizzle-orm';
import type { BillingDatabase } from '@/features/billing/balance';
import { ensureSubscription } from '@/features/billing/balance';
import type { PaymentProvider } from '@/features/billing/PaymentProvider';
import { subscriptionSchema } from '@/models/Schema';

// Persisted deposit address ↔ user mapping. The watcher reverse-maps an on-chain
// transfer's recipient to a userId via subscription.deposit_address, so the
// address must be stored when first derived (the creator dashboard does this).

/**
 * Returns the user's persisted TRC-20 deposit address, deriving and storing it on
 * first call. The HD index is allocated sequentially (max+1) so the wallet stays
 * recoverable by scanning m/44'/195'/0'/0/0..N; the provider is a pure deriver
 * that turns (userId, index) into an address. Idempotent: the allocation happens
 * inside a transaction and the UPDATE only fills a NULL address, so a repeated
 * call returns the same persisted value. The subscription_deposit_index_uq unique
 * constraint is the collision backstop for concurrent allocation.
 */
export async function getOrCreateDepositAddress(
  db: BillingDatabase,
  provider: PaymentProvider,
  userId: string,
): Promise<string> {
  const existing = await db
    .select({ depositAddress: subscriptionSchema.depositAddress })
    .from(subscriptionSchema)
    .where(eq(subscriptionSchema.userId, userId));

  const current = existing[0]?.depositAddress;
  if (current) {
    return current;
  }

  await ensureSubscription(db, userId);

  return db.transaction(async (tx) => {
    // Re-check inside the transaction: a concurrent caller may have just filled it.
    const row = await tx
      .select({ depositAddress: subscriptionSchema.depositAddress })
      .from(subscriptionSchema)
      .where(eq(subscriptionSchema.userId, userId));
    const persisted = row[0]?.depositAddress;
    if (persisted) {
      return persisted;
    }

    // Next sequential index = max(existing non-null indices) + 1, starting at 0.
    const maxRow = await tx
      .select({
        max: sql<number>`coalesce(max(${subscriptionSchema.depositIndex}), -1)`,
      })
      .from(subscriptionSchema);
    const nextIndex = Number(maxRow[0]?.max ?? -1) + 1;

    const address = await provider.getDepositAddress(userId, nextIndex);

    await tx
      .update(subscriptionSchema)
      .set({ depositAddress: address, depositIndex: nextIndex })
      .where(
        and(
          eq(subscriptionSchema.userId, userId),
          isNull(subscriptionSchema.depositAddress),
        ),
      );

    return address;
  });
}

/** Resolves a deposit address to its owning userId (null if unknown). */
export async function resolveUserIdByDepositAddress(
  db: BillingDatabase,
  address: string,
): Promise<string | null> {
  const rows = await db
    .select({ userId: subscriptionSchema.userId })
    .from(subscriptionSchema)
    .where(eq(subscriptionSchema.depositAddress, address))
    .limit(1);

  return rows[0]?.userId ?? null;
}
