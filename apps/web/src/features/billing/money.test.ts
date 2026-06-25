import { describe, expect, it } from 'vitest';
import {
  microsToNumericString,
  microToUsdt,
  parseUsdt,
  parseUsdtMicros,
  toMicro,
  usdtToNumericString,
} from './money';

// BILL-4: the web money path mirrors the worker/ledger bigint discipline — all
// arithmetic is integer micro-USDT, never IEEE-754 float. These tests pin the
// exact round-trip through the numeric(20,6) string boundary.

describe('money (integer micro-USDT)', () => {
  it('toMicro returns exact integer micros as BigInt', () => {
    expect(toMicro(9)).toBe(9_000_000n);
    expect(toMicro(0.25)).toBe(250_000n);
    expect(toMicro(8.999999)).toBe(8_999_999n);
    expect(toMicro(0)).toBe(0n);
  });

  it('parseUsdtMicros parses a numeric(20,6) string EXACTLY (no float drift)', () => {
    expect(parseUsdtMicros('8.999999')).toBe(8_999_999n);
    expect(parseUsdtMicros('0.500000')).toBe(500_000n);
    expect(parseUsdtMicros('10')).toBe(10_000_000n);
    expect(parseUsdtMicros('0')).toBe(0n);
    // Signed (debit) values round-trip with the sign preserved.
    expect(parseUsdtMicros('-1.500000')).toBe(-1_500_000n);
    // Fewer/zero fractional digits and over-long fractions are handled.
    expect(parseUsdtMicros('2.5')).toBe(2_500_000n);
    expect(parseUsdtMicros('2.1234567')).toBe(2_123_456n); // truncated to 6 micro digits
  });

  it('microsToNumericString renders the exact numeric(20,6) string', () => {
    expect(microsToNumericString(500_000n)).toBe('0.500000');
    expect(microsToNumericString(8_999_999n)).toBe('8.999999');
    expect(microsToNumericString(0n)).toBe('0.000000');
    expect(microsToNumericString(-1_500_000n)).toBe('-1.500000');
  });

  it('a fractional price round-trips exactly through the string boundary', () => {
    // The BILL-4 invariant: 8.999999 must survive USDT → micros → string → micros
    // with zero drift (a float path would land on 8.999998999... and lose a micro).
    const micros = toMicro(8.999999);
    const persisted = microsToNumericString(micros);
    expect(persisted).toBe('8.999999');
    expect(parseUsdtMicros(persisted)).toBe(micros);
  });

  it('usdtToNumericString composes toMicro + microsToNumericString', () => {
    expect(usdtToNumericString(8.999999)).toBe('8.999999');
    expect(usdtToNumericString(-0.25)).toBe('-0.250000');
  });

  it('display helpers (microToUsdt / parseUsdt) are exact within the float-safe range', () => {
    expect(microToUsdt(8_999_999n)).toBeCloseTo(8.999999, 6);
    expect(parseUsdt('8.999999')).toBeCloseTo(8.999999, 6);
    expect(parseUsdt('-1.500000')).toBeCloseTo(-1.5, 6);
  });
});
