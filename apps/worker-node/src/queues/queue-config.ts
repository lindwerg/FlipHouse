import type { Stage } from '@fliphouse/shared';

/**
 * Tunable BullMQ knobs for the Flow-DAG. The GPU valve + lock/stall settings
 * implement the docs/01 §5 reliability invariants.
 */

/** Redis-enforced cluster ceiling on GPU queues (docs/01 §5 GPU valve). */
export const GPU_GLOBAL_CONCURRENCY = 2;

/** Per-worker concurrency for CPU stages (docs/01 §6: floor(vCPU/2), MVP = 1). */
export const CPU_WORKER_CONCURRENCY = 1;

/**
 * Lock a worker holds while processing a stage. MUST exceed the longest stage's
 * wall-clock. PLACEHOLDER pending real timing on the 2h canon fixture (open
 * decision #2); the {@link assertTimeoutsBelowLock} invariant holds regardless.
 */
export const LOCK_DURATION_MS = 15 * 60 * 1000;

export const STALLED_INTERVAL_MS = 30_000;
export const MAX_STALLED_COUNT = 1;

/** Retention so the FAILED set doubles as a bounded dead-letter (docs blueprint §4). */
export const RETENTION = {
  complete: { age: 3600, count: 1000 },
  fail: { age: 86_400 },
} as const;

export interface StageRetryPolicy {
  readonly attempts: number;
  readonly backoff: { readonly type: 'exponential' | 'fixed'; readonly delay: number };
}

/**
 * Per-stage retry policy. ASR/score get more attempts + exponential backoff to
 * ride out 429/5xx; mostly-fatal-input stages (transcode/store/publish) get few.
 */
export const STAGE_RETRY: Readonly<Record<Stage, StageRetryPolicy>> = {
  transcode: { attempts: 2, backoff: { type: 'exponential', delay: 2000 } },
  asr: { attempts: 5, backoff: { type: 'exponential', delay: 2000 } },
  score: { attempts: 5, backoff: { type: 'exponential', delay: 2000 } },
  reframe: { attempts: 3, backoff: { type: 'exponential', delay: 2000 } },
  caption: { attempts: 3, backoff: { type: 'exponential', delay: 2000 } },
  banner: { attempts: 3, backoff: { type: 'exponential', delay: 2000 } },
  store: { attempts: 2, backoff: { type: 'exponential', delay: 2000 } },
  publish: { attempts: 2, backoff: { type: 'exponential', delay: 2000 } },
};

/** Per-stage Node-side timeout. INVARIANT: every value < LOCK_DURATION_MS. */
export const STAGE_TIMEOUT_MS: Readonly<Record<Stage, number>> = {
  transcode: 600_000,
  asr: 600_000,
  score: 300_000,
  reframe: 300_000,
  caption: 120_000,
  banner: 120_000,
  store: 120_000,
  publish: 60_000,
};

/**
 * Assert every stage timeout is strictly below the worker lock so a Node-side
 * AbortSignal always fires BEFORE BullMQ's stall recovery — otherwise a stalled
 * job could double-run. Defaults to the real config; accepts overrides so the
 * invariant itself is unit-testable.
 */
export function assertTimeoutsBelowLock(
  timeouts: Readonly<Record<string, number>> = STAGE_TIMEOUT_MS,
  lockMs: number = LOCK_DURATION_MS,
): void {
  for (const [stage, timeout] of Object.entries(timeouts)) {
    if (timeout >= lockMs) {
      throw new Error(
        `stage timeout invariant violated: "${stage}" timeout ${timeout}ms >= lock ${lockMs}ms`,
      );
    }
  }
}
