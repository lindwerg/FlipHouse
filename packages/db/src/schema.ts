import {
  bigint,
  boolean,
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

/** Durable mirror of fatal flow failures — a dead-letter audit that survives Redis eviction. */
export const flowFailures = pgTable('flow_failures', {
  id: serial('id').primaryKey(),
  contentHash: text('content_hash').notNull(),
  stage: text('stage').notNull(),
  code: text('code').notNull(),
  message: text('message').notNull(),
  createdAt: timestamp('created_at', { mode: 'date' }).defaultNow().notNull(),
});
