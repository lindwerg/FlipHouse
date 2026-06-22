import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3';
import type { S3ClientConfig } from '@aws-sdk/client-s3';
import { Queue } from 'bullmq';
import type { ConnectionOptions } from 'bullmq';
import { Redis } from 'ioredis';

import type { AsrPayload } from './gpu-callback-types.js';
import { parkKeyFor, parkValueSchema, QUEUE_ASR_RESUME } from './handle-callback.js';
import type { AsrResumeJob, CallbackDeps, ParkValue } from './handle-callback.js';
import { verifyHmac } from './verify-hmac.js';

/**
 * Production wiring for the GigaAM callback handler (P2 step #1, TRACK B). Binds
 * the pure {@link handleCallback} flow to real effects: the SINGLE atomic dedup is
 * an ioredis `GETDEL park:<request_id>` here (and NOWHERE else); the raw payload
 * goes to R2 via a `PutObjectCommand`; the resume/fail signal goes to the
 * `asr-resume` BullMQ queue. Every line is real I/O, so the whole module is
 * coverage-ignored — the contract it serves is unit-tested via the injected seams.
 */

/* v8 ignore start -- real ioredis + S3 + BullMQ construction; integration-only, never unit-tested */

/** Job name used when failing a parked job through the `asr-resume` queue. */
export const ASR_FAIL_JOB_NAME = 'asr-fail';

/** Job name used for a normal resume on the `asr-resume` queue. */
export const ASR_RESUME_JOB_NAME = 'asr-resume';

/** Failure-variant payload pushed to `asr-resume`; worker-node fails the parked job. */
export interface AsrFailJob {
  readonly jobId: string;
  readonly error: string;
}

/** R2 connection settings, validated out of the process environment. */
export interface R2Settings {
  readonly accountId: string;
  readonly bucket: string;
  readonly accessKeyId: string;
  readonly secretAccessKey: string;
}

const REQUIRED_R2_VARS = [
  'R2_ACCOUNT_ID',
  'R2_BUCKET',
  'R2_ACCESS_KEY_ID',
  'R2_SECRET_ACCESS_KEY',
] as const;

/** Validate R2 env vars into typed settings, failing fast on the first missing one. */
export function resolveR2Env(env: Record<string, string | undefined>): R2Settings {
  for (const name of REQUIRED_R2_VARS) {
    if (!env[name]) {
      throw new Error(`missing required env var: ${name}`);
    }
  }
  return {
    accountId: env.R2_ACCOUNT_ID as string,
    bucket: env.R2_BUCKET as string,
    accessKeyId: env.R2_ACCESS_KEY_ID as string,
    secretAccessKey: env.R2_SECRET_ACCESS_KEY as string,
  };
}

/**
 * S3 client config for Cloudflare R2. `WHEN_REQUIRED` on both checksum knobs is
 * mandatory: aws-sdk-js v3's default emits a CRC32 streaming trailer R2 rejects
 * with `SignatureDoesNotMatch`. Mirrors the worker-node artifact-store config.
 */
export function buildS3Config(settings: R2Settings): S3ClientConfig {
  return {
    region: 'auto',
    endpoint: `https://${settings.accountId}.r2.cloudflarestorage.com`,
    credentials: {
      accessKeyId: settings.accessKeyId,
      secretAccessKey: settings.secretAccessKey,
    },
    requestChecksumCalculation: 'WHEN_REQUIRED',
    responseChecksumValidation: 'WHEN_REQUIRED',
  };
}

/** Parse a `redis://`/`rediss://` URL into BullMQ {@link ConnectionOptions}. */
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

/**
 * Decode a raw `park:<request_id>` Redis value into a {@link ParkValue}. The
 * worker-node park seam stores JSON `{ jobId, contentHash, outputPrefix }`; a bare
 * legacy jobId string is rejected (it cannot reconstruct contentHash/outputPrefix).
 */
function decodeParkValue(raw: string): ParkValue {
  return parkValueSchema.parse(JSON.parse(raw));
}

export interface RealDepsConfig {
  readonly secret: string;
  readonly redisUrl: string;
  readonly r2Env: Record<string, string | undefined>;
}

/**
 * Construct the production {@link CallbackDeps}. The ioredis client, S3 client, and
 * BullMQ queue are each built ONCE (they pool internally) and closed via the
 * returned {@link CloseableDeps.close}.
 */
export interface CloseableDeps {
  readonly deps: CallbackDeps;
  close(): Promise<void>;
}

export function buildRealDeps(config: RealDepsConfig): CloseableDeps {
  // ioredis accepts the connection string directly; building from a BullMQ
  // ConnectionOptions object trips the duplicate-ioredis-version type clash.
  const redis = new Redis(config.redisUrl, { maxRetriesPerRequest: null });
  const settings = resolveR2Env(config.r2Env);
  const s3 = new S3Client(buildS3Config(settings));
  const connection = redisConnectionFromUrl(config.redisUrl);
  const resumeQueue = new Queue(QUEUE_ASR_RESUME, { connection });

  const claimPrediction = async (requestId: string): Promise<ParkValue | null> => {
    const raw = await redis.getdel(parkKeyFor(requestId));
    if (raw === null) {
      return null;
    }
    return decodeParkValue(raw);
  };

  const writeRawPayload = async (rawPayloadKey: string, payload: AsrPayload): Promise<void> => {
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
    await resumeQueue.add(ASR_RESUME_JOB_NAME, job, { jobId: `resume:${job.requestId}` });
  };

  const failParkedJob = async (jobId: string, error: string): Promise<void> => {
    const failJob: AsrFailJob = { jobId, error };
    await resumeQueue.add(ASR_FAIL_JOB_NAME, failJob, { jobId: `fail:${jobId}` });
  };

  const deps: CallbackDeps = {
    verifyHmacFn: (rawBody, signatureHeader, timestampHeader) =>
      verifyHmac({ secret: config.secret, rawBody, signatureHeader, timestampHeader }),
    claimPrediction,
    writeRawPayload,
    enqueueResume,
    failParkedJob,
  };

  const close = async (): Promise<void> => {
    await resumeQueue.close();
    await s3.destroy();
    redis.disconnect();
  };

  return { deps, close };
}

/* v8 ignore stop */
