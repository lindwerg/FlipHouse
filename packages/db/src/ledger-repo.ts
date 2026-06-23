import { and, asc, desc, eq, inArray, isNull, lt, notInArray, sql } from 'drizzle-orm';

import type { Db } from './client.js';
import { microsToNumericString } from './rating.js';
import { clips, costRecords, flowFailures, uploadLedger, uploadStatusEnum } from './schema.js';

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

/**
 * One ranked clip row as projected for the creator dashboard. Heavy JSONB
 * columns (`subScores`, `modalitiesUsed`) are deliberately EXCLUDED from the
 * projection so the dashboard payload stays small. Numeric columns surface as
 * strings (drizzle/pg numeric mode) — the API route coerces them at its zod
 * boundary, keeping the repo a thin storage seam.
 */
export interface ClipDashboardRow {
  readonly rank: number;
  readonly score: string;
  readonly startTime: string;
  readonly endTime: string;
  readonly durationS: string;
  readonly width: number;
  readonly height: number;
  readonly clipUrl: string;
  readonly title: string;
}

export interface OwnerClips {
  readonly status: UploadStatus;
  readonly clips: readonly ClipDashboardRow[];
}

/**
 * Owner-scoped read of an upload's status + ranked clips for the dashboard.
 * Returns `null` when the ledger row does not exist OR is owned by a different
 * user — the route maps either case to a 404 so a wrong/forged contentHash never
 * leaks another creator's existence. Clips are ordered by `rank` asc (best
 * first); the heavy JSONB columns are excluded from the projection.
 */
export async function listClipsForOwner(
  db: Db,
  contentHash: string,
  ownerId: string,
): Promise<OwnerClips | null> {
  const rows = await db
    .select({ status: uploadLedger.status, ownerId: uploadLedger.ownerId })
    .from(uploadLedger)
    .where(eq(uploadLedger.contentHash, contentHash));
  const row = rows[0];
  if (!row || row.ownerId !== ownerId) {
    return null;
  }

  const clipRows = await db
    .select({
      rank: clips.rank,
      score: clips.score,
      startTime: clips.startTime,
      endTime: clips.endTime,
      durationS: clips.durationS,
      width: clips.width,
      height: clips.height,
      clipUrl: clips.clipUrl,
      title: clips.title,
    })
    .from(clips)
    .where(eq(clips.contentHash, contentHash))
    .orderBy(asc(clips.rank));

  return { status: row.status, clips: clipRows };
}

/** Default page size for {@link listUploadsForOwner} — newest uploads first. */
export const OWNER_UPLOADS_DEFAULT_LIMIT = 50;

/**
 * One upload as projected for the owner-wide "Мои клипы" history: the ledger
 * identity + status + billable duration + creation time, plus its ranked clips
 * (same projection as {@link listClipsForOwner}). In-flight uploads carry an
 * empty `clips` array until publish writes them.
 */
export interface OwnerUpload {
  readonly contentHash: string;
  readonly status: UploadStatus;
  readonly durationSec: number | null;
  readonly createdAt: Date;
  readonly clips: readonly ClipDashboardRow[];
}

/** Keyset cursor for {@link listUploadsForOwner} — the last row of the prior page. */
export interface OwnerUploadsCursor {
  readonly createdAt: Date;
  readonly contentHash: string;
}

export interface ListUploadsForOwnerOptions {
  /** Max upload rows to return. Defaults to {@link OWNER_UPLOADS_DEFAULT_LIMIT}. */
  readonly limit?: number;
  /** Fetch the page strictly older than this (createdAt, contentHash) cursor. */
  readonly cursor?: OwnerUploadsCursor;
}

/**
 * Owner-wide read of an owner's upload history (ALL statuses, not just `done` —
 * in-flight uploads are included so a refresh never drops a running job), newest
 * first, with each upload's ranked clips attached. Strictly scoped to `ownerId`:
 * the route NEVER accepts an owner from the client, so a creator only ever sees
 * their own rows. Ordered `(created_at desc, content_hash desc)` for a stable
 * keyset; `cursor` resumes from the prior page's last row. Heavy JSONB clip
 * columns are excluded, mirroring {@link listClipsForOwner}. Returns `[]` for an
 * owner with no uploads.
 */
export async function listUploadsForOwner(
  db: Db,
  ownerId: string,
  opts?: ListUploadsForOwnerOptions,
): Promise<readonly OwnerUpload[]> {
  const limit = opts?.limit ?? OWNER_UPLOADS_DEFAULT_LIMIT;
  const cursor = opts?.cursor;
  // (created_at, content_hash) keyset: a tie on the timestamp is broken by the
  // primary-key hash, so the cursor walks every row exactly once with no skips.
  // The cursor's Date is cast to `timestamp` explicitly so the row-value
  // comparison orders chronologically — without the cast pg can resolve the
  // bound param as text and compare the timestamp lexicographically.
  const olderThanCursor = cursor
    ? sql`(${uploadLedger.createdAt}, ${uploadLedger.contentHash}) < (${cursor.createdAt}::timestamp, ${cursor.contentHash})`
    : undefined;

  const uploadRows = await db
    .select({
      contentHash: uploadLedger.contentHash,
      status: uploadLedger.status,
      durationSec: uploadLedger.durationSec,
      createdAt: uploadLedger.createdAt,
    })
    .from(uploadLedger)
    .where(and(eq(uploadLedger.ownerId, ownerId), olderThanCursor))
    .orderBy(desc(uploadLedger.createdAt), desc(uploadLedger.contentHash))
    .limit(limit);

  if (uploadRows.length === 0) {
    return [];
  }

  // One batched read of every clip across the page's hashes (no N+1), grouped
  // back onto its upload in memory and kept rank-ordered.
  const hashes = uploadRows.map((row) => row.contentHash);
  const clipRows = await db
    .select({
      contentHash: clips.contentHash,
      rank: clips.rank,
      score: clips.score,
      startTime: clips.startTime,
      endTime: clips.endTime,
      durationS: clips.durationS,
      width: clips.width,
      height: clips.height,
      clipUrl: clips.clipUrl,
      title: clips.title,
    })
    .from(clips)
    .where(inArray(clips.contentHash, hashes))
    .orderBy(asc(clips.rank));

  const clipsByHash = new Map<string, ClipDashboardRow[]>();
  for (const { contentHash, ...clip } of clipRows) {
    const bucket = clipsByHash.get(contentHash);
    if (bucket) {
      bucket.push(clip);
    } else {
      clipsByHash.set(contentHash, [clip]);
    }
  }

  return uploadRows.map((row) => ({
    contentHash: row.contentHash,
    status: row.status,
    durationSec: row.durationSec,
    createdAt: row.createdAt,
    clips: clipsByHash.get(row.contentHash) ?? [],
  }));
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

/**
 * Append a durable failure record (dead-letter audit). `ownerId` is OPTIONAL: a
 * pre-claim ingest failure stamps it so the dashboard can surface the failure to
 * exactly that creator (there is no content_hash to owner-gate on yet), while an
 * in-flight stage failure omits it (its `contentHash` is owner-gated via the
 * ledger join). A NULL owner_id is never returned by the owner-scoped read.
 */
export async function recordFailure(
  db: Db,
  contentHash: string,
  stage: string,
  code: string,
  message: string,
  ownerId?: string,
): Promise<void> {
  await db.insert(flowFailures).values({ contentHash, stage, code, message, ownerId: ownerId ?? null });
}

/** The latest classified ingest failure surfaced to the dashboard poll. */
export interface IngestFailureRow {
  readonly code: string;
  readonly message: string;
  readonly createdAt: Date;
}

/**
 * Read the most-recent ingest failure for an owner keyed by the synthetic
 * `ingest:<sha256(url)>` content-hash. STRICTLY owner-scoped: the `owner_id`
 * predicate means a creator can only ever read their OWN failure, never another
 * user's (the dashboard poll passes the server-trusted Clerk userId). Returns the
 * latest row (newest first) or `null` when the ingest has not (yet) failed —
 * letting the poll distinguish "still downloading" from "failed, here is why".
 */
export async function findIngestFailure(
  db: Db,
  ownerId: string,
  ingestKey: string,
): Promise<IngestFailureRow | null> {
  const rows = await db
    .select({
      code: flowFailures.code,
      message: flowFailures.message,
      createdAt: flowFailures.createdAt,
    })
    .from(flowFailures)
    .where(and(eq(flowFailures.ownerId, ownerId), eq(flowFailures.contentHash, ingestKey)))
    // `id desc` tie-breaks rows sharing a `created_at` instant so "latest" is the
    // most-recently-inserted (serial id is monotonic), never order-undefined.
    .orderBy(desc(flowFailures.createdAt), desc(flowFailures.id))
    .limit(1);
  return rows[0] ?? null;
}

export interface DebitInput {
  readonly userId: string;
  readonly jobId: string;
  /**
   * The POSITIVE charge as an exact `numeric(20,6)` string (e.g. `"0.250000"`).
   * A string — not a float — so the integer-derived amount never round-trips
   * through IEEE-754 (which would drift for rates not expressible as a power-of-two
   * fraction). debitOnce negates it by string prefix and binds it verbatim.
   */
  readonly amountUsdt: string;
  readonly reason: string;
}

/**
 * Idempotently record a PAYG debit in `balance_entries` AND decrement the cached
 * `subscription.balance_usdt`, both inside ONE transaction. Keyed by (user_id,
 * job_id) with a content-derived `job_id`, so a stage retry or re-delivered job
 * never double-charges. Throws on an empty jobId (a NULL job_id is treated as
 * distinct by the unique index → would silently dupe). Returns whether a new
 * debit row was written.
 *
 * The cached balance is decremented ONLY when the ON CONFLICT insert actually
 * wrote a row — the `RETURNING id` length is the gate — so a duplicate call is a
 * true no-op on both the ledger and the balance column (no divergence). The
 * balance is allowed to go negative: a completed job is always charged, and the
 * pre-submit gate is what guards starting an unaffordable job.
 */
export async function debitOnce(db: Db, input: DebitInput): Promise<boolean> {
  if (input.jobId.length === 0) {
    throw new Error('debitOnce requires a non-empty jobId to stay idempotent');
  }
  // String negation by prefix keeps the exact numeric — no float arithmetic.
  const amount = `-${input.amountUsdt}`;
  return db.transaction(async (tx) => {
    const inserted = await tx.execute(sql`
      INSERT INTO balance_entries (user_id, kind, amount_usdt, job_id, reason)
      VALUES (${input.userId}, 'payg', ${amount}, ${input.jobId}, ${input.reason})
      ON CONFLICT (user_id, job_id) DO NOTHING
      RETURNING id
    `);
    if (inserted.rows.length === 0) {
      return false;
    }
    // A user can reach publish with no subscription row (free plan never created
    // one — see usageGate). Materialize it at balance 0 first, else the UPDATE
    // below matches zero rows and the cached balance silently diverges from the
    // ledger. All other columns carry defaults, so user_id alone suffices.
    await tx.execute(sql`
      INSERT INTO subscription (user_id)
      VALUES (${input.userId})
      ON CONFLICT (user_id) DO NOTHING
    `);
    // Same transaction → ledger sum and cached balance can never diverge.
    await tx.execute(sql`
      UPDATE subscription
      SET balance_usdt = balance_usdt + ${amount}
      WHERE user_id = ${input.userId}
    `);
    return true;
  });
}

export interface DebitPaygInput {
  readonly userId: string;
  readonly jobId: string;
  /** Charge in micro-USDT (integer, 1e6 scale) — converted to the ledger string here. */
  readonly amountMicros: bigint;
}

/** PAYG debit reason recorded on the ledger row (audit string). */
const PAYG_DEBIT_REASON = 'payg:clip-job';

/**
 * Charge a PAYG job against the prepaid balance. The micro-USDT amount is the
 * billing authority; it is converted to the exact `numeric(20,6)` string at THIS
 * boundary (integer math, no float) and routed through {@link debitOnce}, which
 * owns the (user, jobId) idempotency + atomic balance decrement. `jobId` is the
 * stable contentHash, so a re-published upload charges exactly once.
 */
export function debitPayg(db: Db, input: DebitPaygInput): Promise<boolean> {
  // Exact micro→numeric(20,6) string; never widened to a float (HIGH fix).
  const amountUsdt = microsToNumericString(input.amountMicros);
  return debitOnce(db, {
    userId: input.userId,
    jobId: input.jobId,
    amountUsdt,
    reason: PAYG_DEBIT_REASON,
  });
}

export interface CogsInput {
  readonly contentHash: string;
  readonly ownerId: string;
  /** Cost of goods sold in micro-USD (integer, 1e6 scale) — NO float. */
  readonly costUsdMicros: bigint;
  readonly engine?: string;
}

/**
 * Persist a cost-of-goods-sold row to the COGS sink (separate from revenue).
 * Idempotent on `content_hash` via ON CONFLICT DO NOTHING, so a re-published
 * upload records its cost exactly once. Returns whether a new row was written.
 */
export async function recordCogs(db: Db, input: CogsInput): Promise<boolean> {
  const inserted = await db
    .insert(costRecords)
    .values({
      contentHash: input.contentHash,
      ownerId: input.ownerId,
      costUsdMicros: input.costUsdMicros,
      ...(input.engine === undefined ? {} : { engine: input.engine }),
    })
    .onConflictDoNothing({ target: costRecords.contentHash })
    .returning({ id: costRecords.id });
  return inserted.length > 0;
}

/**
 * Forward-only write of the probed source duration onto the ledger row — the
 * billable quantity the PAYG charge is computed from. Mirrors {@link setFlowJobId}
 * (a plain UPDATE keyed on contentHash); idempotent under stage retry.
 */
export async function setSourceDuration(db: Db, contentHash: string, durationSec: number): Promise<void> {
  await db.update(uploadLedger).set({ durationSec }).where(eq(uploadLedger.contentHash, contentHash));
}

/** The billing inputs publish reads off an upload to compute its PAYG charge. */
export interface UploadCharge {
  readonly ownerId: string;
  readonly durationSec: number | null;
}

/**
 * Load the owner + probed source duration for an upload, or `null` when the
 * ledger row does not exist. `durationSec` is `null` when the transcode probe
 * never wrote it — publish must decide how to charge a missing duration.
 */
export async function loadUpload(db: Db, contentHash: string): Promise<UploadCharge | null> {
  const rows = await db
    .select({ ownerId: uploadLedger.ownerId, durationSec: uploadLedger.durationSec })
    .from(uploadLedger)
    .where(eq(uploadLedger.contentHash, contentHash));
  const row = rows[0];
  return row ? { ownerId: row.ownerId, durationSec: row.durationSec } : null;
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
