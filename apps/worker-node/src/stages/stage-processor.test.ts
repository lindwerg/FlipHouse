import { STAGE_REQUEST_VERSION } from '@fliphouse/shared';
import type { StageRequest, StageResult } from '@fliphouse/shared';
import type { Job } from 'bullmq';
import { expect, test, vi } from 'vitest';

import type { ArtifactStore } from './handler-contract.js';
import type { PublishDeps } from './publish.js';
import { buildStageInputs, makeStageProcessor } from './stage-processor.js';
import type { StageProcessorDeps } from './stage-processor.js';

const HASH = 'a'.repeat(64);
const SOURCE = 'uploads/a.mp4';
const PROXY = `intermediate/${HASH}/transcode/proxy.mp4`;

const OK_RESULT: StageResult = { ok: true, outputs: [{ key: 'k' }], metrics: { duration_ms: 5 } };

const MANIFEST = {
  schema_version: 2,
  source: SOURCE,
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

function job(data: Record<string, unknown>): Job {
  return { data } as unknown as Job;
}

function noopR2(): ArtifactStore {
  return { hasSentinel: vi.fn(async () => false), writeSentinel: vi.fn(async () => {}) };
}

// --- buildStageInputs: the cross-stage dependency wiring ---

test('buildStageInputs wires transcode to the original source upload', () => {
  expect(buildStageInputs('transcode', HASH, SOURCE)).toEqual({ source: SOURCE });
});

test('buildStageInputs feeds asr the transcode proxy', () => {
  expect(buildStageInputs('asr', HASH, SOURCE)).toEqual({ source: PROXY });
});

test('buildStageInputs feeds score the proxy + asr cascade transcript', () => {
  expect(buildStageInputs('score', HASH, SOURCE)).toEqual({
    source: PROXY,
    transcript: `intermediate/${HASH}/asr/cascade_transcript.json`,
  });
});

test('buildStageInputs feeds reframe the proxy + score clips', () => {
  expect(buildStageInputs('reframe', HASH, SOURCE)).toEqual({
    source: PROXY,
    clips: `intermediate/${HASH}/score/clips.json`,
  });
});

test('buildStageInputs gives caption/banner no inputs (P2 passthrough no-op)', () => {
  expect(buildStageInputs('caption', HASH, SOURCE)).toEqual({});
  expect(buildStageInputs('banner', HASH, SOURCE)).toEqual({});
});

// --- makeStageProcessor: routing + wiring ---

test('processor runs a Python stage via executeStage with the wired request', async () => {
  const r2 = noopR2();
  const runStage = vi.fn(async () => OK_RESULT);
  const deps: StageProcessorDeps = { r2, runStage, publish: {} as PublishDeps };
  const proc = makeStageProcessor(deps);

  const result = await proc(
    job({ contentHash: HASH, ownerId: 'u1', stage: 'reframe', source: SOURCE, outputPrefix: `intermediate/${HASH}/reframe` }),
    'tok',
  );

  expect(result).toEqual(OK_RESULT);
  const req = runStage.mock.calls[0]?.[0] as StageRequest;
  expect(req).toMatchObject({
    version: STAGE_REQUEST_VERSION,
    stage: 'reframe',
    contentHash: HASH,
    ownerId: 'u1',
    outputPrefix: `intermediate/${HASH}/reframe`,
    params: {},
    inputs: { source: PROXY, clips: `intermediate/${HASH}/score/clips.json` },
  });
  expect(r2.writeSentinel).toHaveBeenCalledOnce();
});

test('processor short-circuits a Python stage on an existing sentinel (cached)', async () => {
  const runStage = vi.fn(async () => OK_RESULT);
  const deps: StageProcessorDeps = {
    r2: { hasSentinel: vi.fn(async () => true), writeSentinel: vi.fn(async () => {}) },
    runStage,
    publish: {} as PublishDeps,
  };
  const proc = makeStageProcessor(deps);

  const result = (await proc(
    job({ contentHash: HASH, ownerId: 'u1', stage: 'asr', source: SOURCE, outputPrefix: `intermediate/${HASH}/asr` }),
    'tok',
  )) as StageResult;

  expect(result).toMatchObject({ ok: true, metrics: { cached: 1 } });
  expect(runStage).not.toHaveBeenCalled();
});

test('processor routes a publish job to publishUpload reading the reframe manifest', async () => {
  const readJson = vi.fn(async () => MANIFEST);
  const upsertClips = vi.fn(async () => {});
  const finishUpload = vi.fn(async () => {});
  const deps: StageProcessorDeps = {
    r2: noopR2(),
    runStage: vi.fn(),
    publish: { readJson, upsertClips, finishUpload },
  };
  const proc = makeStageProcessor(deps);

  const result = await proc(
    job({
      contentHash: HASH,
      ownerId: 'u1',
      stage: 'publish',
      source: SOURCE,
      outputPrefix: `intermediate/${HASH}/publish`,
      reframePrefix: `intermediate/${HASH}/reframe`,
    }),
    'tok',
  );

  expect(result).toEqual({ clipCount: 1 });
  expect(readJson).toHaveBeenCalledWith(`intermediate/${HASH}/reframe/manifest.json`);
  expect(upsertClips).toHaveBeenCalledOnce();
  expect(finishUpload).toHaveBeenCalledOnce();
});

test('processor throws when a publish job is missing reframePrefix', async () => {
  const proc = makeStageProcessor({ r2: noopR2(), runStage: vi.fn(), publish: {} as PublishDeps });
  await expect(
    proc(job({ contentHash: HASH, ownerId: 'u1', stage: 'publish', source: SOURCE, outputPrefix: 'p' }), 'tok'),
  ).rejects.toThrow(/reframePrefix/);
});

test('processor throws on an unknown stage', async () => {
  const proc = makeStageProcessor({ r2: noopR2(), runStage: vi.fn(), publish: {} as PublishDeps });
  await expect(
    proc(job({ contentHash: HASH, ownerId: 'u1', stage: 'thumbnail', source: SOURCE, outputPrefix: 'p' }), 'tok'),
  ).rejects.toThrow(/unknown stage/i);
});

test('processor surfaces a fatal stage failure as a thrown (unrecoverable) error', async () => {
  const runStage = async (): Promise<StageResult> => ({ ok: false, kind: 'fatal', code: 'BOOM', message: 'bad input' });
  const proc = makeStageProcessor({
    r2: { hasSentinel: vi.fn(async () => false), writeSentinel: vi.fn(async () => {}) },
    runStage,
    publish: {} as PublishDeps,
  });
  await expect(
    proc(
      job({ contentHash: HASH, ownerId: 'u1', stage: 'transcode', source: SOURCE, outputPrefix: `intermediate/${HASH}/transcode` }),
      'tok',
    ),
  ).rejects.toThrow(/BOOM/);
});
