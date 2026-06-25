import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3';
import { Queue } from 'bullmq';
import type { ConnectionOptions } from 'bullmq';
import { Redis } from 'ioredis';
import { z } from 'zod';

import { buildS3Config } from '../r2/artifact-store.js';
import { resolveR2Env } from '../r2/build-r2-client.js';
import { probeGigaamHealth, runParkSweep } from '../state/park-sweep.js';
import type {
  AsrFailJob,
  AsrResumeJob,
  GpuStatus,
  HealthProbeResult,
  ParkSweepDeps,
  ParkSweepSummary,
  ParkValue,
} from '../state/park-sweep.js';
import { PARK_INDEX_KEY, parkKeyFor, parkValueSchema } from '../state/park.js';

/**
 * Real wiring for the lost-callback park sweep (P2 step #1, TRACK C). Binds the
 * pure {@link runParkSweep} to real effects: the index is a Redis sorted set; the
 * claim is an atomic `GETDEL park:<id>`; the status poll hits the GPU
 * `${endpoint}/status/<id>`; raw payloads go to R2 and resume/fail signals to the
 * `asr-resume` queue. Coverage-ignored — the logic is unit-tested via the seams.
 */

/* v8 ignore start -- real ioredis + S3 + BullMQ + fetch construction; integration-only */

const ASR_RESUME_QUEUE = 'asr-resume';
const ASR_RESUME_JOB = 'asr-resume';
const ASR_FAIL_JOB = 'asr-fail';

/** Redis hash tracking per-request sweep re-arm cycles. */
const PARK_CYCLES_KEY = 'park:cycles';

/** The GPU `/status/<id>` response: a terminal result or a still-processing state. */
const statusResponseSchema = z.union([
  z.object({ state: z.literal('succeeded'), payload: z.unknown() }),
  z.object({ state: z.literal('failed'), error: z.string() }),
  z.object({ state: z.literal('processing') }),
]);

function statusUrl(endpoint: string, requestId: string): string {
  return `${endpoint.replace(/\/$/, '')}/status/${requestId}`;
}

export interface ParkSweepConfig {
  readonly connection: ConnectionOptions;
  readonly redisUrl: string;
  readonly gigaamEndpoint: string;
  readonly r2Env: Record<string, string | undefined>;
}

export interface CloseableParkSweep {
  runOnce(): Promise<ParkSweepSummary>;
  /**
   * Probe the GPU `/health` endpoint (TRANS-4). The sweep cron calls this each pass
   * and alerts on `!healthy`, so a Modal outage / expired-secret cold-start failure
   * is detected immediately instead of after ~20min of jobs silently park-failing.
   */
  probeHealthOnce(): Promise<HealthProbeResult>;
  close(): Promise<void>;
}

/** GET `${endpoint}/health` and report the HTTP status (or reject on transport fault). */
function healthUrl(endpoint: string): string {
  return `${endpoint.replace(/\/$/, '')}/health`;
}

/** Build the real park-sweep deps + a `runOnce` entry the cron/sweep can call. */
export function buildParkSweep(config: ParkSweepConfig): CloseableParkSweep {
  const redis = new Redis(config.redisUrl, { maxRetriesPerRequest: null });
  const settings = resolveR2Env(config.r2Env);
  const s3 = new S3Client(buildS3Config(settings));
  const queue = new Queue(ASR_RESUME_QUEUE, { connection: config.connection });

  const listExpired = (): Promise<string[]> =>
    redis.zrangebyscore(PARK_INDEX_KEY, '-inf', Date.now());

  const pollStatus = async (requestId: string): Promise<GpuStatus> => {
    const res = await fetch(statusUrl(config.gigaamEndpoint, requestId));
    if (!res.ok) return { state: 'processing' };
    return statusResponseSchema.parse(await res.json()) as GpuStatus;
  };

  const claim = async (requestId: string): Promise<ParkValue | null> => {
    const raw = await redis.getdel(parkKeyFor(requestId));
    if (raw === null) return null;
    await redis.zrem(PARK_INDEX_KEY, requestId);
    await redis.hdel(PARK_CYCLES_KEY, requestId);
    return parkValueSchema.parse(JSON.parse(raw));
  };

  const bumpDeadline = async (requestId: string, newDeadlineMs: number): Promise<number> => {
    await redis.zadd(PARK_INDEX_KEY, newDeadlineMs, requestId);
    return redis.hincrby(PARK_CYCLES_KEY, requestId, 1);
  };

  const writeRaw = async (rawPayloadKey: string, payload: unknown): Promise<void> => {
    await s3.send(
      new PutObjectCommand({
        Bucket: settings.bucket,
        Key: rawPayloadKey,
        Body: JSON.stringify(payload),
        ContentType: 'application/json',
      }),
    );
  };

  const enqueueResume = async (job: AsrResumeJob): Promise<void> => {
    // BullMQ rejects a custom jobId containing ':' — use '-' (ids are colon-free).
    await queue.add(ASR_RESUME_JOB, job, { jobId: `resume-${job.requestId}` });
  };

  const enqueueFail = async (job: AsrFailJob): Promise<void> => {
    await queue.add(ASR_FAIL_JOB, job, { jobId: `fail-${job.jobId}` });
  };

  const deps: ParkSweepDeps = {
    nowMs: Date.now,
    listExpired,
    pollStatus,
    claim,
    bumpDeadline,
    writeRaw,
    enqueueResume,
    enqueueFail,
  };

  return {
    runOnce: () => runParkSweep(deps),
    probeHealthOnce: () =>
      probeGigaamHealth({
        fetchHealth: async () => {
          const res = await fetch(healthUrl(config.gigaamEndpoint));
          return { status: res.status };
        },
      }),
    close: async () => {
      await queue.close();
      s3.destroy();
      redis.disconnect();
    },
  };
}
/* v8 ignore stop */
