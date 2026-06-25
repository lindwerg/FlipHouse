/**
 * BullMQ QueueEvents → flow progress → Postgres projector (docs §5/§6.9).
 *
 * BullMQ has no whole-flow status: each Worker only knows about its own job. The
 * dashboard, however, needs one forward-moving status (and a 0–100 bar) per
 * upload. This module is the read-side projector: it subscribes to per-queue
 * `completed`/`failed` events, accumulates the set of completed stages per
 * content-hash, derives the aggregate status via {@link computeFlowProgress},
 * and writes it to the ledger through the guarded `setStatus`.
 *
 * INVARIANTS this module holds:
 *  - Forward-only: status writes go through `setStatus(validFrom)`, so a
 *    re-delivered/out-of-order event is silently rejected, never regresses.
 *  - Idempotent: the completed-set is a `Set<Stage>` (duplicate completions are
 *    no-ops) and `computeFlowProgress` de-dupes its input.
 *  - No double-finish: the `publish` completion is owned by `publishUpload`
 *    (which calls `finishUpload` → status='done'); the projector must NOT also
 *    write 'done' for it, to avoid a competing UPDATE.
 *
 * The pure projection (jobId parsing, stage→status mapping, progress/update
 * derivation, idempotent accumulation) lives in exported functions with full
 * unit coverage. The QueueEvents I/O wiring (constructor, `.on()`,
 * `.waitUntilReady()`-style readiness, `.close()`, the real
 * `setStatus`/`recordFailure` calls) is isolated behind a v8-ignore block,
 * mirroring `flow-producer.ts` and `spawn.ts`; it is exercised by integration
 * tests, not unit tests.
 *
 * NOTE: `buildProgressUpdate` returns a numeric `progress` for logging/future
 * use, but `upload_ledger` has no progress column today — the I/O layer
 * persists only `status`. Adding a column is a separate migration in apps/web.
 */

import { recordFailure, setStatus, type Db, type UploadStatus } from '@fliphouse/db';
import { isStage, isValidContentHash, QUEUE_NAMES, STAGES } from '@fliphouse/shared';
import type { Stage } from '@fliphouse/shared';
import { QueueEvents } from 'bullmq';
import type { ConnectionOptions } from 'bullmq';

import { log } from '../log.js';
import { UPLOAD_STATUSES } from '../state/transitions.js';

import { computeFlowProgress } from './flow-progress.js';

/** Stage → ledger status the projector writes when that stage completes. */
export const STAGE_TO_STATUS: Readonly<Record<Stage, UploadStatus>> = {
  transcode: 'transcoding',
  asr: 'transcribing',
  score: 'scoring',
  reframe: 'reframing',
  caption: 'captioning',
  // No 'bannering' status exists; the banner render maps onto 'rendering'.
  banner: 'rendering',
  publish: 'publishing',
};

/** Map a stage to the ledger status reached once that stage has completed. */
export function stageToStatus(stage: Stage): UploadStatus {
  return STAGE_TO_STATUS[stage];
}

/**
 * Recover the {@link Stage} a BullMQ jobId belongs to, or `undefined` for an id
 * the projector should ignore. Stage jobs are `${stage}-${hash}`; the flow ROOT
 * is `flow-${hash}` (the publish node — see `content-hash.ts`). Both halves are
 * validated so an arbitrary/foreign jobId never maps to a stage by accident.
 */
export function stageNameFromJobId(jobId: string): Stage | undefined {
  const dash = jobId.indexOf('-');
  if (dash === -1) return undefined;
  const prefix = jobId.slice(0, dash);
  const suffix = jobId.slice(dash + 1);
  if (!isValidContentHash(suffix)) return undefined;
  if (isStage(prefix)) return prefix;
  if (prefix === 'flow') return 'publish';
  return undefined;
}

/**
 * Derive the aggregate `{ status, progress }` from the set of completed stages.
 * Empty set → the `queued` baseline. Otherwise the status follows the LAST
 * completed stage in DAG order (`publish` completing means the whole flow is
 * `done`); progress is the weighted {@link computeFlowProgress}.
 */
export function buildProgressUpdate(
  completedStages: ReadonlySet<Stage>,
): { status: UploadStatus; progress: number } {
  if (completedStages.size === 0) {
    return { status: 'queued', progress: 0 };
  }
  // `last` is defined: the set is non-empty and only holds valid stages.
  const last = STAGES.filter((stage) => completedStages.has(stage)).at(-1) as Stage;
  const status: UploadStatus = last === 'publish' ? 'done' : stageToStatus(last);
  return { status, progress: computeFlowProgress([...completedStages]) };
}

/**
 * Idempotently record `stage` as completed in `completed` and return the
 * resulting aggregate update. Mutating the caller's set is intentional: the I/O
 * layer keeps one accumulator per content-hash. `Set.add` makes a re-delivered
 * completion a no-op, so the derived update is stable across duplicates.
 */
export function applyStageCompleted(
  stage: Stage,
  completed: Set<Stage>,
): { update: { status: UploadStatus; progress: number } } {
  completed.add(stage);
  return { update: buildProgressUpdate(completed) };
}

/** Shape a stage failure into the durable `recordFailure` payload. */
export function buildFailureRecord(
  stage: string,
  reason: string,
): { stage: string; code: string; message: string } {
  return { stage, code: 'STAGE_FAILED', message: reason };
}

/** Running projector handle the bootstrap wires into graceful shutdown. */
export interface FlowProjector {
  close(): Promise<void>;
}

/* v8 ignore start -- QueueEvents I/O; exercised by integration tests, not unit */
/** Non-terminal statuses a job may legally fail out of. */
const NON_TERMINAL_STATUSES: readonly UploadStatus[] = UPLOAD_STATUSES.filter(
  (status) => status !== 'done' && status !== 'failed' && status !== 'duplicate',
);

/** Statuses preceding `to` in the forward order — the legal `validFrom` set. */
function statusesBefore(to: UploadStatus): readonly UploadStatus[] {
  const index = UPLOAD_STATUSES.indexOf(to);
  return UPLOAD_STATUSES.slice(0, index).filter(
    (status) => status !== 'failed' && status !== 'duplicate',
  );
}

/** Per-hash completed-stage accumulator (resets on worker restart; see risks). */
function completedSetFor(byHash: Map<string, Set<Stage>>, hash: string): Set<Stage> {
  const existing = byHash.get(hash);
  if (existing) return existing;
  const fresh = new Set<Stage>();
  byHash.set(hash, fresh);
  return fresh;
}

/** Recover the content-hash half of a `${prefix}-${hash}` jobId. */
function hashFromJobId(jobId: string): string {
  return jobId.slice(jobId.indexOf('-') + 1);
}

/**
 * Subscribe to every queue's `completed`/`failed` stream and project flow
 * progress into the ledger. One QueueEvents per queue name (a queue carries
 * several stages — e.g. `cpu` runs reframe/caption/banner); the owning stage is
 * recovered from each event's jobId. The publish completion is intentionally
 * NOT written here — `publishUpload` already finalized status='done'.
 */
export function createFlowProjector(db: Db, connection: ConnectionOptions): FlowProjector {
  const completedByHash = new Map<string, Set<Stage>>();
  const events = QUEUE_NAMES.map((name) => new QueueEvents(name, { connection }));

  const onCompleted = async ({ jobId }: { jobId: string }): Promise<void> => {
    const stage = stageNameFromJobId(jobId);
    if (stage === undefined) return;
    const hash = hashFromJobId(jobId);
    const { update } = applyStageCompleted(stage, completedSetFor(completedByHash, hash));
    // publish's terminal 'done' is owned by publishUpload/finishUpload.
    if (stage === 'publish') return;
    await setStatus(db, hash, update.status, statusesBefore(update.status));
  };

  const onFailed = async ({
    jobId,
    failedReason,
  }: {
    jobId: string;
    failedReason: string;
  }): Promise<void> => {
    const stage = stageNameFromJobId(jobId);
    if (stage === undefined) return;
    const hash = hashFromJobId(jobId);
    const record = buildFailureRecord(stage, failedReason);
    await recordFailure(db, hash, record.stage, record.code, record.message);
    await setStatus(db, hash, 'failed', NON_TERMINAL_STATUSES);
  };

  // A projected write (setStatus/recordFailure) can reject on a transient pg
  // blip. These handlers are fired-and-forgotten by QueueEvents, so an
  // unhandled rejection would crash PID 1 mid-flight — fatal for the worker.
  // Swallow-with-(structured)-log instead: the ledger write is best-effort
  // (forward-only, non-authoritative). A swallowed write is RECOVERED by the
  // worker-side status reconciler (`reconcileStuckStatuses`, scheduled in
  // run-workers beside the park-sweep), which backfills a terminal status onto
  // any upload left stranded in a non-terminal status — so losing one projection
  // never strands the user on a perpetual spinner and never takes down the consumer.
  const onError = (op: string, jobId: string) => (err: unknown): void => {
    log.error({ op, jobId, err: String(err) }, 'projector handler failed');
  };
  for (const qe of events) {
    qe.on('completed', (args) => void onCompleted(args).catch(onError('completed', args.jobId)));
    qe.on('failed', (args) => void onFailed(args).catch(onError('failed', args.jobId)));
  }

  return {
    close: async (): Promise<void> => {
      await Promise.all(events.map((qe) => qe.close()));
    },
  };
}
/* v8 ignore stop */
