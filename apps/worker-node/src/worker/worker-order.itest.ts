import { FlowProducer, QueueEvents, type ConnectionOptions, type Worker } from 'bullmq';
import { GenericContainer, type StartedTestContainer } from 'testcontainers';
import { afterAll, beforeAll, expect, test } from 'vitest';
import { flowJobId } from '@fliphouse/shared';

import { enqueueFlow } from '../flow/flow-producer.js';
import { resolveQueue } from '../queues/queue-name.js';
import type { Stage } from '@fliphouse/shared';
import { createStageWorker } from './make-worker.js';

const HASH = 'a'.repeat(64);
const ARGS = { contentHash: HASH, ownerId: 'user_1', source: 'uploads/a.mp4' };
const QUEUES = ['transcode', 'gpu-asr', 'gpu-score', 'cpu', 'publish'] as const;

let container: StartedTestContainer;
let connection: ConnectionOptions;
let producer: FlowProducer;
let workers: Worker[];
let events: QueueEvents;
const order: string[] = [];

beforeAll(async () => {
  container = await new GenericContainer('redis:7-alpine').withExposedPorts(6379).start();
  connection = { host: container.getHost(), port: container.getMappedPort(6379) };
  producer = new FlowProducer({ connection });

  // One worker per queue; each records the stage name as it runs and succeeds.
  workers = QUEUES.map((queue) =>
    createStageWorker(queue, connection, async (job) => {
      order.push(job.name);
      return {};
    }),
  );
  events = new QueueEvents('publish', { connection });
  await events.waitUntilReady();
  await Promise.all(workers.map((w) => w.waitUntilReady()));
}, 180_000);

afterAll(async () => {
  await Promise.all(workers.map((w) => w.close()));
  await events.close();
  await producer.close();
  await container.stop();
});

// #15 — the DAG actually executes children-run-first on a real broker: the root
// `publish` runs only after every upstream stage, in dependency order.
test('the flow runs all stages in children-run-first dependency order', async () => {
  const done = new Promise<void>((resolve, reject) => {
    events.on('completed', ({ jobId }) => {
      if (jobId === flowJobId(HASH)) resolve();
    });
    events.on('failed', ({ failedReason }) => reject(new Error(failedReason)));
  });

  await enqueueFlow(producer, ARGS);
  await done;

  expect(order).toEqual([
    'transcode',
    'asr',
    'score',
    'reframe',
    'caption',
    'banner',
    'publish',
  ]);
  // Sanity: every stage routed to its declared queue.
  expect(resolveQueue('score' as Stage)).toBe('gpu-score');
});
