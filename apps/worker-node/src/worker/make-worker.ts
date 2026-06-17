import { Worker } from 'bullmq';
import type { ConnectionOptions, Processor } from 'bullmq';

import {
  CPU_WORKER_CONCURRENCY,
  LOCK_DURATION_MS,
  MAX_STALLED_COUNT,
  STALLED_INTERVAL_MS,
} from '../queues/queue-config.js';

/**
 * Create a BullMQ Worker for one queue with the FlipHouse reliability config
 * (stall/lock settings from docs/01 §5). Thin real-Redis wrapper — exercised by
 * the worker integration tests, not unit tests.
 */
export function createStageWorker(
  queueName: string,
  connection: ConnectionOptions,
  processor: Processor,
  concurrency: number = CPU_WORKER_CONCURRENCY,
): Worker {
  return new Worker(queueName, processor, {
    connection,
    concurrency,
    lockDuration: LOCK_DURATION_MS,
    stalledInterval: STALLED_INTERVAL_MS,
    maxStalledCount: MAX_STALLED_COUNT,
  });
}
