import { execFile } from 'node:child_process';
import { pathToFileURL } from 'node:url';

import { createDb } from '@fliphouse/db';
import { Queue, type ConnectionOptions } from 'bullmq';
import { Pool } from 'pg';

import { createFlowProjector } from '../progress/projector.js';
import { resolvePythonEntry } from '../python/resolve-entry.js';
import { planWorkerPool, redisConnectionFromUrl } from '../queues/worker-pool.js';
import { makeStageProcessor } from '../stages/stage-processor.js';

import { buildStageProcessorDeps } from './build-stage-processor-deps.js';
import { createStageWorker } from './make-worker.js';
import { createResumeAsrWorker } from './run-resume-asr.js';

/** Hard cap on the boot selftest so a hung interpreter cannot wedge startup. */
const SELFTEST_TIMEOUT_MS = 15_000;

function requireEnv(env: Record<string, string | undefined>, name: string): string {
  const value = env[name];
  if (!value) {
    throw new Error(`missing required env var: ${name}`);
  }
  return value;
}

/** Run `<python> -m fliphouse_worker.cli --selftest`, resolving its exit code. */
type SelftestRunner = (command: string, args: readonly string[]) => Promise<number>;

/* v8 ignore start -- real subprocess I/O; covered by the injected `_run` seam */
const defaultSelftestRun: SelftestRunner = (command, args) =>
  new Promise<number>((resolve, reject) => {
    execFile(command, [...args], { timeout: SELFTEST_TIMEOUT_MS }, (err) => {
      if (err) {
        const code = typeof err.code === 'number' ? err.code : 1;
        if (code !== 0) {
          resolve(code);
          return;
        }
        reject(err);
        return;
      }
      resolve(0);
    });
  });
/* v8 ignore stop */

export interface RunPythonSelftestOptions {
  /** Test seam: replaces the real `execFile`-backed runner. */
  readonly _run?: SelftestRunner;
}

/**
 * Fail-fast boot gate: spawn the Python stage CLI once with `--selftest` and
 * reject if it cannot start or exits non-zero. This catches a broken Python
 * image (missing wheel, MediaPipe ImportError, wrong interpreter) at deploy
 * time instead of letting every claimed stage job fail one-by-one
 * (roadmap §2 node-python-failure MEDIUM). The interpreter is resolved the same
 * way real stages resolve it, so an override mismatch surfaces here too.
 */
export async function runPythonSelftest(
  env: Record<string, string | undefined> = process.env,
  opts: RunPythonSelftestOptions = {},
): Promise<void> {
  const run = opts._run ?? defaultSelftestRun;
  const entry = resolvePythonEntry(env);
  const args = [...entry.baseArgs, '--selftest'];
  let code: number;
  try {
    code = await run(entry.command, args);
  } catch (err: unknown) {
    const reason = err instanceof Error ? err.message : String(err);
    throw new Error(`python selftest failed to spawn (${entry.command}): ${reason}`);
  }
  if (code !== 0) {
    throw new Error(`python selftest failed: \`${entry.command} ${args.join(' ')}\` exited ${code}`);
  }
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
  // The asr-resume consumer (TRACK C): drives the GigaAM resume/fail state
  // machine the webhook-receiver enqueues onto the `asr-resume` queue.
  const resumeWorker = createResumeAsrWorker(connection, env);
  workers.push(resumeWorker);
  await Promise.all(workers.map((worker) => worker.waitUntilReady()));

  // Read-side projector: turns per-stage QueueEvents into one ledger status.
  const projector = createFlowProjector(db, connection);

  const shutdown = async (): Promise<void> => {
    // worker.close() drains in-flight jobs and closes BullMQ's own connections.
    await Promise.all(workers.map((worker) => worker.close()));
    await projector.close();
    await pool.end();
  };
  return { shutdown };
}

/** Backstop deadline for a graceful drain. Set under Railway's SIGKILL grace
 * (see DEPLOY.md `WORKER_SHUTDOWN_DEADLINE_MS`) so a hung `worker.close()`
 * force-exits cleanly instead of being SIGKILLed mid-write. Defaults to 30s. */
export const DEFAULT_SHUTDOWN_DEADLINE_MS = 30_000;

/** Resolve the shutdown deadline from env, falling back to the default. */
export function shutdownDeadlineMs(env: Record<string, string | undefined>): number {
  const raw = Number(env.WORKER_SHUTDOWN_DEADLINE_MS);
  return Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_SHUTDOWN_DEADLINE_MS;
}

/* v8 ignore start -- process entrypoint: real signals + I/O, exercised on deploy */
function installSignalHandlers(
  running: RunningWorkers,
  env: Record<string, string | undefined> = process.env,
): void {
  const deadlineMs = shutdownDeadlineMs(env);
  let draining = false;
  for (const signal of ['SIGTERM', 'SIGINT'] as const) {
    // `process.on` (not `once`): a SECOND signal during a slow drain means the
    // operator wants out now — force-exit and let BullMQ's stall recovery
    // re-claim the in-flight stage (idempotent → at worst a redundant render).
    process.on(signal, () => {
      if (draining) {
        process.stderr.write(`worker: ${signal} during shutdown — forcing exit\n`);
        process.exit(1);
      }
      draining = true;
      const deadline = setTimeout(() => {
        process.stderr.write(`worker: graceful shutdown exceeded ${deadlineMs}ms — forcing exit\n`);
        process.exit(1);
      }, deadlineMs);
      deadline.unref();
      running.shutdown().then(
        () => {
          clearTimeout(deadline);
          process.exit(0);
        },
        () => {
          clearTimeout(deadline);
          process.exit(1);
        },
      );
    });
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  // Selftest the Python sidecar BEFORE pulling jobs: a broken image fails the
  // deploy outright instead of silently retrying every stage to exhaustion.
  runPythonSelftest()
    .then(() => runWorkers())
    .then(installSignalHandlers, (err: unknown) => {
      process.stderr.write(`worker bootstrap failed: ${String(err)}\n`);
      process.exit(1);
    });
}
/* v8 ignore stop */
