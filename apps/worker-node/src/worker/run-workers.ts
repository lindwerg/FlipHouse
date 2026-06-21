import { pathToFileURL } from 'node:url';

import { createDb } from '@fliphouse/db';
import { Queue, type ConnectionOptions } from 'bullmq';
import { Pool } from 'pg';

import { planWorkerPool, redisConnectionFromUrl } from '../queues/worker-pool.js';
import { makeStageProcessor } from '../stages/stage-processor.js';

import { buildStageProcessorDeps } from './build-stage-processor-deps.js';
import { createStageWorker } from './make-worker.js';

function requireEnv(env: Record<string, string | undefined>, name: string): string {
  const value = env[name];
  if (!value) {
    throw new Error(`missing required env var: ${name}`);
  }
  return value;
}

export interface RunningWorkers {
  /** Graceful shutdown: stop fetching, let in-flight jobs finish, release resources. */
  readonly shutdown: () => Promise<void>;
}

/**
 * Boot one BullMQ Worker per queue, sharing a single connection config, pg Pool and
 * stage processor. GPU queues get the cluster-wide ceiling via setGlobalConcurrency
 * BEFORE any worker pulls; every worker uses the reliability config in
 * make-worker.ts. Returns a graceful shutdown the entrypoint wires to SIGTERM so an
 * in-flight ffmpeg/GPU stage finishes (and writes its sentinel) instead of being
 * abandoned and double-run on the next deploy.
 */
export async function runWorkers(
  env: Record<string, string | undefined> = process.env,
): Promise<RunningWorkers> {
  const connection: ConnectionOptions = redisConnectionFromUrl(requireEnv(env, 'REDIS_URL'));
  const pool = new Pool({ connectionString: requireEnv(env, 'DATABASE_URL') });
  const db = createDb(pool);

  const processor = makeStageProcessor(buildStageProcessorDeps(db, env));
  const plans = planWorkerPool();

  for (const plan of plans) {
    if (plan.globalConcurrency !== undefined) {
      const queue = new Queue(plan.queue, { connection });
      await queue.setGlobalConcurrency(plan.globalConcurrency);
      await queue.close();
    }
  }

  const workers = plans.map((plan) =>
    createStageWorker(plan.queue, connection, processor, plan.concurrency),
  );
  await Promise.all(workers.map((worker) => worker.waitUntilReady()));

  const shutdown = async (): Promise<void> => {
    // worker.close() drains in-flight jobs and closes BullMQ's own connections.
    await Promise.all(workers.map((worker) => worker.close()));
    await pool.end();
  };
  return { shutdown };
}

/* v8 ignore start -- process entrypoint: real signals + I/O, exercised on deploy */
function installSignalHandlers(running: RunningWorkers): void {
  for (const signal of ['SIGTERM', 'SIGINT'] as const) {
    process.once(signal, () => {
      running.shutdown().then(
        () => process.exit(0),
        () => process.exit(1),
      );
    });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runWorkers().then(installSignalHandlers, (err: unknown) => {
    process.stderr.write(`worker bootstrap failed: ${String(err)}\n`);
    process.exit(1);
  });
}
/* v8 ignore stop */
