import { QUEUE_NAMES } from '@fliphouse/shared';
import type { QueueName } from '@fliphouse/shared';
import type { ConnectionOptions } from 'bullmq';

import { CPU_WORKER_CONCURRENCY, GPU_GLOBAL_CONCURRENCY } from './queue-config.js';

/** GPU-bound queues — one heavy job per worker, capped cluster-wide by the valve. */
const GPU_QUEUES: ReadonlySet<QueueName> = new Set<QueueName>(['gpu-asr', 'gpu-score']);

export function isGpuQueue(queue: QueueName): boolean {
  return GPU_QUEUES.has(queue);
}

/** How one queue's workers are sized. */
export interface WorkerPlan {
  readonly queue: QueueName;
  /** Per-worker (per-process) concurrency. */
  readonly concurrency: number;
  /** Redis-enforced cluster-wide ceiling (the GPU valve); absent for CPU queues. */
  readonly globalConcurrency?: number;
}

/**
 * The worker-sizing plan for the whole pool (pure — no Redis). GPU queues run one
 * job per worker AND carry the cluster-wide {@link GPU_GLOBAL_CONCURRENCY} valve so
 * N worker replicas never exceed the real GPU count; CPU/transcode/publish queues
 * use the per-worker CPU concurrency with no global cap.
 */
export function planWorkerPool(): readonly WorkerPlan[] {
  return QUEUE_NAMES.map((queue) =>
    isGpuQueue(queue)
      ? { queue, concurrency: 1, globalConcurrency: GPU_GLOBAL_CONCURRENCY }
      : { queue, concurrency: CPU_WORKER_CONCURRENCY },
  );
}

/**
 * Parse a `redis://` / `rediss://` URL into a BullMQ {@link ConnectionOptions}
 * object. Passing options (not a constructed IORedis instance) lets BullMQ own its
 * connections and sidesteps the duplicate-ioredis type clash. `maxRetriesPerRequest:
 * null` is mandatory for blocking worker connections; `rediss:` enables TLS.
 */
export function redisConnectionFromUrl(url: string): ConnectionOptions {
  const parsed = new URL(url);
  return {
    host: parsed.hostname,
    port: parsed.port ? Number(parsed.port) : 6379,
    maxRetriesPerRequest: null,
    ...(parsed.username ? { username: decodeURIComponent(parsed.username) } : {}),
    ...(parsed.password ? { password: decodeURIComponent(parsed.password) } : {}),
    ...(parsed.protocol === 'rediss:' ? { tls: {} } : {}),
  };
}
