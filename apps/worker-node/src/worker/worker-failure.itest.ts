import {
  FlowProducer,
  QueueEvents,
  UnrecoverableError,
  type ConnectionOptions,
  type Worker,
} from 'bullmq';
import { GenericContainer, type StartedTestContainer } from 'testcontainers';
import { afterAll, beforeAll, expect, test } from 'vitest';
import { flowJobId } from '@fliphouse/shared';

import { enqueueFlow } from '../flow/flow-producer.js';
import { createStageWorker } from './make-worker.js';

const HASH = 'b'.repeat(64);
const ARGS = { contentHash: HASH, ownerId: 'user_1', source: 'uploads/b.mp4' };
const QUEUES = ['transcode', 'gpu-asr', 'gpu-score', 'cpu', 'publish'] as const;

let container: StartedTestContainer;
let connection: ConnectionOptions;
let producer: FlowProducer;
let workers: Worker[];
let events: QueueEvents;
const completed: string[] = [];

beforeAll(async () => {
  container = await new GenericContainer('redis:7-alpine').withExposedPorts(6379).start();
  connection = { host: container.getHost(), port: container.getMappedPort(6379) };
  producer = new FlowProducer({ connection });

  // `score` (critical, gpu-score) fails terminally; others record on success.
  workers = QUEUES.map((queue) =>
    createStageWorker(queue, connection, async (job) => {
      if (job.name === 'score') throw new UnrecoverableError('forced score failure');
      completed.push(job.name);
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

// #19 — failParentOnFailure on the critical chain: a failed stage fails the whole
// flow; publish (and everything downstream of score) never runs.
test('a critical stage failure fails the whole flow and publish never runs', async () => {
  const rootFailed = new Promise<void>((resolve, reject) => {
    events.on('failed', ({ jobId }) => {
      if (jobId === flowJobId(HASH)) resolve();
    });
    events.on('completed', ({ jobId }) => {
      if (jobId === flowJobId(HASH)) reject(new Error('publish ran despite a critical failure'));
    });
  });

  await enqueueFlow(producer, ARGS);
  await rootFailed;

  expect(completed).toEqual(['transcode', 'asr']);
  expect(completed).not.toContain('publish');
});
