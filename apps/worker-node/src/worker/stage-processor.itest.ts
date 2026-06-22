import { flowJobId } from '@fliphouse/shared';
import type { StageRequest, StageResult } from '@fliphouse/shared';
import { FlowProducer, QueueEvents, type ConnectionOptions, type Worker } from 'bullmq';
import { GenericContainer, type StartedTestContainer } from 'testcontainers';
import { afterAll, beforeAll, expect, test } from 'vitest';

import { enqueueFlow } from '../flow/flow-producer.js';
import type { AsrLaneDeps, AsrMarkerStore } from '../stages/execute-asr.js';
import type { PublishDeps } from '../stages/publish.js';
import { makeStageProcessor } from '../stages/stage-processor.js';

import { createStageWorker } from './make-worker.js';

const HASH = 'c'.repeat(64);
const ARGS = { contentHash: HASH, ownerId: 'user_1', source: 'uploads/c.mp4' };
const QUEUES = ['transcode', 'gpu-asr', 'gpu-score', 'cpu', 'publish'] as const;

const MANIFEST = {
  schema_version: 2,
  source: 'uploads/c.mp4',
  engine: 'fliphouse-cpu-mediapipe-v1',
  generated_at: '2026-06-17T00:00:00Z',
  resolution: [1080, 1920],
  clip_count: 1,
  clips: [
    {
      rank: 0,
      score: 88,
      sub_scores: { hook: 9 },
      confidence: 80,
      start_time: 1,
      end_time: 20,
      duration_s: 19,
      width: 1080,
      height: 1920,
      path: 'clip_00.mp4',
      title: 'A',
      used_video: true,
      model_used: 'gemini',
      modalities_used: ['text'],
    },
  ],
};

let container: StartedTestContainer;
let connection: ConnectionOptions;
let producer: FlowProducer;
let workers: Worker[];
let events: QueueEvents;

// In-memory fakes: a real broker drives the real processor, but the external
// I/O (R2 sentinels, Python subprocess, DB) is faked so the test is hermetic.
const sentinels = new Set<string>();
const ranPythonStages: string[] = [];
const clipRows: unknown[] = [];

beforeAll(async () => {
  container = await new GenericContainer('redis:7-alpine').withExposedPorts(6379).start();
  connection = { host: container.getHost(), port: container.getMappedPort(6379) };
  producer = new FlowProducer({ connection });

  const r2: AsrMarkerStore = {
    hasSentinel: async (prefix) => sentinels.has(prefix),
    writeSentinel: async (prefix) => {
      sentinels.add(prefix);
    },
    hasFailedMarker: async () => false,
    writeFailedMarker: async () => {},
  };
  const runStage = async (request: StageRequest): Promise<StageResult> => {
    ranPythonStages.push(request.stage);
    return { ok: true, outputs: [], metrics: {} };
  };
  const publish: PublishDeps = {
    readJson: async () => MANIFEST,
    copyObject: async () => {},
    upsertClips: async (_hash, rows) => {
      clipRows.push(...rows);
    },
    finishUpload: async () => {},
  };
  // Park lane OFF → the asr stage runs inline (executeStage), preserving the
  // existing end-to-end DAG behavior this integration test asserts.
  const asr: AsrLaneDeps = {
    gpuParkEnabled: false,
    redis: { set: async () => 'OK', zadd: async () => 0 },
    gpuSubmit: async () => 'req',
    presignAudio: async () => '',
    newRequestId: () => 'req',
    nowMs: () => 0,
    gigaamEndpoint: '',
    webhookCallbackUrl: '',
  };
  const processor = makeStageProcessor({ r2, runStage, publish, asr });

  workers = QUEUES.map((queue) => createStageWorker(queue, connection, processor));
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

// The real processor drives the whole DAG on a real broker: every Python stage
// runs (in dependency order) and the publish root writes the manifest's clips.
test('makeStageProcessor runs the full flow and publishes clip rows', async () => {
  const done = new Promise<void>((resolve, reject) => {
    events.on('completed', ({ jobId }) => {
      if (jobId === flowJobId(HASH)) resolve();
    });
    events.on('failed', ({ failedReason }) => reject(new Error(failedReason)));
  });

  await enqueueFlow(producer, ARGS);
  await done;

  expect(ranPythonStages).toEqual(['transcode', 'asr', 'score', 'reframe', 'caption', 'banner']);
  // publish read the reframe manifest and upserted its single clip row.
  expect(clipRows).toHaveLength(MANIFEST.clips.length);
});
