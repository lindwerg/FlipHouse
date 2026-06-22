import IORedis, { type Redis } from 'ioredis';
import { GenericContainer, type StartedTestContainer } from 'testcontainers';
import { afterAll, beforeAll, beforeEach, expect, test } from 'vitest';

import { createRedisParker, PARK_KEY_TTL_SEC, parkKeyFor, parkValueSchema, type ParkValue } from './park.js';

// #7 — single-source GETDEL dedup, proven on a REAL Redis broker.
//
// A parked GPU job is mapped at `park:<request_id>` → {jobId, contentHash,
// outputPrefix}. Exactly ONE actor may resume it. THREE actors can race to claim
// it: a webhook delivery, a DUPLICATE webhook delivery (providers are at-least-
// once), and the lost-callback sweep. All three claim with the IDENTICAL
// primitive — `redis.getdel(parkKeyFor(id))` (webhook-receiver real-deps.ts
// `claimPrediction`, worker-node park-sweep `claim`). The resume path itself does
// NO getdel. Because GETDEL is atomic, the field of claimers collapses to exactly
// one winner; everyone else gets `null` and is a no-op. This itest is the
// load-bearing proof that the dedup holds under real concurrency — the unit suite
// can only assert the wiring, not Redis's atomicity.

const REQUEST_ID = 'req_dedup_0001';
const PARK_VALUE: ParkValue = {
  jobId: 'flow-deadbeef',
  contentHash: 'd'.repeat(64),
  outputPrefix: 'intermediate/dddd/asr',
};

let container: StartedTestContainer;
let client: Redis;

beforeAll(async () => {
  container = await new GenericContainer('redis:7-alpine').withExposedPorts(6379).start();
  client = new IORedis({ host: container.getHost(), port: container.getMappedPort(6379) });
});

afterAll(async () => {
  await client.quit();
  await container.stop();
});

beforeEach(async () => {
  await client.flushall();
});

/** SET the park mapping the production way (createRedisParker → ioredis SET EX). */
async function park(): Promise<void> {
  const parker = createRedisParker(client);
  await parker.set(parkKeyFor(REQUEST_ID), JSON.stringify(PARK_VALUE), 'EX', PARK_KEY_TTL_SEC);
}

/** The production claim primitive: atomic GETDEL → decoded value once, else null. */
async function claim(): Promise<ParkValue | null> {
  const raw = await client.getdel(parkKeyFor(REQUEST_ID));
  return raw === null ? null : parkValueSchema.parse(JSON.parse(raw));
}

test('duplicate GPU callbacks racing to claim the same parked job yield exactly ONE winner', async () => {
  await park();

  // Five at-least-once deliveries hit the webhook concurrently.
  const results = await Promise.all(Array.from({ length: 5 }, () => claim()));

  const winners = results.filter((r): r is ParkValue => r !== null);
  expect(winners).toHaveLength(1);
  expect(winners[0]).toEqual(PARK_VALUE);
  expect(results.filter((r) => r === null)).toHaveLength(4);

  // The key is gone — a later delivery (or the sweep) also gets nothing.
  expect(await claim()).toBeNull();
});

test('a webhook claim and the lost-callback sweep can never both win', async () => {
  await park();

  // The real webhook delivery and the recovery sweep fire at the same instant.
  const [webhook, sweep] = await Promise.all([claim(), claim()]);

  const won = [webhook, sweep].filter((r): r is ParkValue => r !== null);
  expect(won).toHaveLength(1);
  expect(won[0]).toEqual(PARK_VALUE);
});

test('claiming an unparked / already-claimed request is a safe no-op', async () => {
  expect(await claim()).toBeNull();
});
