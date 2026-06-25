import { Worker } from 'bullmq';
import type { ConnectionOptions, Job, Processor } from 'bullmq';

import { log } from '../log.js';
import {
  CPU_WORKER_CONCURRENCY,
  LOCK_DURATION_MS,
  MAX_STALLED_COUNT,
  STALLED_INTERVAL_MS,
} from '../queues/queue-config.js';

/** Minimal Worker event surface used by {@link attachWorkerObservability} (injectable for tests). */
export interface ListenableWorker {
  on(event: 'failed', cb: (job: Job | undefined, err: Error) => void): unknown;
  on(event: 'error', cb: (err: Error) => void): unknown;
}

/** Minimal logger surface used here (injectable so the listeners are unit-testable). */
export interface WorkerLogger {
  error(obj: Record<string, unknown>, msg: string): void;
}

/**
 * Attach BullMQ observability listeners to a Worker (OBS-3). BullMQ surfaces
 * per-job exhaustion via `failed` and Redis-connection trouble via `error`;
 * without a handler both are invisible at the worker level — a repeatedly-failing
 * stage or a flapping Redis leaves no actionable worker log. The `error` handler
 * ALSO doubles as the guard BullMQ requires: an unhandled `error` event would
 * otherwise propagate as an uncaught exception.
 */
export function attachWorkerObservability(
  worker: ListenableWorker,
  queueName: string,
  logger: WorkerLogger = log,
): void {
  worker.on('failed', (job: Job | undefined, err: Error) => {
    logger.error(
      { queue: queueName, jobId: job?.id, attemptsMade: job?.attemptsMade, err: err.message },
      'worker job failed',
    );
  });
  worker.on('error', (err: Error) => {
    logger.error({ queue: queueName, err: err.message }, 'worker connection error');
  });
}

/**
 * Create a BullMQ Worker for one queue with the FlipHouse reliability config
 * (stall/lock settings from docs/01 §5) and the OBS-3 `failed`/`error` listeners.
 * Thin real-Redis wrapper — exercised by the worker integration tests, not unit
 * tests; the listener wiring is unit-tested via {@link attachWorkerObservability}.
 */
export function createStageWorker(
  queueName: string,
  connection: ConnectionOptions,
  processor: Processor,
  concurrency: number = CPU_WORKER_CONCURRENCY,
): Worker {
  const worker = new Worker(queueName, processor, {
    connection,
    concurrency,
    lockDuration: LOCK_DURATION_MS,
    stalledInterval: STALLED_INTERVAL_MS,
    maxStalledCount: MAX_STALLED_COUNT,
  });
  attachWorkerObservability(worker, queueName);
  return worker;
}
