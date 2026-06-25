import {
  bigint,
  boolean,
  index,
  integer,
  jsonb,
  numeric,
  pgEnum,
  pgTable,
  serial,
  text,
  timestamp,
  uniqueIndex,
} from 'drizzle-orm/pg-core';

/**
 * P2 Flow-DAG pipeline tables — owned here as the single source of truth and
 * re-exported by `apps/web/src/models/Schema.ts` so the one Postgres migration
 * chain (drizzle-kit in apps/web) includes them. `apps/worker-node` consumes
 * these directly, with no worker→web coupling. (Billing tables stay in apps/web.)
 */

/** Forward-only upload status (mirrors worker-node state/transitions.ts). */
export const uploadStatusEnum = pgEnum('upload_status', [
  'queued',
  'hashing',
  'transcoding',
  'transcribing',
  'scoring',
  'reframing',
  'captioning',
  'rendering',
  'storing',
  'publishing',
  'done',
  'failed',
  'duplicate',
]);

/** One row per uploaded video, keyed by content-hash — the idempotency authority. */
export const uploadLedger = pgTable('upload_ledger', {
  contentHash: text('content_hash').primaryKey(),
  ownerId: text('owner_id').notNull(),
  firstUploadId: text('first_upload_id').notNull(),
  tusObjectKey: text('tus_object_key').notNull(),
  status: uploadStatusEnum('status').default('queued').notNull(),
  flowJobId: text('flow_job_id'),
  sizeBytes: integer('size_bytes'),
  durationSec: integer('duration_sec'),
  resultUrl: text('result_url'),
  manifestUrl: text('manifest_url'),
  engine: text('engine'),
  error: text('error'),
  attempts: integer('attempts').default(0).notNull(),
  createdAt: timestamp('created_at', { mode: 'date' }).defaultNow().notNull(),
  updatedAt: timestamp('updated_at', { mode: 'date' })
    .defaultNow()
    .$onUpdate(() => new Date())
    .notNull(),
});

/** Ranked output clips for an upload (rank 0 = best), shown in the dashboard. */
export const clips = pgTable(
  'clips',
  {
    id: serial('id').primaryKey(),
    contentHash: text('content_hash').notNull(),
    rank: integer('rank').notNull(),
    score: numeric('score', { precision: 6, scale: 4 }).notNull(),
    subScores: jsonb('sub_scores').notNull(),
    confidence: integer('confidence').notNull(),
    startTime: numeric('start_time', { precision: 10, scale: 3 }).notNull(),
    endTime: numeric('end_time', { precision: 10, scale: 3 }).notNull(),
    durationS: numeric('duration_s', { precision: 10, scale: 3 }).notNull(),
    width: integer('width').notNull(),
    height: integer('height').notNull(),
    clipUrl: text('clip_url').notNull(),
    title: text('title').notNull(),
    usedVideo: boolean('used_video').notNull(),
    modelUsed: text('model_used').notNull(),
    modalitiesUsed: jsonb('modalities_used').notNull(),
    manifestSchemaVersion: integer('manifest_schema_version').notNull(),
    engine: text('engine').notNull(),
    createdAt: timestamp('created_at', { mode: 'date' }).defaultNow().notNull(),
  },
  (table) => [
    // (content_hash, rank) is unique so a re-publish UPDATEs the same row
    // instead of orphaning a duplicate clip.
    uniqueIndex('clips_hash_rank_uq').on(table.contentHash, table.rank),
  ],
);

/**
 * Cost-of-goods-sold sink, kept SEPARATE from the revenue ledger (`balance_entries`).
 * One row per published upload, keyed by `content_hash` (the idempotency authority):
 * a re-publish of the same upload is a no-op via ON CONFLICT (content_hash) DO NOTHING.
 * `cost_usd_micros` is integer micro-USD (1e6 scale, mirrors micro-USDT) — NO float —
 * representing what the pipeline spent (GPU/LLM) to produce the clips. The Python COGS
 * threading through the manifest is a documented follow-up; rows ship at 0 for now.
 */
export const costRecords = pgTable(
  'cost_records',
  {
    id: serial('id').primaryKey(),
    contentHash: text('content_hash').notNull(),
    ownerId: text('owner_id').notNull(),
    costUsdMicros: bigint('cost_usd_micros', { mode: 'bigint' }).notNull(),
    engine: text('engine'),
    createdAt: timestamp('created_at', { mode: 'date' }).defaultNow().notNull(),
  },
  (table) => [
    // One COGS row per upload — the unique key makes recordCogs idempotent.
    uniqueIndex('cost_records_content_hash_uq').on(table.contentHash),
  ],
);

/**
 * Subscription-plan minute-usage ledger — the cap-plan analogue of the PAYG
 * `balance_entries`. One row per billed job, keyed by (user_id, job_id) with a
 * content-derived `job_id`, so {@link incrementMinutesUsed} advances the monthly
 * minute counter EXACTLY ONCE per upload (a re-publish is an ON CONFLICT no-op,
 * never a double-count). Append-only audit: the cached `subscription.minutes_used_this_period`
 * is the sum of these rows for the current period. `minutes` is the whole-minute
 * billable quantity (mirrors the PAYG rounding); NO float.
 */
export const usageRecords = pgTable(
  'usage_records',
  {
    id: serial('id').primaryKey(),
    userId: text('user_id').notNull(),
    jobId: text('job_id').notNull(),
    minutes: integer('minutes').notNull(),
    createdAt: timestamp('created_at', { mode: 'date' }).defaultNow().notNull(),
  },
  (table) => [
    // (user_id, job_id) unique → a retried/re-published job never double-counts
    // the minute cap. Both columns are NOT NULL so the dedupe is exact (unlike
    // balance_entries, which leaves job_id NULL for deposits).
    uniqueIndex('usage_records_user_job_uq').on(table.userId, table.jobId),
  ],
);

/** Durable mirror of fatal flow failures — a dead-letter audit that survives Redis eviction. */
export const flowFailures = pgTable(
  'flow_failures',
  {
    id: serial('id').primaryKey(),
    contentHash: text('content_hash').notNull(),
    // The owner this failure belongs to, so a creator can be shown ONLY their own
    // failures (never another user's). Nullable: pre-claim ingest failures stamp it
    // (the dashboard polls failures by owner+url before any content_hash exists),
    // while in-flight stage failures leave it NULL and are read via the owner-gated
    // ledger join on content_hash instead.
    ownerId: text('owner_id'),
    stage: text('stage').notNull(),
    code: text('code').notNull(),
    message: text('message').notNull(),
    createdAt: timestamp('created_at', { mode: 'date' }).defaultNow().notNull(),
  },
  (table) => [
    // The ingest-status poll reads the latest failure for (owner_id, content_hash)
    // where content_hash is the synthetic `ingest:<sha256(url)>` key — index it so
    // the per-poll read stays a cheap point lookup.
    index('flow_failures_owner_hash_idx').on(table.ownerId, table.contentHash),
  ],
);
