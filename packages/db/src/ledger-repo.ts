import { and, eq, inArray, isNull, lt, notInArray, sql } from 'drizzle-orm';

import type { Db } from './client.js';
import { clips, flowFailures, uploadLedger, uploadStatusEnum } from './schema.js';

export type UploadStatus = (typeof uploadStatusEnum.enumValues)[number];
export type UploadRow = typeof uploadLedger.$inferSelect;

const TERMINAL_STATUSES: readonly UploadStatus[] = ['done', 'failed', 'duplicate'];

export interface ClaimInput {
  readonly contentHash: string;
  readonly ownerId: string;
  readonly firstUploadId: string;
  readonly tusObjectKey: string;
  readonly flowJobId?: string;
  readonly sizeBytes?: number;
}

export interface ClaimResult {
  readonly claimed: boolean;
  readonly existing: UploadRow | undefined;
}

/**
 * Atomically claim an upload by content-hash. The first caller inserts and wins
 * (`claimed: true`); a losing concurrent caller / re-delivered tusd hook gets
 * `claimed: false` plus the existing row. This ON CONFLICT row — NOT the BullMQ
 * jobId — is the durable idempotency authority.
 */
export async function claimUpload(db: Db, input: ClaimInput): Promise<ClaimResult> {
  const inserted = await db
    .insert(uploadLedger)
    .values(input)
    .onConflictDoNothing({ target: uploadLedger.contentHash })
    .returning();
  if (inserted.length > 0) {
    return { claimed: true, existing: undefined };
  }
  const rows = await db
    .select()
    .from(uploadLedger)
    .where(eq(uploadLedger.contentHash, input.contentHash));
  return { claimed: false, existing: rows[0] };
}

/**
 * Guarded forward-only status write: succeeds only if the row is currently in
 * one of `validFrom`, rejecting out-of-order writes from re-delivered jobs.
 * Returns whether a row transitioned.
 */
export async function setStatus(
  db: Db,
  contentHash: string,
  to: UploadStatus,
  validFrom: readonly UploadStatus[],
): Promise<boolean> {
  const updated = await db
    .update(uploadLedger)
    .set({ status: to })
    .where(and(eq(uploadLedger.contentHash, contentHash), inArray(uploadLedger.status, [...validFrom])))
    .returning({ contentHash: uploadLedger.contentHash });
  return updated.length > 0;
}

export type ClipInput = Omit<typeof clips.$inferInsert, 'id' | 'contentHash' | 'createdAt'>;

/** Replace an upload's clip rows atomically — idempotent under re-publish. */
export async function upsertClips(db: Db, contentHash: string, rows: readonly ClipInput[]): Promise<void> {
  await db.transaction(async (tx) => {
    await tx.delete(clips).where(eq(clips.contentHash, contentHash));
    if (rows.length > 0) {
      await tx.insert(clips).values(rows.map((row) => ({ ...row, contentHash })));
    }
  });
}

export interface FinishInput {
  readonly resultUrl: string;
  readonly manifestUrl: string;
  readonly engine: string;
  readonly durationSec?: number;
}

/** Mark an upload done and record its result URLs (terminal success). */
export async function finishUpload(db: Db, contentHash: string, input: FinishInput): Promise<void> {
  await db
    .update(uploadLedger)
    .set({
      status: 'done',
      resultUrl: input.resultUrl,
      manifestUrl: input.manifestUrl,
      engine: input.engine,
      ...(input.durationSec === undefined ? {} : { durationSec: input.durationSec }),
    })
    .where(eq(uploadLedger.contentHash, contentHash));
}

/** Append a durable failure record (dead-letter audit). */
export async function recordFailure(
  db: Db,
  contentHash: string,
  stage: string,
  code: string,
  message: string,
): Promise<void> {
  await db.insert(flowFailures).values({ contentHash, stage, code, message });
}

export interface DebitInput {
  readonly userId: string;
  readonly jobId: string;
  readonly amountUsdt: number;
  readonly reason: string;
}

/**
 * Idempotently record a PAYG debit in `balance_entries`. Keyed by
 * (user_id, job_id) with a content-derived `job_id`, so a stage retry or
 * re-delivered job never double-charges. Throws on an empty jobId (a NULL
 * job_id is treated as distinct by the unique index → would silently dupe).
 * Returns whether a new debit row was written.
 */
export async function debitOnce(db: Db, input: DebitInput): Promise<boolean> {
  if (input.jobId.length === 0) {
    throw new Error('debitOnce requires a non-empty jobId to stay idempotent');
  }
  const result = await db.execute(sql`
    INSERT INTO balance_entries (user_id, kind, amount_usdt, job_id, reason)
    VALUES (${input.userId}, 'payg', ${(-input.amountUsdt).toString()}, ${input.jobId}, ${input.reason})
    ON CONFLICT (user_id, job_id) DO NOTHING
    RETURNING id
  `);
  return result.rows.length > 0;
}

/** Persist the BullMQ flow root jobId, marking the upload's flow as enqueued. */
export async function setFlowJobId(db: Db, contentHash: string, flowJobId: string): Promise<void> {
  await db
    .update(uploadLedger)
    .set({ flowJobId })
    .where(eq(uploadLedger.contentHash, contentHash));
}

/**
 * Rows that won their ledger claim but whose flow never reached Redis — the true
 * "crashed between claim and enqueue" gap. The marker is `flow_job_id IS NULL`:
 * a successful enqueue sets it ({@link setFlowJobId}), so a healthy in-flight (or
 * slow) flow is NEVER re-swept — only an un-enqueued one is. `olderThan` is a
 * secondary grace so a row mid-enqueue isn't raced. Terminal rows are excluded.
 */
export function findStuckFlows(db: Db, olderThan: Date): Promise<UploadRow[]> {
  return db
    .select()
    .from(uploadLedger)
    .where(
      and(
        notInArray(uploadLedger.status, [...TERMINAL_STATUSES]),
        isNull(uploadLedger.flowJobId),
        lt(uploadLedger.updatedAt, olderThan),
      ),
    );
}
