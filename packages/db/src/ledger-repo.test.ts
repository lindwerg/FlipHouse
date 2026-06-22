import { PGlite } from '@electric-sql/pglite';
import { sql } from 'drizzle-orm';
import { drizzle } from 'drizzle-orm/pglite';
import { afterEach, beforeEach, expect, test } from 'vitest';

import type { Db } from './client.js';
import {
  claimUpload,
  debitOnce,
  findStuckFlows,
  finishUpload,
  listClipsForOwner,
  recordFailure,
  setFlowJobId,
  setStatus,
  upsertClips,
} from './ledger-repo.js';
import * as schema from './schema.js';

// Test-only DDL mirroring the apps/web migration (one Postgres, one chain).
const DDL = `
CREATE TYPE upload_status AS ENUM ('queued','hashing','transcoding','transcribing','scoring','reframing','captioning','rendering','storing','publishing','done','failed','duplicate');
CREATE TABLE upload_ledger (
  content_hash text PRIMARY KEY,
  owner_id text NOT NULL,
  first_upload_id text NOT NULL,
  tus_object_key text NOT NULL,
  status upload_status NOT NULL DEFAULT 'queued',
  flow_job_id text,
  size_bytes integer,
  duration_sec integer,
  result_url text,
  manifest_url text,
  engine text,
  error text,
  attempts integer NOT NULL DEFAULT 0,
  created_at timestamp NOT NULL DEFAULT now(),
  updated_at timestamp NOT NULL DEFAULT now()
);
CREATE TABLE clips (
  id serial PRIMARY KEY,
  content_hash text NOT NULL,
  rank integer NOT NULL,
  score numeric(6,4) NOT NULL,
  sub_scores jsonb NOT NULL,
  confidence integer NOT NULL,
  start_time numeric(10,3) NOT NULL,
  end_time numeric(10,3) NOT NULL,
  duration_s numeric(10,3) NOT NULL,
  width integer NOT NULL,
  height integer NOT NULL,
  clip_url text NOT NULL,
  title text NOT NULL,
  used_video boolean NOT NULL,
  model_used text NOT NULL,
  modalities_used jsonb NOT NULL,
  manifest_schema_version integer NOT NULL,
  engine text NOT NULL,
  created_at timestamp NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX clips_hash_rank_uq ON clips (content_hash, rank);
CREATE TABLE flow_failures (
  id serial PRIMARY KEY,
  content_hash text NOT NULL,
  stage text NOT NULL,
  code text NOT NULL,
  message text NOT NULL,
  created_at timestamp NOT NULL DEFAULT now()
);
CREATE TYPE balance_entry_kind AS ENUM ('deposit','payg','subscription');
CREATE TABLE balance_entries (
  id serial PRIMARY KEY,
  user_id text NOT NULL,
  kind balance_entry_kind NOT NULL,
  amount_usdt numeric(20,6) NOT NULL,
  job_id text,
  txid text,
  reason text NOT NULL,
  created_at timestamp NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX balance_entries_user_job_uq ON balance_entries (user_id, job_id);
`;

const CLAIM = {
  contentHash: 'a'.repeat(64),
  ownerId: 'user_1',
  firstUploadId: 'tus_1',
  tusObjectKey: 'uploads/a',
};

const CLIP = {
  rank: 0,
  score: '87.5000',
  subScores: { hook: 9 },
  confidence: 80,
  startTime: '12.000',
  endTime: '41.500',
  durationS: '29.500',
  width: 1080,
  height: 1920,
  clipUrl: 'intermediate/x/reframe/clip_00.mp4',
  title: 'best',
  usedVideo: true,
  modelUsed: 'gemini',
  modalitiesUsed: ['text'],
  manifestSchemaVersion: 1,
  engine: 'fliphouse-cpu-mediapipe-v1',
};

let client: PGlite;
let db: Db;

beforeEach(async () => {
  client = new PGlite();
  await client.exec(DDL);
  db = drizzle({ client, schema }) as unknown as Db;
});

afterEach(async () => {
  await client.close();
});

test('claimUpload wins on first insert and reports the existing row on re-claim', async () => {
  const first = await claimUpload(db, CLAIM);
  expect(first.claimed).toBe(true);
  expect(first.existing).toBeUndefined();

  const second = await claimUpload(db, { ...CLAIM, ownerId: 'user_2' });
  expect(second.claimed).toBe(false);
  expect(second.existing?.ownerId).toBe('user_1'); // original wins
});

test('setStatus advances only from a valid prior status', async () => {
  await claimUpload(db, CLAIM);

  expect(await setStatus(db, CLAIM.contentHash, 'hashing', ['queued'])).toBe(true);
  // current is now 'hashing'; a transition gated on 'queued' must be rejected.
  expect(await setStatus(db, CLAIM.contentHash, 'scoring', ['queued'])).toBe(false);
});

test('upsertClips replaces prior clips and tolerates an empty set', async () => {
  await claimUpload(db, CLAIM);
  await upsertClips(db, CLAIM.contentHash, [CLIP, { ...CLIP, rank: 1, clipUrl: 'c1' }]);

  const two = await db.select().from(schema.clips);
  expect(two).toHaveLength(2);

  await upsertClips(db, CLAIM.contentHash, [{ ...CLIP, title: 'replaced' }]);
  const one = await db.select().from(schema.clips);
  expect(one).toHaveLength(1);
  expect(one[0]?.title).toBe('replaced');

  await upsertClips(db, CLAIM.contentHash, []);
  expect(await db.select().from(schema.clips)).toHaveLength(0);
});

test('finishUpload marks done with and without a duration', async () => {
  await claimUpload(db, CLAIM);

  await finishUpload(db, CLAIM.contentHash, {
    resultUrl: 'r',
    manifestUrl: 'm',
    engine: 'e',
    durationSec: 120,
  });
  let row = (await db.select().from(schema.uploadLedger))[0];
  expect(row?.status).toBe('done');
  expect(row?.durationSec).toBe(120);

  await finishUpload(db, CLAIM.contentHash, { resultUrl: 'r2', manifestUrl: 'm2', engine: 'e2' });
  row = (await db.select().from(schema.uploadLedger))[0];
  expect(row?.resultUrl).toBe('r2');
});

test('recordFailure appends a durable failure row', async () => {
  await recordFailure(db, CLAIM.contentHash, 'score', 'OPENROUTER_402', 'no credits');

  const rows = await db.select().from(schema.flowFailures);
  expect(rows).toHaveLength(1);
  expect(rows[0]?.code).toBe('OPENROUTER_402');
});

test('debitOnce is idempotent per (user, jobId) and rejects an empty jobId', async () => {
  const first = await debitOnce(db, { userId: 'user_1', jobId: 'flow-x', amountUsdt: 1, reason: 'clip' });
  const dup = await debitOnce(db, { userId: 'user_1', jobId: 'flow-x', amountUsdt: 1, reason: 'clip' });

  expect(first).toBe(true);
  expect(dup).toBe(false);
  await expect(
    debitOnce(db, { userId: 'user_1', jobId: '', amountUsdt: 1, reason: 'x' }),
  ).rejects.toThrow(/non-empty jobId/);
});

test('findStuckFlows returns only un-enqueued (flow_job_id IS NULL) pre-terminal rows older than the cutoff', async () => {
  const HASH_B = 'b'.repeat(64);
  const HASH_C = 'c'.repeat(64);
  const HASH_D = 'd'.repeat(64);
  await claimUpload(db, CLAIM);
  await claimUpload(db, { ...CLAIM, contentHash: HASH_B, firstUploadId: 'tus_b' });
  await claimUpload(db, { ...CLAIM, contentHash: HASH_C, firstUploadId: 'tus_c' });
  await claimUpload(db, { ...CLAIM, contentHash: HASH_D, firstUploadId: 'tus_d' });

  // 'a' is stuck-old, pre-terminal, never enqueued → the only stuck row.
  // 'b' is old but terminal; 'c' is recent; 'd' is old but DID enqueue (marker set).
  await db.execute(sql`UPDATE upload_ledger SET updated_at = '2000-01-01' WHERE content_hash = ${CLAIM.contentHash}`);
  await db.execute(sql`UPDATE upload_ledger SET updated_at = '2000-01-01', status = 'done' WHERE content_hash = ${HASH_B}`);
  await db.execute(sql`UPDATE upload_ledger SET updated_at = '2000-01-01' WHERE content_hash = ${HASH_D}`);
  await setFlowJobId(db, HASH_D, `flow-${HASH_D}`);

  const stuck = await findStuckFlows(db, new Date('2020-01-01'));
  expect(stuck.map((r) => r.contentHash)).toEqual([CLAIM.contentHash]);
});

test('setFlowJobId persists the flow root jobId, taking the row out of the stuck set', async () => {
  await claimUpload(db, CLAIM);
  await db.execute(sql`UPDATE upload_ledger SET updated_at = '2000-01-01' WHERE content_hash = ${CLAIM.contentHash}`);
  expect((await findStuckFlows(db, new Date('2020-01-01'))).map((r) => r.contentHash)).toEqual([CLAIM.contentHash]);

  await setFlowJobId(db, CLAIM.contentHash, `flow-${CLAIM.contentHash}`);

  expect(await findStuckFlows(db, new Date('2020-01-01'))).toEqual([]);
});

test('listClipsForOwner returns the status and rank-ordered clips for the owner', async () => {
  await claimUpload(db, CLAIM);
  await setStatus(db, CLAIM.contentHash, 'hashing', ['queued']);
  // Insert out of rank order to prove the ORDER BY rank asc.
  await upsertClips(db, CLAIM.contentHash, [
    { ...CLIP, rank: 2, title: 'third' },
    { ...CLIP, rank: 0, title: 'first' },
    { ...CLIP, rank: 1, title: 'second' },
  ]);

  const result = await listClipsForOwner(db, CLAIM.contentHash, CLAIM.ownerId);

  expect(result).not.toBeNull();
  expect(result?.status).toBe('hashing');
  expect(result?.clips.map((c) => c.title)).toEqual(['first', 'second', 'third']);
  // Heavy JSONB columns are excluded from the projection.
  const first = result?.clips[0] as Record<string, unknown>;
  expect(first).not.toHaveProperty('subScores');
  expect(first).not.toHaveProperty('modalitiesUsed');
  // But the dashboard fields are present.
  expect(first?.rank).toBe(0);
  expect(first?.clipUrl).toBe(CLIP.clipUrl);
  expect(first?.width).toBe(1080);
});

test('listClipsForOwner returns null when the row is owned by another user (auth)', async () => {
  await claimUpload(db, CLAIM);
  await upsertClips(db, CLAIM.contentHash, [CLIP]);

  expect(await listClipsForOwner(db, CLAIM.contentHash, 'user_2')).toBeNull();
});

test('listClipsForOwner returns null when there is no ledger row', async () => {
  expect(await listClipsForOwner(db, 'f'.repeat(64), CLAIM.ownerId)).toBeNull();
});

test('listClipsForOwner returns an empty clip list for an owned row with no clips yet', async () => {
  await claimUpload(db, CLAIM);

  const result = await listClipsForOwner(db, CLAIM.contentHash, CLAIM.ownerId);

  expect(result).not.toBeNull();
  expect(result?.status).toBe('queued');
  expect(result?.clips).toEqual([]);
});
