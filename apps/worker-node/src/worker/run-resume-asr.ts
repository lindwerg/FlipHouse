import { spawn as nodeSpawn } from 'node:child_process';

import { stageResultSchema } from '@fliphouse/shared';
import type { StageResult } from '@fliphouse/shared';
import { Job, Queue, Worker } from 'bullmq';
import type { ConnectionOptions } from 'bullmq';

import { resolvePythonEntry } from '../python/resolve-entry.js';
import { RESULT_FRAME_PREFIX } from '../python/spawn.js';
import { buildR2ArtifactStore } from '../r2/build-r2-client.js';
import type { FinalizeInput, ResumableParkedJob, ResumeAsrDeps } from '../state/resume-asr.js';
import { resumeAsrProcessor } from '../state/resume-asr.js';

import { createStageWorker } from './make-worker.js';

/**
 * Real wiring for the `asr-resume` queue consumer (P2 step #1, TRACK C). Binds
 * the pure {@link resumeAsrProcessor} state machine to real effects: the parked
 * `gpu-asr` job is loaded via `Job.fromId`, the finalize CLI is a spawned
 * subprocess, and the `_FAILED` marker write goes to R2. Every line is real I/O,
 * so the whole module is coverage-ignored — the contract is unit-tested via the
 * injected seams in `state/resume-asr.test.ts`.
 */

/* v8 ignore start -- real subprocess + BullMQ + R2 construction; integration-only, never unit-tested */

/** The BullMQ queue the parked asr jobs live on (gpu-asr). */
const GPU_ASR_QUEUE = 'gpu-asr';

/** The queue the webhook-receiver enqueues resume/fail jobs onto. */
const ASR_RESUME_QUEUE = 'asr-resume';

/** Hard cap on the finalize subprocess so a hung interpreter cannot wedge a resume. */
const FINALIZE_TIMEOUT_MS = 120_000;

/** Spawn `python -m fliphouse_worker.cli asr-finalize`, feeding the input on stdin. */
function runAsrFinalize(input: FinalizeInput): Promise<StageResult> {
  const entry = resolvePythonEntry();
  return new Promise<StageResult>((resolve) => {
    const child = nodeSpawn(entry.command, [...entry.baseArgs, 'asr-finalize'], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    let stdout = '';
    let settled = false;
    const finish = (result: StageResult): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      finish({ ok: false, kind: 'retryable', code: 'FINALIZE_TIMEOUT', message: 'asr-finalize timed out' });
    }, FINALIZE_TIMEOUT_MS);
    timer.unref();

    child.stdout.on('data', (chunk: unknown) => {
      stdout += String(chunk);
    });
    child.on('error', (err: Error) => {
      finish({ ok: false, kind: 'retryable', code: 'SPAWN_FAILED', message: err.message });
    });
    child.on('close', (code: number | null) => {
      for (const line of stdout.split('\n').reverse()) {
        if (!line.startsWith(RESULT_FRAME_PREFIX)) continue;
        try {
          const parsed = stageResultSchema.safeParse(JSON.parse(line.slice(RESULT_FRAME_PREFIX.length)));
          finish(parsed.success ? parsed.data : { ok: false, kind: 'retryable', code: 'BAD_RESULT', message: 'bad envelope' });
        } catch {
          finish({ ok: false, kind: 'retryable', code: 'BAD_RESULT', message: 'envelope not JSON' });
        }
        return;
      }
      finish({ ok: false, kind: 'retryable', code: 'NO_RESULT', message: `asr-finalize exit ${String(code)}` });
    });

    child.stdin.write(JSON.stringify(input));
    child.stdin.end();
  });
}

/** Build the real {@link ResumeAsrDeps} bound to the gpu-asr queue + R2. */
export function buildResumeAsrDeps(
  connection: ConnectionOptions,
  env: Record<string, string | undefined> = process.env,
): ResumeAsrDeps {
  const r2 = buildR2ArtifactStore(env);
  const gpuAsrQueue = new Queue(GPU_ASR_QUEUE, { connection });

  const loadJob = async (jobId: string): Promise<ResumableParkedJob | undefined> => {
    const job = await Job.fromId(gpuAsrQueue, jobId);
    if (!job) return undefined;
    const outputPrefix = String((job.data as { outputPrefix?: unknown }).outputPrefix ?? '');
    return {
      changeDelay: (delay: number) => job.changeDelay(delay),
      outputPrefix,
    };
  };

  return {
    loadJob,
    runFinalize: runAsrFinalize,
    writeFailedMarker: (outputPrefix, error) => r2.writeFailedMarker(outputPrefix, error),
  };
}

/** Create + start the `asr-resume` BullMQ Worker driving the resume/fail machine. */
export function createResumeAsrWorker(
  connection: ConnectionOptions,
  env: Record<string, string | undefined> = process.env,
): Worker {
  const deps = buildResumeAsrDeps(connection, env);
  // MUST use the shared stage-worker config (LOCK_DURATION_MS = 15 min, not the
  // BullMQ default 30 s): the resume processor spawns the asr-finalize Python CLI
  // (cold interpreter + R2 download + normalize + upload), which under load runs
  // well past 30 s. A short lock made the job STALL ("Missing key … moveToFinished"),
  // BullMQ re-ran it, and each re-run fired changeDelay(0) again — re-waking the
  // parked asr lane before `_COMPLETE` was durable, so asr re-submitted to the GPU
  // in a tight loop. The 15 min lock matches every other stage and ends the loop.
  return createStageWorker(
    ASR_RESUME_QUEUE,
    connection,
    (job) => resumeAsrProcessor({ name: job.name, data: job.data }, deps),
    4,
  );
}
/* v8 ignore stop */
