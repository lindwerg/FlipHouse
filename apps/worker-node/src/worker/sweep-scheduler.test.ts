import { expect, test, vi } from 'vitest';

import { MAX_PARK_MS } from '../state/park.js';

import {
  DEFAULT_STATUS_RECONCILE_GRACE_MS,
  DEFAULT_SWEEP_INTERVAL_MS,
  startSweepScheduler,
  statusReconcileGraceMs,
  sweepIntervalMs,
  type SchedulerClock,
} from './sweep-scheduler.js';

test('sweepIntervalMs reads a positive override below MAX_PARK_MS, else the default', () => {
  expect(sweepIntervalMs({ PARK_SWEEP_INTERVAL_MS: '30000' })).toBe(30_000);
  expect(sweepIntervalMs({})).toBe(DEFAULT_SWEEP_INTERVAL_MS);
  expect(sweepIntervalMs({ PARK_SWEEP_INTERVAL_MS: 'abc' })).toBe(DEFAULT_SWEEP_INTERVAL_MS);
  expect(sweepIntervalMs({ PARK_SWEEP_INTERVAL_MS: '0' })).toBe(DEFAULT_SWEEP_INTERVAL_MS);
  // At/above MAX_PARK_MS an expired park could escape a window → clamp to default.
  expect(sweepIntervalMs({ PARK_SWEEP_INTERVAL_MS: String(MAX_PARK_MS) })).toBe(DEFAULT_SWEEP_INTERVAL_MS);
});

test('statusReconcileGraceMs reads a positive override, else the default', () => {
  expect(statusReconcileGraceMs({ STATUS_RECONCILE_GRACE_MS: '600000' })).toBe(600_000);
  expect(statusReconcileGraceMs({})).toBe(DEFAULT_STATUS_RECONCILE_GRACE_MS);
  expect(statusReconcileGraceMs({ STATUS_RECONCILE_GRACE_MS: '-1' })).toBe(DEFAULT_STATUS_RECONCILE_GRACE_MS);
});

/** A controllable clock seam: capture the tick so the test drives it synchronously. */
function fakeClock(): { clock: SchedulerClock; tick: () => void; cleared: boolean[] } {
  let captured: () => void = () => undefined;
  const cleared: boolean[] = [];
  const clock: SchedulerClock = {
    setIntervalFn: (cb) => {
      captured = cb;
      return 0 as unknown as ReturnType<typeof setInterval>;
    },
    clearIntervalFn: () => cleared.push(true),
  };
  return { clock, tick: () => captured(), cleared };
}

test('startSweepScheduler runs the sweep on each tick and logs the summary with the label', async () => {
  const { clock, tick } = fakeClock();
  const summary = { scanned: 2, resumed: 1, failed: 1, rearmed: 0, lostRace: 0 };
  const sweep = { runOnce: vi.fn().mockResolvedValue(summary) };
  const logger = { info: vi.fn(), error: vi.fn() };

  startSweepScheduler(sweep, logger, { clock, intervalMs: 1000, label: 'park-sweep' });
  tick();
  await Promise.resolve(); // let the runOnce promise settle

  expect(sweep.runOnce).toHaveBeenCalledTimes(1);
  expect(logger.info).toHaveBeenCalledWith(summary, 'park-sweep');
  expect(logger.error).not.toHaveBeenCalled();
});

test('startSweepScheduler swallows-and-logs a sweep error so the timer never throws', async () => {
  const { clock, tick } = fakeClock();
  const sweep = { runOnce: vi.fn().mockRejectedValue(new Error('redis down')) };
  const logger = { info: vi.fn(), error: vi.fn() };

  startSweepScheduler(sweep, logger, { clock, label: 'park-sweep' });
  expect(() => tick()).not.toThrow();
  await Promise.resolve();
  await Promise.resolve();

  expect(logger.error).toHaveBeenCalledWith({ err: 'Error: redis down' }, 'park-sweep failed');
});

test('startSweepScheduler defaults the label and falls back to the default interval', async () => {
  const { clock, tick } = fakeClock();
  const sweep = { runOnce: vi.fn().mockResolvedValue({ ok: 1 }) };
  const logger = { info: vi.fn(), error: vi.fn() };

  startSweepScheduler(sweep, logger, { clock });
  tick();
  await Promise.resolve();

  expect(logger.info).toHaveBeenCalledWith({ ok: 1 }, 'sweep');
});

test('stop() clears the interval and is idempotent', () => {
  const { clock, cleared } = fakeClock();
  const sweep = { runOnce: vi.fn().mockResolvedValue({}) };
  const logger = { info: vi.fn(), error: vi.fn() };

  const scheduler = startSweepScheduler(sweep, logger, { clock });
  scheduler.stop();
  scheduler.stop(); // second call is a no-op

  expect(cleared).toEqual([true]);
});
