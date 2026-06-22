// PAYG rating — pure integer micro-USDT math (USDT has 6 on-chain decimals, so
// 1 USDT = 1_000_000 micro-USDT). NO float is ever used for money: the rate is a
// bigint and the only arithmetic is integer multiply.

/** $0.25 per minute of source, expressed in micro-USDT (0.25 * 1e6). */
export const PAYG_PER_MINUTE_MICROS = 250_000n;

/**
 * PAYG charge for a source video of `sourceSeconds`, in micro-USDT.
 *
 * Billing rule (disclosed to the user): a 1-minute MINIMUM, then ceil to the next
 * whole minute. So a 1s clip and a 60s clip both bill one minute; 61s bills two.
 * `Math.ceil`/`Math.max` run on the (small, exact) minute COUNT — never on money —
 * and the per-minute price is multiplied in as a bigint, so the result is exact.
 */
export function ratePaygMicros(sourceSeconds: number): bigint {
  // BigInt(Infinity|NaN) throws an opaque TypeError deep in the debit path (after
  // the job is already 'done' → silent revenue loss). Fail loud + early instead.
  if (!Number.isFinite(sourceSeconds)) {
    throw new RangeError(`ratePaygMicros: sourceSeconds must be finite, got ${sourceSeconds}`);
  }
  const minutes = Math.max(1, Math.ceil(sourceSeconds / 60));
  return BigInt(minutes) * PAYG_PER_MINUTE_MICROS;
}

/** Micro-USDT per whole USDT (6 on-chain decimals). */
const MICROS_PER_USDT = 1_000_000n;

/**
 * Render a non-negative micro-USDT amount as the EXACT `numeric(20,6)` string the
 * ledger column stores (e.g. `500000n` → `"0.500000"`). Pure integer arithmetic
 * (BigInt divmod + zero-padding) — no float, so there is no rounding drift at the
 * persistence boundary. Negative input is rejected: amounts are unsigned here and
 * the debit sign is applied by the caller.
 */
export function microsToNumericString(micros: bigint): string {
  if (micros < 0n) {
    throw new Error('microsToNumericString requires a non-negative amount');
  }
  const whole = micros / MICROS_PER_USDT;
  const frac = micros % MICROS_PER_USDT;
  return `${whole}.${frac.toString().padStart(6, '0')}`;
}
