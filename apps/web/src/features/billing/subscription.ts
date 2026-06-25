import { eq } from 'drizzle-orm';
import { balanceEntrySchema, subscriptionSchema } from '@/models/Schema';
import type { BillingDatabase } from './balance';
import { microsToNumericString, parseUsdtMicros, toMicro } from './money';
import { getPlan } from './plans';

// Monthly subscription renewal. Crypto has no stored card / auto-charge, so a
// renewal debits the prepaid balance. If the balance can't cover the plan price,
// we downgrade to free + past_due rather than letting the balance go negative.

export async function chargeMonthlySubscription(
  db: BillingDatabase,
  userId: string,
): Promise<{ plan: string; subscriptionStatus: 'active' | 'past_due' }> {
  return db.transaction(async (tx) => {
    const rows = await tx
      .select({
        plan: subscriptionSchema.plan,
        balanceUsdt: subscriptionSchema.balanceUsdt,
      })
      .from(subscriptionSchema)
      .where(eq(subscriptionSchema.userId, userId));

    const row = rows[0];
    if (!row) {
      throw new Error(`no subscription for user ${userId}`);
    }

    // All money stays in integer micro-USDT (BigInt) — no float touches the
    // balance/price comparison or the new balance (BILL-4).
    const priceMicro = toMicro(getPlan(row.plan).priceUsdt);
    const balanceMicro = parseUsdtMicros(row.balanceUsdt);

    if (balanceMicro < priceMicro) {
      await tx
        .update(subscriptionSchema)
        .set({ plan: 'free', subscriptionStatus: 'past_due' })
        .where(eq(subscriptionSchema.userId, userId));
      return { plan: 'free', subscriptionStatus: 'past_due' };
    }

    const newMicro = balanceMicro - priceMicro;
    await tx.insert(balanceEntrySchema).values({
      userId,
      kind: 'subscription',
      amountUsdt: microsToNumericString(-priceMicro),
      reason: `monthly ${row.plan} subscription`,
    });
    await tx
      .update(subscriptionSchema)
      .set({
        balanceUsdt: microsToNumericString(newMicro),
        subscriptionStatus: 'active',
        minutesUsedThisPeriod: 0,
      })
      .where(eq(subscriptionSchema.userId, userId));

    return { plan: row.plan, subscriptionStatus: 'active' };
  });
}
