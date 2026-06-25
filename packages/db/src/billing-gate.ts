// Worker-side pre-scoring affordability gate (BILL-2). The web `usageGate` runs
// the same check at submit time, but the live upload-authorization path never
// wires it (duration is unknown at grant time), so an unaffordable/over-cap job
// would otherwise run the expensive scoring stages and only get billed after the
// fact (PAYG into arbitrary negative balance; subscription over its cap). This
// gate fires at the PROBE seam — once the transcode has measured the real source
// duration — and FAILS the flow before any scoring GPU/LLM spend.
//
// Money is integer micro-USDT throughout (NO float). The per-minute rate and the
// plan minute-caps mirror apps/web `plans.ts`; the caps are overridable via the
// SAME `BILLING_PLAN_ENV` knob so the two stay in lock-step without a cross-app
// import (the worker is a separate deployable and cannot import apps/web).

import { sql } from 'drizzle-orm';

import type { Db } from './client.js';
import type { BillingPlan } from './ledger-repo.js';
import { PAYG_PER_MINUTE_MICROS } from './rating.js';

/** Why a clip job was blocked pre-scoring — a machine code, not a string match. */
export type BillingBlockReason = 'insufficient_balance' | 'minute_cap_exceeded';

/** Thrown when a job is unaffordable/over-cap at the probe seam (caught → fatal flow failure). */
export class BillingError extends Error {
  readonly reason: BillingBlockReason;

  constructor(reason: BillingBlockReason, message: string) {
    super(message);
    this.name = 'BillingError';
    this.reason = reason;
  }
}

/** Monthly source-minute cap per plan; `null` = no cap (PAYG, gated by balance). */
const DEFAULT_MINUTE_CAPS: Record<BillingPlan, number | null> = {
  free: 30,
  start: 150,
  active: 300,
  studio: 1000,
  payg: null,
};

/** A subset of the env we read; defaults to `process.env` in production. */
export interface BillingGateEnv {
  readonly BILLING_PLAN_ENV?: string;
}

/**
 * Resolve the monthly minute cap for a plan, applying any `BILLING_PLAN_ENV`
 * override (same JSON shape apps/web parses: `{ "<plan>": { "minutesPerMonth": N|null } }`).
 * A malformed override is ignored (fail-open to the defaults) — the gate must
 * never wedge the pipeline on a bad env string; the worst case is it falls back
 * to the disclosed default cap.
 */
export function resolveMinuteCap(plan: BillingPlan, env: BillingGateEnv): number | null {
  const raw = env.BILLING_PLAN_ENV;
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as Record<string, { minutesPerMonth?: number | null }>;
      const override = parsed[plan];
      if (override && 'minutesPerMonth' in override) {
        return override.minutesPerMonth ?? null;
      }
    } catch {
      // Malformed override → fall through to the default cap (fail-open).
    }
  }
  return DEFAULT_MINUTE_CAPS[plan];
}

/** Whole billable minutes for a source of `durationSec`: a 1-min floor, then ceil. */
function billedMinutes(durationSec: number): number {
  return Math.max(1, Math.ceil(durationSec / 60));
}

/** The owner's billing state the gate reads off `subscription` (NULL row → free defaults). */
interface BillingState {
  readonly plan: BillingPlan;
  readonly balanceMicros: bigint;
  readonly minutesUsedThisPeriod: number;
}

/**
 * Read the owner's plan + prepaid balance (as integer micros) + minutes used.
 * A user with no `subscription` row yet is a clean free period: plan `free`,
 * balance 0, 0 minutes used — mirroring the web gate's no-row default so a
 * missing row never silently passes a PAYG charge.
 */
async function loadBillingState(db: Db, userId: string): Promise<BillingState> {
  const result = await db.execute<{
    plan: BillingPlan;
    balance_micros: string;
    minutes_used_this_period: number;
  }>(sql`
    SELECT
      plan,
      -- numeric(20,6) USDT → integer micro-USDT, in SQL so no float crosses the wire.
      (balance_usdt * 1000000)::bigint AS balance_micros,
      minutes_used_this_period
    FROM subscription
    WHERE user_id = ${userId}
  `);
  const row = result.rows[0];
  if (!row) {
    return { plan: 'free', balanceMicros: 0n, minutesUsedThisPeriod: 0 };
  }
  return {
    plan: row.plan,
    balanceMicros: BigInt(row.balance_micros),
    minutesUsedThisPeriod: row.minutes_used_this_period,
  };
}

/**
 * Gate a clip job for a source of `durationSec` BEFORE the expensive scoring
 * stages run. PAYG users must have enough prepaid balance to cover the per-minute
 * cost; subscription users must be within their monthly minute cap. Throws
 * {@link BillingError} when blocked; resolves silently when allowed. Pure integer
 * money math — no float ever touches the balance comparison.
 */
export async function assertAffordable(
  db: Db,
  userId: string,
  durationSec: number,
  env: BillingGateEnv = process.env,
): Promise<void> {
  const minutes = billedMinutes(durationSec);
  const state = await loadBillingState(db, userId);

  const cap = resolveMinuteCap(state.plan, env);
  if (cap === null) {
    // PAYG (no cap) → gate on the prepaid balance covering the per-minute cost.
    const costMicros = BigInt(minutes) * PAYG_PER_MINUTE_MICROS;
    if (state.balanceMicros < costMicros) {
      throw new BillingError('insufficient_balance', 'insufficient balance for PAYG clip');
    }
    return;
  }

  if (state.minutesUsedThisPeriod + minutes > cap) {
    throw new BillingError('minute_cap_exceeded', 'monthly minute cap exceeded');
  }
}
