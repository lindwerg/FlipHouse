/**
 * GPU submit-and-park seam (spec §2.4, §6.10), realized for the real GigaAM-v3
 * ASR lane. A GPU stage cannot block a worker slot while a long external
 * prediction runs, so the park path is:
 *
 *   1. submit to the GPU → mint a `request_id`,
 *   2. SET `park:<request_id>` to the JSON value `{ jobId, contentHash,
 *      outputPrefix }` (TTL-guarded; an orphan self-evicts after a day),
 *   3. register `<request_id>` in a Redis index set so the lost-callback sweep
 *      can enumerate in-flight parks,
 *   4. `job.moveToDelayed(deadlineMs, token)` — park the job in BullMQ's
 *      `delayed` state until the webhook (or sweep) promotes it.
 *
 * The single AUTHORITATIVE atomic `GETDEL park:<id>` lives in the
 * webhook-receiver (TRACK B); this seam only SETs the key. There is NO
 * getdel/resume on this side — promotion happens via `changeDelay(0)` driven by
 * the `asr-resume` consumer (see `worker/resume-asr.ts`).
 *
 * `decideParkMode` gates inline (flag off / CPU) vs. park (flag on). All
 * decision and mapping logic is pure and injectable; the only real ioredis I/O
 * lives in the v8-ignored {@link createRedisParker} factory.
 */
import type { Redis } from 'ioredis';
import { z } from 'zod';

/** TTL on a park mapping; an orphaned key (provider never calls back) self-evicts after a day. */
export const PARK_KEY_TTL_SEC = 86_400;

/** Max wall-clock a parked ASR job waits before its delay deadline elapses (15 min). */
export const MAX_PARK_MS = 15 * 60 * 1000;

/**
 * Redis SORTED-SET tracking every in-flight parked request id, SCORED by its park
 * deadline (`now + MAX_PARK_MS`). The lost-callback sweep reads members whose
 * deadline has already passed (`ZRANGEBYSCORE -inf now`), so a stuck park is
 * enumerable by age without an extra per-request timestamp key.
 */
export const PARK_INDEX_KEY = 'park:index';

/** The narrow ioredis surface the park seam needs (injectable, so the pure logic stays testable). */
export interface RedisParker {
  set(key: string, value: string, ex: 'EX', ttlSec: number): Promise<'OK' | null>;
  zadd(key: string, score: number, member: string): Promise<number | string>;
}

/** The slice of a BullMQ {@link Job} the park seam touches (injectable). */
export interface ParkableJob {
  readonly id?: string;
  moveToDelayed(timestamp: number, token?: string): Promise<void>;
}

/** Monotonic-ish wall clock, injected so the delay deadline is deterministic in tests. */
export type NowMsFn = () => number;

/** Outcome of {@link decideParkMode}: run the stage inline, or park it on an external request id. */
export type ParkDecision =
  | { readonly mode: 'inline' }
  | { readonly mode: 'park'; readonly providerRequestId: string };

/** Boundary input for {@link decideParkMode}: the GPU gate flag plus, when on, the provider request id. */
const parkConfigSchema = z.discriminatedUnion('gpuParkEnabled', [
  z.object({ gpuParkEnabled: z.literal(false) }),
  z.object({ gpuParkEnabled: z.literal(true), providerRequestId: z.string().min(1) }),
]);

export type ParkConfig = z.input<typeof parkConfigSchema>;

/** The value stored at `park:<request_id>` — the webhook-receiver decodes this exact shape. */
export const parkValueSchema = z.object({
  jobId: z.string().min(1),
  contentHash: z.string().min(1),
  outputPrefix: z.string().min(1),
});

export type ParkValue = z.infer<typeof parkValueSchema>;

/** The Redis key that maps an external provider request back to its parked BullMQ job. */
export function parkKeyFor(providerRequestId: string): string {
  return `park:${providerRequestId}`;
}

/**
 * Decide whether a stage runs inline (flag off → CPU/inline path) or parks on an
 * external provider request. Validates at the boundary: a park without a
 * non-empty `providerRequestId` is rejected by the discriminated-union schema.
 */
export function decideParkMode(config: ParkConfig): ParkDecision {
  const parsed = parkConfigSchema.parse(config);
  if (!parsed.gpuParkEnabled) return { mode: 'inline' };
  return { mode: 'park', providerRequestId: parsed.providerRequestId };
}

export interface ParkJobArgs {
  readonly providerRequestId: string;
  readonly job: ParkableJob;
  readonly token: string;
  readonly redis: RedisParker;
  readonly contentHash: string;
  readonly outputPrefix: string;
  readonly nowMs: NowMsFn;
}

/**
 * Park a job on an external GPU request. Persists the JSON `park:<id> → {jobId,
 * contentHash, outputPrefix}` mapping (TTL-guarded), indexes the request id for
 * the sweep, then hands the worker slot back to BullMQ via `moveToDelayed` with a
 * `now + MAX_PARK_MS` deadline. Resume is `changeDelay(0)` driven externally —
 * the deadline is only the lost-callback backstop, never the happy path.
 */
export async function parkJob(args: ParkJobArgs): Promise<{ parked: true; jobId: string }> {
  const { providerRequestId, job, token, redis, contentHash, outputPrefix, nowMs } = args;
  if (!job.id) throw new Error('park: job.id missing — cannot store park mapping');

  const deadlineMs = nowMs() + MAX_PARK_MS;
  const value: ParkValue = { jobId: job.id, contentHash, outputPrefix };
  await redis.set(parkKeyFor(providerRequestId), JSON.stringify(value), 'EX', PARK_KEY_TTL_SEC);
  await redis.zadd(PARK_INDEX_KEY, deadlineMs, providerRequestId);
  await job.moveToDelayed(deadlineMs, token);
  return { parked: true, jobId: job.id };
}

/* v8 ignore start -- real ioredis calls; exercised in integration, not unit tests */
export function createRedisParker(client: Redis): RedisParker {
  return {
    set: (key, value, ex, ttlSec) => client.set(key, value, ex, ttlSec),
    zadd: (key, score, member) => client.zadd(key, score, member),
  };
}
/* v8 ignore stop */
