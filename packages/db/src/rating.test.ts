import { expect, test } from 'vitest';

import { PAYG_PER_MINUTE_MICROS, microsToNumericString, ratePaygMicros } from './rating.js';

test('PAYG_PER_MINUTE_MICROS is $0.25 in micro-USDT', () => {
  expect(PAYG_PER_MINUTE_MICROS).toBe(250_000n);
});

// Golden table: 1-minute minimum + ceil-to-whole-minute (the disclosed rule).
test.each([
  [0, 250_000n], // empty/unknown source still bills the minimum minute
  [1, 250_000n], // 1s → 1 minute
  [59, 250_000n], // just under a minute → 1 minute
  [60, 250_000n], // exactly a minute → 1 minute
  [61, 500_000n], // just over → 2 minutes
  [120, 500_000n], // exactly two minutes → 2 minutes
  [121, 750_000n], // → 3 minutes
  [3600, 15_000_000n], // 60 minutes → $15
])('ratePaygMicros(%is) = %s micros', (seconds, expected) => {
  expect(ratePaygMicros(seconds)).toBe(expected);
});

// A non-finite duration must fail loud here, not throw an opaque BigInt TypeError
// deep in the debit path after the job is already 'done'.
test.each([Infinity, -Infinity, NaN])('ratePaygMicros(%s) throws RangeError', (bad) => {
  expect(() => ratePaygMicros(bad)).toThrow(RangeError);
});

test('microsToNumericString renders exact numeric(20,6) strings with no float drift', () => {
  expect(microsToNumericString(0n)).toBe('0.000000');
  expect(microsToNumericString(250_000n)).toBe('0.250000');
  expect(microsToNumericString(500_000n)).toBe('0.500000');
  expect(microsToNumericString(1_000_000n)).toBe('1.000000');
  expect(microsToNumericString(15_000_000n)).toBe('15.000000');
  expect(microsToNumericString(1n)).toBe('0.000001');
  expect(microsToNumericString(123_456_789n)).toBe('123.456789');
});

test('microsToNumericString rejects a negative amount', () => {
  expect(() => microsToNumericString(-1n)).toThrow(/non-negative/);
});
