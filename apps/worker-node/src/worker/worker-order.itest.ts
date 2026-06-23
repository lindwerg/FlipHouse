import { flowJobId, STAGES } from '@fliphouse/shared';
import type { QueueName, Stage } from '@fliphouse/shared';
import { FlowProducer, QueueEvents, type ConnectionOptions, type Worker } from 'bullmq';
import { GenericContainer, type StartedTestContainer } from 'testcontainers';
import { afterAll, beforeAll, expect, test } from 'vitest';

import { enqueueFlow } from '../flow/flow-producer.js';
import { resolveQueue } from '../queues/queue-name.js';


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

  // The full DAG ran end-to-end (transcode→asr→score→reframe→caption→banner→
  // publish) on a real broker, in exactly the declared children-run-first order.
  expect(order).toEqual([
    'transcode',
    'asr',
    'score',
    'reframe',
    'caption',
    'banner',
    'publish',
  ]);
  // It is the canonical STAGES topology, not a coincidental local list.
  expect(order).toEqual([...STAGES]);

  // Every stage ran exactly once — no stage was dropped, skipped, or replayed.
  expect(new Set(order).size).toBe(order.length);

  // The terminal join (`publish`) ran strictly after every upstream stage, and
  // the root of the dependency chain (`transcode`) ran strictly first.
  expect(order.at(-1)).toBe('publish');
  expect(order.at(0)).toBe('transcode');
  for (const stage of STAGES) {
    if (stage !== 'publish') {
      expect(order.indexOf(stage)).toBeLessThan(order.indexOf('publish'));
    }
  }

  // Every stage routed to its declared queue — the GPU stages (asr/score) land
  // on the dedicated GPU queues, the cpu fan-out arms share `cpu`, publish is its
  // own queue. This is the wiring the real worker pool binds to.
  const expectedQueues: Record<Stage, QueueName> = {
    transcode: 'transcode',
    asr: 'gpu-asr',
    score: 'gpu-score',
    reframe: 'cpu',
    caption: 'cpu',
    banner: 'cpu',
    publish: 'publish',
  };
  for (const stage of STAGES) {
    expect(resolveQueue(stage)).toBe(expectedQueues[stage]);
  }
});
