import { and, eq, isNull } from 'drizzle-orm';
import type { BillingDatabase } from '@/features/billing/balance';
import { ensureSubscription } from '@/features/billing/balance';
import type { PaymentProvider } from '@/features/billing/PaymentProvider';
import { subscriptionSchema } from '@/models/Schema';

// Persisted deposit address ↔ user mapping. The watcher reverse-maps an on-chain
// transfer's recipient to a userId via subscription.deposit_address, so the
// address must be stored when first derived (the creator dashboard does this).

/**
 * Returns the user's persisted TRC-20 deposit address, deriving and storing it
 * on first call. Idempotent: derivation is deterministic and the UPDATE only
 * fills a NULL address, so concurrent callers converge on the same value.
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

  const address = await provider.getDepositAddress(userId);
  await ensureSubscription(db, userId);
  await db
    .update(subscriptionSchema)
    .set({ depositAddress: address })
    .where(
      and(
        eq(subscriptionSchema.userId, userId),
        isNull(subscriptionSchema.depositAddress),
      ),
    );

  return address;
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
