import { PGlite } from '@electric-sql/pglite';
import { sql } from 'drizzle-orm';
import { drizzle } from 'drizzle-orm/pglite';
import { afterEach, beforeEach, expect, test } from 'vitest';

import type { Db } from './client.js';
import {
  claimUpload,
  debitOnce,
  debitPayg,
  findIngestFailure,
  findStuckFlows,
  findStuckStatusUploads,
  finishUpload,
  incrementMinutesUsed,
  isPaygPlan,
  listClipsForOwner,
  listUploadsForOwner,
  loadUpload,
  recordCogs,
  recordFailure,
  reconcileRows,
  reconcileStuckStatuses,
  setFlowJobId,
  setSourceDuration,
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
  owner_id text,
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
CREATE TABLE usage_records (
  id serial PRIMARY KEY,
  user_id text NOT NULL,
  job_id text NOT NULL,
  minutes integer NOT NULL,
  created_at timestamp NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX usage_records_user_job_uq ON usage_records (user_id, job_id);
CREATE TABLE cost_records (
  id serial PRIMARY KEY,
  content_hash text NOT NULL,
  owner_id text NOT NULL,
  cost_usd_micros bigint NOT NULL,
  engine text,
  created_at timestamp NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX cost_records_content_hash_uq ON cost_records (content_hash);
CREATE TYPE plan AS ENUM ('free','start','active','studio','payg');
CREATE TYPE subscription_status AS ENUM ('active','past_due','canceled');
CREATE TABLE subscription (
  user_id text PRIMARY KEY,
  plan plan NOT NULL DEFAULT 'free',
  balance_usdt numeric(20,6) NOT NULL DEFAULT '0',
  deposit_address text,
  deposit_index integer,
  subscription_status subscription_status,
  current_period_end timestamp,
  minutes_used_this_period integer NOT NULL DEFAULT 0,
  updated_at timestamp NOT NULL DEFAULT now(),
  created_at timestamp NOT NULL DEFAULT now()
);
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

test('recordFailure appends a durable failure row (no owner by default)', async () => {
  await recordFailure(db, CLAIM.contentHash, 'score', 'OPENROUTER_402', 'no credits');

  const rows = await db.select().from(schema.flowFailures);
  expect(rows).toHaveLength(1);
  expect(rows[0]?.code).toBe('OPENROUTER_402');
  expect(rows[0]?.ownerId).toBeNull();
});

test('recordFailure stamps the owner when given (pre-claim ingest failure)', async () => {
  await recordFailure(db, 'ingest:abc', 'ingest', 'ip-blocked', 'YouTube заблокировал', 'user_1');

  const rows = await db.select().from(schema.flowFailures);
  expect(rows[0]?.ownerId).toBe('user_1');
});

test('findIngestFailure returns the latest failure scoped to the owner', async () => {
  const KEY = 'ingest:deadbeef';
  // No failure yet → null (the poll reads this as "still downloading").
  expect(await findIngestFailure(db, 'user_1', KEY)).toBeNull();

  await recordFailure(db, KEY, 'ingest', 'private', 'first', 'user_1');
  await recordFailure(db, KEY, 'ingest', 'ip-blocked', 'second', 'user_1');

  const latest = await findIngestFailure(db, 'user_1', KEY);
  expect(latest?.code).toBe('ip-blocked');
  expect(latest?.message).toBe('second');
});

test('findIngestFailure never returns another owner’s failure', async () => {
  const KEY = 'ingest:cafef00d';
  await recordFailure(db, KEY, 'ingest', 'private', 'theirs', 'user_2');

  // Same key, different owner → must not leak the other user's failure.
  expect(await findIngestFailure(db, 'user_1', KEY)).toBeNull();
  expect((await findIngestFailure(db, 'user_2', KEY))?.message).toBe('theirs');
});

async function seedSubscription(userId: string, balanceUsdt: string): Promise<void> {
  await db.execute(
    sql`INSERT INTO subscription (user_id, balance_usdt) VALUES (${userId}, ${balanceUsdt})`,
  );
}

async function readBalance(userId: string): Promise<string | undefined> {
  const rows = await db.execute<{ balance_usdt: string }>(
    sql`SELECT balance_usdt FROM subscription WHERE user_id = ${userId}`,
  );
  return rows.rows[0]?.balance_usdt;
}

test('debitOnce is idempotent per (user, jobId) and rejects an empty jobId', async () => {
  await seedSubscription('user_1', '10.000000');
  const first = await debitOnce(db, { userId: 'user_1', jobId: 'flow-x', amountUsdt: '1', reason: 'clip' });
  const dup = await debitOnce(db, { userId: 'user_1', jobId: 'flow-x', amountUsdt: '1', reason: 'clip' });

  expect(first).toBe(true);
  expect(dup).toBe(false);
  await expect(
    debitOnce(db, { userId: 'user_1', jobId: '', amountUsdt: '1', reason: 'x' }),
  ).rejects.toThrow(/non-empty jobId/);
});

test('debitOnce decrements balance_usdt atomically, ONCE, only on a freshly-inserted row', async () => {
  await seedSubscription('user_1', '10.000000');

  // First debit writes the ledger row AND decrements the cached balance.
  const first = await debitOnce(db, { userId: 'user_1', jobId: 'flow-x', amountUsdt: '2.5', reason: 'clip' });
  expect(first).toBe(true);
  expect(await readBalance('user_1')).toBe('7.500000');

  // A duplicate (same jobId) is a no-op: NO ledger row, NO second decrement.
  const dup = await debitOnce(db, { userId: 'user_1', jobId: 'flow-x', amountUsdt: '2.5', reason: 'clip' });
  expect(dup).toBe(false);
  expect(await readBalance('user_1')).toBe('7.500000');

  // The ledger row was written exactly once.
  const entries = await db.execute<{ n: string }>(
    sql`SELECT count(*)::text AS n FROM balance_entries WHERE user_id = 'user_1' AND job_id = 'flow-x'`,
  );
  expect(entries.rows[0]?.n).toBe('1');
});

test('debitOnce proceeds past zero (negative balance allowed — job already done)', async () => {
  await seedSubscription('user_1', '1.000000');
  const ok = await debitOnce(db, { userId: 'user_1', jobId: 'flow-y', amountUsdt: '2.5', reason: 'clip' });
  expect(ok).toBe(true);
  // Spillover into the negative is acceptable; the pre-submit gate guards starts.
  expect(await readBalance('user_1')).toBe('-1.500000');
});

test('debitOnce materializes a missing subscription row (free plan) instead of silently diverging', async () => {
  // No seedSubscription: a free-plan user reaches publish with no subscription row.
  const ok = await debitOnce(db, { userId: 'user_free', jobId: 'flow-z', amountUsdt: '0.25', reason: 'clip' });
  expect(ok).toBe(true);
  // The row is created at 0 then decremented — ledger and cached balance agree.
  expect(await readBalance('user_free')).toBe('-0.250000');
  const entries = await db.execute<{ n: string }>(
    sql`SELECT count(*)::text AS n FROM balance_entries WHERE user_id = 'user_free'`,
  );
  expect(entries.rows[0]?.n).toBe('1');
});

test('debitPayg converts micros→numeric string and routes through debitOnce idempotently', async () => {
  await seedSubscription('user_1', '5.000000');
  // 500_000 micros = $0.50 (a 61s source at the 2-minute charge would be 500000).
  const first = await debitPayg(db, { userId: 'user_1', jobId: 'hash-1', amountMicros: 500_000n });
  const dup = await debitPayg(db, { userId: 'user_1', jobId: 'hash-1', amountMicros: 500_000n });

  expect(first).toBe(true);
  expect(dup).toBe(false);
  expect(await readBalance('user_1')).toBe('4.500000');

  const row = await db.execute<{ amount_usdt: string; kind: string; reason: string }>(
    sql`SELECT amount_usdt, kind, reason FROM balance_entries WHERE user_id = 'user_1' AND job_id = 'hash-1'`,
  );
  expect(row.rows[0]?.amount_usdt).toBe('-0.500000');
  expect(row.rows[0]?.kind).toBe('payg');
});

test('recordCogs inserts one row and is idempotent on content_hash (ON CONFLICT no-op)', async () => {
  const HASH = 'h'.repeat(64);
  const first = await recordCogs(db, {
    contentHash: HASH,
    ownerId: 'user_1',
    costUsdMicros: 25_000n,
    engine: 'fliphouse-cpu-mediapipe-v1',
  });
  const dup = await recordCogs(db, {
    contentHash: HASH,
    ownerId: 'user_1',
    costUsdMicros: 99_999n,
    engine: 'other',
  });

  expect(first).toBe(true);
  expect(dup).toBe(false);

  const rows = await db.select().from(schema.costRecords);
  expect(rows).toHaveLength(1);
  expect(rows[0]?.costUsdMicros).toBe(25_000n); // first write wins; dup did nothing
  expect(rows[0]?.engine).toBe('fliphouse-cpu-mediapipe-v1');
});

test('recordCogs persists a zero cost and a null engine (the ship-now default)', async () => {
  const HASH = 'z'.repeat(64);
  const ok = await recordCogs(db, { contentHash: HASH, ownerId: 'user_1', costUsdMicros: 0n });
  expect(ok).toBe(true);
  const rows = await db.select().from(schema.costRecords);
  expect(rows[0]?.costUsdMicros).toBe(0n);
  expect(rows[0]?.engine).toBeNull();
});

test('setSourceDuration writes duration_sec forward-only onto the ledger row', async () => {
  await claimUpload(db, CLAIM);
  await setSourceDuration(db, CLAIM.contentHash, 137);

  const row = (await db.select().from(schema.uploadLedger))[0];
  expect(row?.durationSec).toBe(137);
});

test('loadUpload returns ownerId + durationSec + plan, or null for an absent row', async () => {
  await claimUpload(db, CLAIM);
  await setSourceDuration(db, CLAIM.contentHash, 200);
  // A user with no subscription row defaults to the free plan (mirrors the gate).
  expect(await loadUpload(db, CLAIM.contentHash)).toEqual({
    ownerId: 'user_1',
    durationSec: 200,
    plan: 'free',
  });

  // No duration written yet → durationSec is null (publish must handle it).
  const HASH_E = 'e'.repeat(64);
  await claimUpload(db, { ...CLAIM, contentHash: HASH_E, firstUploadId: 'tus_e' });
  expect(await loadUpload(db, HASH_E)).toEqual({
    ownerId: 'user_1',
    durationSec: null,
    plan: 'free',
  });

  expect(await loadUpload(db, 'f'.repeat(64))).toBeNull();
});

test('loadUpload joins the owner\'s billing plan from subscription', async () => {
  await claimUpload(db, CLAIM);
  await db.execute(
    sql`INSERT INTO subscription (user_id, plan) VALUES (${CLAIM.ownerId}, 'payg')`,
  );
  expect((await loadUpload(db, CLAIM.contentHash))?.plan).toBe('payg');

  const HASH_S = 's'.repeat(64);
  await claimUpload(db, { ...CLAIM, contentHash: HASH_S, ownerId: 'user_sub', firstUploadId: 'tus_s' });
  await db.execute(sql`INSERT INTO subscription (user_id, plan) VALUES ('user_sub', 'start')`);
  expect((await loadUpload(db, HASH_S))?.plan).toBe('start');
});

test('isPaygPlan is true only for the payg plan', () => {
  expect(isPaygPlan('payg')).toBe(true);
  for (const plan of ['free', 'start', 'active', 'studio'] as const) {
    expect(isPaygPlan(plan)).toBe(false);
  }
});

async function readMinutesUsed(userId: string): Promise<number | undefined> {
  const rows = await db.execute<{ minutes_used_this_period: number }>(
    sql`SELECT minutes_used_this_period FROM subscription WHERE user_id = ${userId}`,
  );
  return rows.rows[0]?.minutes_used_this_period;
}

test('incrementMinutesUsed advances the cap ONCE per (user, job) and rejects bad input', async () => {
  await db.execute(sql`INSERT INTO subscription (user_id, plan) VALUES ('sub_1', 'start')`);

  const first = await incrementMinutesUsed(db, { userId: 'sub_1', jobId: 'hash-1', minutes: 5 });
  const dup = await incrementMinutesUsed(db, { userId: 'sub_1', jobId: 'hash-1', minutes: 5 });

  expect(first).toBe(true);
  expect(dup).toBe(false); // re-publish is a no-op — the cap is never double-counted
  expect(await readMinutesUsed('sub_1')).toBe(5);

  // A second, distinct job DOES advance the counter further.
  await incrementMinutesUsed(db, { userId: 'sub_1', jobId: 'hash-2', minutes: 3 });
  expect(await readMinutesUsed('sub_1')).toBe(8);

  await expect(
    incrementMinutesUsed(db, { userId: 'sub_1', jobId: '', minutes: 1 }),
  ).rejects.toThrow(/non-empty jobId/);
  await expect(
    incrementMinutesUsed(db, { userId: 'sub_1', jobId: 'x', minutes: -1 }),
  ).rejects.toThrow(/non-negative integer/);
  await expect(
    incrementMinutesUsed(db, { userId: 'sub_1', jobId: 'x', minutes: 1.5 }),
  ).rejects.toThrow(/non-negative integer/);
});

test('incrementMinutesUsed materializes a missing subscription row at 0 then advances', async () => {
  // No subscription row yet — the increment must create it, not silently no-op.
  const ok = await incrementMinutesUsed(db, { userId: 'sub_new', jobId: 'j', minutes: 4 });
  expect(ok).toBe(true);
  expect(await readMinutesUsed('sub_new')).toBe(4);
  const records = await db.execute<{ n: string }>(
    sql`SELECT count(*)::text AS n FROM usage_records WHERE user_id = 'sub_new'`,
  );
  expect(records.rows[0]?.n).toBe('1');
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

test('findStuckStatusUploads returns only ENQUEUED (flow_job_id set) pre-terminal rows older than the cutoff', async () => {
  const HASH_B = 'b'.repeat(64);
  const HASH_C = 'c'.repeat(64);
  const HASH_D = 'd'.repeat(64);
  await claimUpload(db, CLAIM);
  await claimUpload(db, { ...CLAIM, contentHash: HASH_B, firstUploadId: 'tus_b' });
  await claimUpload(db, { ...CLAIM, contentHash: HASH_C, firstUploadId: 'tus_c' });
  await claimUpload(db, { ...CLAIM, contentHash: HASH_D, firstUploadId: 'tus_d' });

  // 'a' is stuck-old, pre-terminal, DID enqueue → the only stuck-status row.
  // 'b' is old+enqueued but terminal; 'c' is recent+enqueued; 'd' is old but NEVER enqueued.
  await setStatus(db, CLAIM.contentHash, 'scoring', ['queued']);
  await setFlowJobId(db, CLAIM.contentHash, `flow-${CLAIM.contentHash}`);
  await setFlowJobId(db, HASH_B, `flow-${HASH_B}`);
  await setFlowJobId(db, HASH_C, `flow-${HASH_C}`);
  await db.execute(sql`UPDATE upload_ledger SET updated_at = '2000-01-01' WHERE content_hash = ${CLAIM.contentHash}`);
  await db.execute(sql`UPDATE upload_ledger SET updated_at = '2000-01-01', status = 'done' WHERE content_hash = ${HASH_B}`);
  await db.execute(sql`UPDATE upload_ledger SET updated_at = '2000-01-01' WHERE content_hash = ${HASH_D}`);

  const stuck = await findStuckStatusUploads(db, new Date('2020-01-01'));
  expect(stuck.map((r) => r.contentHash)).toEqual([CLAIM.contentHash]);
});

test('reconcileStuckStatuses backfills failed for an upload stranded in a non-terminal status', async () => {
  await claimUpload(db, CLAIM);
  await setStatus(db, CLAIM.contentHash, 'scoring', ['queued']);
  await setFlowJobId(db, CLAIM.contentHash, `flow-${CLAIM.contentHash}`);
  await db.execute(sql`UPDATE upload_ledger SET updated_at = '2000-01-01' WHERE content_hash = ${CLAIM.contentHash}`);

  const result = await reconcileStuckStatuses(db, new Date('2020-01-01'));

  expect(result).toEqual({ scanned: 1, reconciled: 1 });
  const after = await listClipsForOwner(db, CLAIM.contentHash, CLAIM.ownerId);
  expect(after?.status).toBe('failed');
  // A durable failure row is recorded so the dashboard surfaces a cause.
  const failure = await findIngestFailure(db, CLAIM.ownerId, CLAIM.contentHash);
  expect(failure?.code).toBe('STUCK_RECONCILED');
});

test('reconcileStuckStatuses is a guarded no-op for fresh or terminal uploads', async () => {
  await claimUpload(db, CLAIM); // recent, queued → not stuck
  const result = await reconcileStuckStatuses(db, new Date('2020-01-01'));
  expect(result).toEqual({ scanned: 0, reconciled: 0 });
  const after = await listClipsForOwner(db, CLAIM.contentHash, CLAIM.ownerId);
  expect(after?.status).toBe('queued'); // untouched
});

test('reconcileRows skips a row whose live status advanced since the scan (guarded miss)', async () => {
  await claimUpload(db, CLAIM);
  await setStatus(db, CLAIM.contentHash, 'scoring', ['queued']);
  await setFlowJobId(db, CLAIM.contentHash, `flow-${CLAIM.contentHash}`); // enqueued → in scan
  const rows = await findStuckStatusUploads(db, new Date('9999-01-01')); // captured at 'scoring'
  // The flow legitimately advanced to 'done' between the scan and the write.
  await setStatus(db, CLAIM.contentHash, 'reframing', ['scoring']);
  await db.execute(sql`UPDATE upload_ledger SET status = 'done' WHERE content_hash = ${CLAIM.contentHash}`);

  const result = await reconcileRows(db, rows);

  // Scanned the stale row but did NOT regress 'done' → reconciled stays 0.
  expect(result).toEqual({ scanned: 1, reconciled: 0 });
  const after = await listClipsForOwner(db, CLAIM.contentHash, CLAIM.ownerId);
  expect(after?.status).toBe('done');
  // And NO bogus STUCK_RECONCILED cause was recorded for the healthy upload:
  // recordFailure is gated on the guarded transition actually landing (moved).
  const failure = await findIngestFailure(db, CLAIM.ownerId, CLAIM.contentHash);
  expect(failure).toBeNull();
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

/** Claim an upload and stamp its created_at so newest-first ordering is deterministic. */
async function seedUpload(
  hash: string,
  ownerId: string,
  createdAt: string,
  status?: 'done' | 'failed' | 'queued',
): Promise<void> {
  await claimUpload(db, { ...CLAIM, contentHash: hash, ownerId, firstUploadId: `tus_${hash}` });
  await db.execute(
    sql`UPDATE upload_ledger SET created_at = ${createdAt} WHERE content_hash = ${hash}`,
  );
  if (status !== undefined) {
    await db.execute(sql`UPDATE upload_ledger SET status = ${status} WHERE content_hash = ${hash}`);
  }
}

test('listUploadsForOwner returns the owner uploads newest-first with their ranked clips attached', async () => {
  const HASH_A = 'a'.repeat(64);
  const HASH_B = 'b'.repeat(64);
  await seedUpload(HASH_A, 'user_1', '2026-01-01', 'done');
  await seedUpload(HASH_B, 'user_1', '2026-02-01', 'queued');
  // A second owner's upload must never leak into user_1's history.
  await seedUpload('c'.repeat(64), 'user_2', '2026-03-01', 'done');
  // Insert clips out of rank order to prove the per-upload rank asc grouping.
  await upsertClips(db, HASH_A, [
    { ...CLIP, rank: 1, title: 'a-second' },
    { ...CLIP, rank: 0, title: 'a-first' },
  ]);

  const uploads = await listUploadsForOwner(db, 'user_1');

  // Newest-first: HASH_B (Feb) before HASH_A (Jan); user_2 excluded.
  expect(uploads.map((u) => u.contentHash)).toEqual([HASH_B, HASH_A]);
  expect(uploads[0]?.status).toBe('queued');
  expect(uploads[0]?.clips).toEqual([]); // in-flight upload, no clips yet
  expect(uploads[1]?.status).toBe('done');
  expect(uploads[1]?.clips.map((c) => c.title)).toEqual(['a-first', 'a-second']);
  // Heavy JSONB columns are excluded from the projection.
  const clip = uploads[1]?.clips[0] as Record<string, unknown>;
  expect(clip).not.toHaveProperty('subScores');
  expect(clip).not.toHaveProperty('modalitiesUsed');
  expect(clip?.clipUrl).toBe(CLIP.clipUrl);
});

test('listUploadsForOwner returns durationSec (or null when unprobed) on each upload', async () => {
  const HASH_A = 'a'.repeat(64);
  await seedUpload(HASH_A, 'user_1', '2026-01-01');
  await setSourceDuration(db, HASH_A, 200);
  const HASH_B = 'b'.repeat(64);
  await seedUpload(HASH_B, 'user_1', '2026-02-01'); // never probed → null

  const uploads = await listUploadsForOwner(db, 'user_1');
  const byHash = new Map(uploads.map((u) => [u.contentHash, u.durationSec]));
  expect(byHash.get(HASH_A)).toBe(200);
  expect(byHash.get(HASH_B)).toBeNull();
});

test('listUploadsForOwner returns an empty array for an owner with no uploads', async () => {
  await seedUpload('a'.repeat(64), 'user_1', '2026-01-01');
  expect(await listUploadsForOwner(db, 'user_other')).toEqual([]);
});

test('listUploadsForOwner honours the limit and walks pages via the keyset cursor', async () => {
  const HASH_A = 'a'.repeat(64); // oldest
  const HASH_B = 'b'.repeat(64);
  const HASH_C = 'c'.repeat(64); // newest
  await seedUpload(HASH_A, 'user_1', '2026-01-01');
  await seedUpload(HASH_B, 'user_1', '2026-02-01');
  await seedUpload(HASH_C, 'user_1', '2026-03-01');

  const page1 = await listUploadsForOwner(db, 'user_1', { limit: 2 });
  expect(page1.map((u) => u.contentHash)).toEqual([HASH_C, HASH_B]);

  const last = page1[page1.length - 1]!;
  const page2 = await listUploadsForOwner(db, 'user_1', {
    limit: 2,
    cursor: { createdAt: last.createdAt, contentHash: last.contentHash },
  });
  expect(page2.map((u) => u.contentHash)).toEqual([HASH_A]);
});
