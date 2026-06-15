import { eq } from 'drizzle-orm';
import { subscriptionSchema } from '@/models/Schema';
import type { BillingDatabase } from './balance';
import { parseUsdt } from './money';
import { getPlan, paygCostUsdt } from './plans';

// Billing error surfaced to the clip-submission path. Carries a machine code so
// callers (and the UI) can branch without string matching.
export type BillingBlockReason = 'insufficient_balance' | 'minute_cap_exceeded';

export class BillingError extends Error {
  readonly reason: BillingBlockReason;

  constructor(reason: BillingBlockReason, message: string) {
    super(message);
    this.name = 'BillingError';
    this.reason = reason;
  }
}

/**
 * Gates a clip job for `sourceMinutes`. PAYG users must have enough balance to
 * cover the cost; subscription users must be within their monthly minute cap.
 * Throws BillingError when blocked; resolves when allowed.
 */
export async function assertCanClip(
  db: BillingDatabase,
  userId: string,
  sourceMinutes: number,
): Promise<void> {
  const rows = await db
    .select({
      plan: subscriptionSchema.plan,
      balanceUsdt: subscriptionSchema.balanceUsdt,
      minutesUsedThisPeriod: subscriptionSchema.minutesUsedThisPeriod,
    })
    .from(subscriptionSchema)
    .where(eq(subscriptionSchema.userId, userId));

  // No row yet → treat as the free plan from a clean period.
  const row = rows[0] ?? {
    plan: 'free' as const,
    balanceUsdt: '0',
    minutesUsedThisPeriod: 0,
  };

  if (row.plan === 'payg') {
    const cost = paygCostUsdt(sourceMinutes);
    if (parseUsdt(row.balanceUsdt) < cost) {
      throw new BillingError(
        'insufficient_balance',
        'insufficient balance for PAYG clip',
      );
    }
    return;
  }

  const cap = getPlan(row.plan).minutesPerMonth;
  if (cap !== null && row.minutesUsedThisPeriod + sourceMinutes > cap) {
    throw new BillingError(
      'minute_cap_exceeded',
      'monthly minute cap exceeded',
    );
  }
}
