// USDT has 6 on-chain decimals. We do all balance math in integer micro-USDT to
// avoid binary float drift, and persist as an exact Postgres numeric(20,6) string.

const MICRO = 1_000_000;

export function toMicro(usdt: number): number {
  return Math.round(usdt * MICRO);
}

export function microToUsdt(micro: number): number {
  return micro / MICRO;
}

/** Parses a numeric(20,6) column value (string from pg) into a USDT number. */
export function parseUsdt(value: string): number {
  return Number.parseFloat(value);
}

/** Formats a USDT amount as an exact numeric(20,6) string for persistence. */
export function usdtToNumericString(usdt: number): string {
  return (Math.round(usdt * MICRO) / MICRO).toFixed(6);
}
