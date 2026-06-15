import * as z from 'zod';
import { Env } from '@/libs/Env';

// The monetization grid (roadmap §1.12, verified against Opus Clip: Pro = 300 min /
// $29). Caps limit source-video minutes/month — the main GPU cost driver. Prices and
// caps live in config (BILLING_PLAN_ENV override), never hardcoded at a call-site.

export type PlanId = 'free' | 'start' | 'active' | 'studio' | 'payg';

export type Plan = {
  id: PlanId;
  /** Monthly price in USDT (0 for free and payg). */
  priceUsdt: number;
  /** Source-minute cap per month; null for payg (gated by balance instead). */
  minutesPerMonth: number | null;
};

/** PAYG charge per source-minute (~90% margin over ~$0.025/min GPU cost). */
export const PAYG_PER_MINUTE_USDT = 0.25;

const DEFAULT_PLANS: Record<PlanId, Plan> = {
  free: { id: 'free', priceUsdt: 0, minutesPerMonth: 30 },
  start: { id: 'start', priceUsdt: 9, minutesPerMonth: 150 },
  active: { id: 'active', priceUsdt: 24, minutesPerMonth: 300 },
  studio: { id: 'studio', priceUsdt: 59, minutesPerMonth: 1000 },
  payg: { id: 'payg', priceUsdt: 0, minutesPerMonth: null },
};

const planOverrideSchema = z.partialRecord(
  z.enum(['free', 'start', 'active', 'studio', 'payg']),
  z.object({
    priceUsdt: z.number().min(0),
    minutesPerMonth: z.number().int().min(0).nullable(),
  }),
);

/**
 * Returns the full plan grid. A `BILLING_PLAN_ENV` JSON string (or an explicit
 * `rawOverride`, used by tests) merges per-plan overrides onto the defaults.
 */
export function getPlans(
  rawOverride: string | undefined = Env.BILLING_PLAN_ENV,
): Record<PlanId, Plan> {
  if (!rawOverride) {
    return DEFAULT_PLANS;
  }

  const parsed = planOverrideSchema.parse(JSON.parse(rawOverride));
  const merged: Record<PlanId, Plan> = { ...DEFAULT_PLANS };

  for (const [id, override] of Object.entries(parsed)) {
    const planId = id as PlanId;
    merged[planId] = { id: planId, ...override };
  }

  return merged;
}

export function getPlan(id: PlanId, rawOverride?: string): Plan {
  return getPlans(rawOverride)[id];
}

/** PAYG cost for a clip of `sourceMinutes` minutes, rounded to USDT precision. */
export function paygCostUsdt(sourceMinutes: number): number {
  return Math.round(sourceMinutes * PAYG_PER_MINUTE_USDT * 1_000_000) / 1_000_000;
}
