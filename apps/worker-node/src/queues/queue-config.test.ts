import { expect, test } from 'vitest';

import { STAGES } from '@fliphouse/shared';

import {
  LOCK_DURATION_MS,
  STAGE_RETRY,
  STAGE_TIMEOUT_MS,
  assertTimeoutsBelowLock,
} from './queue-config.js';

test('STAGE_RETRY and STAGE_TIMEOUT_MS cover every stage exactly', () => {
  for (const stage of STAGES) {
    expect(STAGE_RETRY[stage].attempts).toBeGreaterThan(0);
    expect(STAGE_TIMEOUT_MS[stage]).toBeGreaterThan(0);
  }
  expect(Object.keys(STAGE_RETRY).sort()).toEqual([...STAGES].sort());
  expect(Object.keys(STAGE_TIMEOUT_MS).sort()).toEqual([...STAGES].sort());
});

test('assertTimeoutsBelowLock passes for the real config', () => {
  expect(() => assertTimeoutsBelowLock()).not.toThrow();
});

test('assertTimeoutsBelowLock throws when a timeout reaches the lock', () => {
  expect(() => assertTimeoutsBelowLock({ store: LOCK_DURATION_MS })).toThrow(
    /timeout invariant violated/,
  );
});
