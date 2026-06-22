import { flowJobId, stageJobId } from '@fliphouse/shared';
import { FlowProducer, Queue } from 'bullmq';
import type { ConnectionOptions } from 'bullmq';
import { GenericContainer, type StartedTestContainer } from 'testcontainers';
import { afterAll, beforeAll, expect, test } from 'vitest';

import { enqueueFlow } from './flow-producer.js';

const HASH = 'a'.repeat(64);
const ARGS = { contentHash: HASH, ownerId: 'user_1', source: 'uploads/a.mp4' };

let container: StartedTestContainer;
let connection: ConnectionOptions;
let producer: FlowProducer;

beforeAll(async () => {
  container = await new GenericContainer('redis:7-alpine').withExposedPorts(6379).start();
  connection = { host: container.getHost(), port: container.getMappedPort(6379) };
  producer = new FlowProducer({ connection });
});

afterAll(async () => {
  await producer.close();
  await container.stop();
});

// #14 — the load-bearing proof: the legalized linear tree is accepted by a REAL
// BullMQ broker (the illegal shared-parent diamond would throw -7 here).
test('enqueueFlow adds the full tree to a real broker without ParentJobCannotBeReplaced', async () => {
  const node = await enqueueFlow(producer, ARGS);

  expect(node.job.id).toBe(flowJobId(HASH));
  expect(node.job.name).toBe('publish');
});

// #17 — whole-flow idempotency on real Redis: re-adding the same content dedups
// by deterministic jobId, so the leaf is enqueued exactly once.
test('re-adding the same flow is idempotent (leaf enqueued once)', async () => {
  await enqueueFlow(producer, ARGS);
  await enqueueFlow(producer, ARGS);

  const transcodeQueue = new Queue('transcode', { connection });
  try {
    const job = await transcodeQueue.getJob(stageJobId('transcode', HASH));
    expect(job?.id).toBe(stageJobId('transcode', HASH));
    expect(await transcodeQueue.getWaitingCount()).toBe(1);
  } finally {
    await transcodeQueue.close();
  }
});
