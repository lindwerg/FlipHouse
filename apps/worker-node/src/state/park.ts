/**
 * GPU submit-and-park seam (spec §2.4, §6.10). A GPU stage cannot block a
 * worker slot while a long external prediction (Replicate) runs, so the future
 * GPU path is: submit to the provider → write `park:<providerRequestId> → jobId`
 * into Redis → `job.moveToWaitingChildren(token)`, freeing the worker. The
 * provider's webhook later resumes the job via an **atomic** `GETDEL` (the
 * compare-and-delete dedup that closes the idempotency-race against duplicate
 * or late callbacks).
 *
 * In P2 every GPU stage runs inline (CPU stub): {@link decideParkMode} returns
 * `{ mode: 'inline' }` and {@link parkJob} short-circuits without any Redis I/O.
 * The contract is already shaped for the GPU path so flipping one stage handler
 * needs zero changes to the DAG topology. The only real Redis I/O lives in the
 * v8-ignored {@link createRedisParker} factory; all decision and mapping logic
 * is pure and injectable so it is fully unit-tested.
 */
import type { Redis } from 'ioredis';
import { z } from 'zod';

/** TTL on a park mapping; an orphaned key (provider never calls back) self-evicts after a day. */
export const PARK_KEY_TTL_SEC = 86_400;

/** The narrow ioredis surface park/resume need (injectable, so the pure logic stays testable). */
export interface RedisParker {
  set(key: string, value: string, ex: 'EX', ttlSec: number): Promise<'OK' | null>;
  getdel(key: string): Promise<string | null>;
}

/** The slice of a BullMQ {@link Job} the park seam touches (injectable). */
export interface ParkableJob {
  readonly id: string | undefined;
  moveToWaitingChildren(token: string): Promise<boolean>;
}

/** Resumes a parked job's state machine once the provider's result arrives. */
export type ResumeJobFn = (jobId: string, result: unknown) => Promise<void>;

/** Outcome of {@link decideParkMode}: run the stage inline, or park it on an external request id. */
export type ParkDecision = { readonly mode: 'inline' } | { readonly mode: 'park'; readonly providerRequestId: string };

/** Boundary input for {@link decideParkMode}: the GPU gate flag plus, when on, the provider request id. */
const parkConfigSchema = z.discriminatedUnion('gpuParkEnabled', [
  z.object({ gpuParkEnabled: z.literal(false) }),
  z.object({ gpuParkEnabled: z.literal(true), providerRequestId: z.string().min(1) }),
]);

export type ParkConfig = z.input<typeof parkConfigSchema>;

/** The Redis key that maps an external provider request back to its parked BullMQ job. */
export function parkKeyFor(providerRequestId: string): string {
  return `park:${providerRequestId}`;
}

/**
 * Decide whether a stage runs inline (P2 CPU stub) or parks on an external
 * provider request. Validates at the boundary: a park without a non-empty
 * `providerRequestId` is rejected by the discriminated-union schema.
 */
export function decideParkMode(config: ParkConfig): ParkDecision {
  const parsed = parkConfigSchema.parse(config);
  if (!parsed.gpuParkEnabled) return { mode: 'inline' };
  return { mode: 'park', providerRequestId: parsed.providerRequestId };
}

export interface ParkJobArgs {
  readonly decision: ParkDecision;
  readonly job: ParkableJob;
  readonly token: string;
  readonly redis: RedisParker;
}

/**
 * Apply a {@link ParkDecision}. Inline decisions return immediately with no
 * Redis I/O (the P2 path). Park decisions persist the `park:<id> → jobId`
 * mapping (TTL-guarded so an orphan self-evicts) before handing the slot back
 * to BullMQ via `moveToWaitingChildren` — the worker never blocks on the GPU.
 */
export async function parkJob(args: ParkJobArgs): Promise<{ parked: boolean }> {
  const { decision, job, token, redis } = args;
  if (decision.mode === 'inline') return { parked: false };

  if (!job.id) throw new Error('park: job.id missing — cannot store park mapping');
  await redis.set(parkKeyFor(decision.providerRequestId), job.id, 'EX', PARK_KEY_TTL_SEC);
  await job.moveToWaitingChildren(token);
  return { parked: true };
}

export interface ResumeParkedJobArgs {
  readonly providerRequestId: string;
  readonly result: unknown;
  readonly redis: RedisParker;
  readonly resumeJob: ResumeJobFn;
}

/**
 * Resume a parked job from a provider webhook. The `GETDEL` is the atomic
 * compare-and-delete that dedups duplicate/late callbacks: only the caller that
 * actually reads the key wins; everyone else gets `null` and a `resumed:false`
 * no-op. A failure inside `resumeJob` is intentionally NOT swallowed so the
 * webhook layer can surface it.
 */
export async function resumeParkedJob(
  args: ResumeParkedJobArgs,
): Promise<{ jobId: string | null; resumed: boolean }> {
  const { providerRequestId, result, redis, resumeJob } = args;
  const jobId = await redis.getdel(parkKeyFor(providerRequestId));
  if (!jobId) return { jobId: null, resumed: false };
  await resumeJob(jobId, result);
  return { jobId, resumed: true };
}

/* v8 ignore start -- real ioredis calls; exercised in integration, not unit tests */
export function createRedisParker(client: Redis): RedisParker {
  return {
    set: (key, value, ex, ttlSec) => client.set(key, value, ex, ttlSec),
    getdel: (key) => client.getdel(key),
  };
}
/* v8 ignore stop */
