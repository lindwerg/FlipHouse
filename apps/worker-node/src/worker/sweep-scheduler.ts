/**
 * Interval scheduler for the lost-callback park sweep (REL-1).
 *
 * {@link buildParkSweep} produces a `runOnce()` reconciler but NOTHING drove it —
 * the GPU-ASR backstop was inert, so a single lost Modal webhook wedged an upload
 * (it burned MAX_PARK_MS, re-submitted, and could re-submit forever). This module
 * is the missing timer: it ticks `runOnce` every `intervalMs`, logging each
 * summary and SWALLOWING any error so one transient Redis/fetch blip never kills
 * the worker. The clock seam (`setIntervalFn`/`clearIntervalFn`) is injected so
 * the drive/stop/error-swallow logic is unit-tested without a real timer.
 *
 * `intervalMs` must be < MAX_PARK_MS so an expired park is caught within one
 * window; the default (60s) is well under the 15-min park deadline.
 */

import { MAX_PARK_MS } from '../state/park.js';

/** Default sweep cadence: 60s — comfortably below MAX_PARK_MS (15 min). */
export const DEFAULT_SWEEP_INTERVAL_MS = 60_000;

/** Resolve the sweep interval from env, clamped to (0, MAX_PARK_MS); else the default. */
export function sweepIntervalMs(env: Record<string, string | undefined>): number {
  const raw = Number(env.PARK_SWEEP_INTERVAL_MS);
  if (Number.isFinite(raw) && raw > 0 && raw < MAX_PARK_MS) return raw;
  return DEFAULT_SWEEP_INTERVAL_MS;
}

/**
 * Grace before the status reconciler (REL-2) declares a non-terminal upload
 * stuck. Must exceed the slowest single stage's wall time so a healthy but slow
 * pipeline (which touches `updated_at` on every status hop) is never falsely
 * failed. Default 30 min — well past the longest CPU/GPU stage.
 */
export const DEFAULT_STATUS_RECONCILE_GRACE_MS = 30 * 60_000;

/** Resolve the status-reconcile grace from env (positive ms), else the default. */
export function statusReconcileGraceMs(env: Record<string, string | undefined>): number {
  const raw = Number(env.STATUS_RECONCILE_GRACE_MS);
  if (Number.isFinite(raw) && raw > 0) return raw;
  return DEFAULT_STATUS_RECONCILE_GRACE_MS;
}

/** Anything that reconciles once and returns a loggable summary (park-sweep, status-reconcile). */
export interface RunnableSweep {
  runOnce(): Promise<object>;
}

/** Minimal logger surface used by the scheduler. */
export interface SweepLogger {
  info(obj: Record<string, unknown>, msg: string): void;
  error(obj: Record<string, unknown>, msg: string): void;
}

/** Timer seams (injected so unit tests drive ticks synchronously, no real clock). */
export interface SchedulerClock {
  setIntervalFn(cb: () => void, ms: number): ReturnType<typeof setInterval>;
  clearIntervalFn(handle: ReturnType<typeof setInterval>): void;
}

const realClock: SchedulerClock = {
  /* v8 ignore start -- real Node timers; the scheduler logic is tested via the injected clock */
  setIntervalFn: (cb, ms) => {
    const handle = setInterval(cb, ms);
    handle.unref();
    return handle;
  },
  clearIntervalFn: (handle) => clearInterval(handle),
  /* v8 ignore stop */
};

export interface SweepSchedulerOptions {
  readonly intervalMs?: number;
  readonly clock?: SchedulerClock;
  /** Log label distinguishing this sweep (default `'sweep'`). */
  readonly label?: string;
}

export interface SweepScheduler {
  /** Stop ticking. Idempotent — safe to call from the shutdown chain more than once. */
  stop(): void;
}

/**
 * Start ticking `sweep.runOnce()` every `intervalMs`. Each tick logs its summary
 * (or logs-and-swallows its error); a tick NEVER throws into the timer. Returns a
 * `stop()` the shutdown chain calls before `sweep.close()`.
 */
export function startSweepScheduler(
  sweep: RunnableSweep,
  logger: SweepLogger,
  opts: SweepSchedulerOptions = {},
): SweepScheduler {
  const intervalMs = opts.intervalMs ?? DEFAULT_SWEEP_INTERVAL_MS;
  const clock = opts.clock ?? realClock;
  const label = opts.label ?? 'sweep';

  const tick = (): void => {
    sweep.runOnce().then(
      (summary) => logger.info({ ...summary }, label),
      (err: unknown) => logger.error({ err: String(err) }, `${label} failed`),
    );
  };

  const handle = clock.setIntervalFn(tick, intervalMs);
  let stopped = false;
  return {
    stop: (): void => {
      if (stopped) return;
      stopped = true;
      clock.clearIntervalFn(handle);
    },
  };
}
