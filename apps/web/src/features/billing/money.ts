// USDT has 6 on-chain decimals. All money math here is INTEGER micro-USDT (BigInt)
// to avoid any IEEE-754 drift, and persists as an exact Postgres numeric(20,6)
// string. This mirrors the worker/ledger discipline (@fliphouse/db rating.ts), so
// both money codebases share the same "no float for money" invariant (BILL-4).

const MICRO = 1_000_000;
const MICRO_BIG = 1_000_000n;

/**
 * Converts a USDT amount to integer micro-USDT (BigInt). `Math.round` runs on the
 * caller-supplied USDT number (a display/price quantity, not money state) to land
 * on the nearest micro; the result is a BigInt so all downstream arithmetic is
 * exact. The input is the only float boundary — by design, prices are authored as
 * decimals (e.g. `9`, `8.999999`).
 */
export function toMicro(usdt: number): bigint {
  return BigInt(Math.round(usdt * MICRO));
}

/**
 * Renders integer micro-USDT (BigInt) as a USDT number for DISPLAY only. Never
 * feed the result back into money arithmetic — keep amounts in micros (BigInt)
 * until the very last display step. Safe for any balance under ~9e9 USDT.
 */
export function microToUsdt(micro: bigint): number {
  return Number(micro) / MICRO;
}

/**
 * Parses a numeric(20,6) column value (string from pg) into EXACT integer
 * micro-USDT (BigInt) — no float ever touches the value. Splits on the decimal
 * point and combines the whole + 6-digit fractional parts with integer math, so a
 * value like `"8.999999"` round-trips to `8_999_999n` exactly.
 */
export function parseUsdtMicros(value: string): bigint {
  const negative = value.startsWith('-');
  const unsigned = negative ? value.slice(1) : value;
  const [wholePart = '0', fracPart = ''] = unsigned.split('.');
  // Right-pad/truncate the fraction to exactly 6 micro digits.
  const micros = `${fracPart}000000`.slice(0, 6);
  const total = BigInt(wholePart) * MICRO_BIG + BigInt(micros);
  return negative ? -total : total;
}

/**
 * Parses a numeric(20,6) column value into a USDT number for DISPLAY. Backed by
 * the exact integer parse so there is no parse-time float drift; the only float
 * appears at the final number conversion. Use {@link parseUsdtMicros} for any
 * value that feeds arithmetic.
 */
export function parseUsdt(value: string): number {
  return microToUsdt(parseUsdtMicros(value));
}

/**
 * Formats integer micro-USDT (BigInt) as the exact numeric(20,6) string the ledger
 * stores (e.g. `500_000n` → `"0.500000"`). Pure integer divmod + zero-padding —
 * no float, no rounding drift at the persistence boundary. Negatives are rendered
 * with a leading `-` (debit amounts persist signed).
 */
export function microsToNumericString(micros: bigint): string {
  const negative = micros < 0n;
  const abs = negative ? -micros : micros;
  const whole = abs / MICRO_BIG;
  const frac = abs % MICRO_BIG;
  const body = `${whole}.${frac.toString().padStart(6, '0')}`;
  return negative ? `-${body}` : body;
}

/** Formats a USDT amount as an exact numeric(20,6) string for persistence. */
export function usdtToNumericString(usdt: number): string {
  return microsToNumericString(toMicro(usdt));
}
