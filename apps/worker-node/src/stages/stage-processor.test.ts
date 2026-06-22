import { STAGE_REQUEST_VERSION } from '@fliphouse/shared';
import type { StageRequest, StageResult } from '@fliphouse/shared';
import type { Job } from 'bullmq';
import { expect, test, vi } from 'vitest';

import type { AsrLaneDeps, AsrMarkerStore } from './execute-asr.js';
import type { PublishDeps } from './publish.js';
import { buildStageInputs, makeStageProcessor, stageAbortSignal } from './stage-processor.js';
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

function noopR2(): AsrMarkerStore {
  return {
    hasSentinel: vi.fn(async () => false),
    writeSentinel: vi.fn(async () => {}),
    hasFailedMarker: vi.fn(async () => false),
    writeFailedMarker: vi.fn(async () => {}),
  };
}

/** ASR lane deps with the park lane OFF — asr delegates to the inline stage body. */
function inlineAsr(): AsrLaneDeps {
  return {
    gpuParkEnabled: false,
    redis: { set: vi.fn(async () => 'OK' as const), zadd: vi.fn(async () => 1) },
    gpuSubmit: vi.fn(async () => 'req'),
    presignAudio: vi.fn(async () => 'url'),
    newRequestId: () => 'req',
    nowMs: () => 0,
    gigaamEndpoint: 'https://gpu',
    webhookCallbackUrl: 'https://hook/gpu/callback',
  };
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

test('buildStageInputs wires caption to the reframe manifest + asr word_segments + clips prefix', () => {
  expect(buildStageInputs('caption', HASH, SOURCE)).toEqual({
    manifest: `intermediate/${HASH}/reframe/manifest.json`,
    word_segments: `intermediate/${HASH}/asr/word_segments.json`,
    clips_prefix: `intermediate/${HASH}/reframe`,
  });
});

test('buildStageInputs gives banner no inputs (still a P2 passthrough no-op)', () => {
  expect(buildStageInputs('banner', HASH, SOURCE)).toEqual({});
});

// --- makeStageProcessor: routing + wiring ---

test('processor runs a Python stage via executeStage with the wired request', async () => {
  const r2 = noopR2();
  const runStage = vi.fn(async () => OK_RESULT);
  const deps: StageProcessorDeps = { r2, runStage, publish: {} as PublishDeps, asr: inlineAsr() };
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
    r2: {
      hasSentinel: vi.fn(async () => true),
      writeSentinel: vi.fn(async () => {}),
      hasFailedMarker: vi.fn(async () => false),
      writeFailedMarker: vi.fn(async () => {}),
    },
    runStage,
    publish: {} as PublishDeps,
    asr: inlineAsr(),
  };
  const proc = makeStageProcessor(deps);

  const result = (await proc(
    job({ contentHash: HASH, ownerId: 'u1', stage: 'asr', source: SOURCE, outputPrefix: `intermediate/${HASH}/asr` }),
    'tok',
  )) as StageResult;

  expect(result).toMatchObject({ ok: true, metrics: { cached: 1 } });
  expect(runStage).not.toHaveBeenCalled();
});

test('processor routes a publish job to publishUpload reading the caption manifest', async () => {
  const readJson = vi.fn(async () => MANIFEST);
  const copyObject = vi.fn(async () => {});
  const upsertClips = vi.fn(async () => {});
  const finishUpload = vi.fn(async () => {});
  const deps: StageProcessorDeps = {
    r2: noopR2(),
    runStage: vi.fn(),
    publish: { readJson, copyObject, upsertClips, finishUpload },
    asr: inlineAsr(),
  };
  const proc = makeStageProcessor(deps);

  const result = await proc(
    job({
      contentHash: HASH,
      ownerId: 'u1',
      stage: 'publish',
      source: SOURCE,
      outputPrefix: `intermediate/${HASH}/publish`,
      clipsPrefix: `intermediate/${HASH}/caption`,
    }),
    'tok',
  );

  expect(result).toEqual({ clipCount: 1 });
  expect(readJson).toHaveBeenCalledWith(`intermediate/${HASH}/caption/manifest.json`);
  expect(upsertClips).toHaveBeenCalledOnce();
  expect(finishUpload).toHaveBeenCalledOnce();
});

test('processor throws when a publish job is missing clipsPrefix', async () => {
  const proc = makeStageProcessor({ r2: noopR2(), runStage: vi.fn(), publish: {} as PublishDeps, asr: inlineAsr() });
  await expect(
    proc(job({ contentHash: HASH, ownerId: 'u1', stage: 'publish', source: SOURCE, outputPrefix: 'p' }), 'tok'),
  ).rejects.toThrow(/clipsPrefix/);
});

test('processor throws on an unknown stage', async () => {
  const proc = makeStageProcessor({ r2: noopR2(), runStage: vi.fn(), publish: {} as PublishDeps, asr: inlineAsr() });
  await expect(
    proc(job({ contentHash: HASH, ownerId: 'u1', stage: 'thumbnail', source: SOURCE, outputPrefix: 'p' }), 'tok'),
  ).rejects.toThrow(/unknown stage/i);
});

test('processor surfaces a fatal stage failure as a thrown (unrecoverable) error', async () => {
  const runStage = async (): Promise<StageResult> => ({ ok: false, kind: 'fatal', code: 'BOOM', message: 'bad input' });
  const proc = makeStageProcessor({
    r2: {
      hasSentinel: vi.fn(async () => false),
      writeSentinel: vi.fn(async () => {}),
      hasFailedMarker: vi.fn(async () => false),
      writeFailedMarker: vi.fn(async () => {}),
    },
    runStage,
    publish: {} as PublishDeps,
    asr: inlineAsr(),
  });
  await expect(
    proc(
      job({ contentHash: HASH, ownerId: 'u1', stage: 'transcode', source: SOURCE, outputPrefix: `intermediate/${HASH}/transcode` }),
      'tok',
    ),
  ).rejects.toThrow(/BOOM/);
});

test('processor routes the asr stage to the submit-and-park lane, threading token + job', async () => {
  const moveToDelayed = vi.fn(async () => {});
  const asr: AsrLaneDeps = {
    gpuParkEnabled: true,
    redis: { set: vi.fn(async () => 'OK' as const), zadd: vi.fn(async () => 1) },
    gpuSubmit: vi.fn(async () => 'req-xyz'),
    presignAudio: vi.fn(async () => 'https://r2/presigned'),
    newRequestId: () => 'req-xyz',
    nowMs: () => 0,
    gigaamEndpoint: 'https://gpu',
    webhookCallbackUrl: 'https://hook/gpu/callback',
  };
  const proc = makeStageProcessor({ r2: noopR2(), runStage: vi.fn(), publish: {} as PublishDeps, asr });

  const asrJob = { data: { contentHash: HASH, ownerId: 'u1', stage: 'asr', source: SOURCE, outputPrefix: `intermediate/${HASH}/asr` }, id: 'asr-1', moveToDelayed } as unknown as Job;

  await expect(proc(asrJob, 'tok-123')).rejects.toMatchObject({ name: 'DelayedError' });
  expect(asr.gpuSubmit).toHaveBeenCalledOnce();
  expect(moveToDelayed).toHaveBeenCalledWith(15 * 60 * 1000, 'tok-123');
});

// --- stageAbortSignal: per-stage timeout ∪ BullMQ cancellation (H1) ---

test('stageAbortSignal fires after the timeout when no BullMQ signal is given', async () => {
  const signal = stageAbortSignal(undefined, 5);
  expect(signal.aborted).toBe(false);
  await new Promise<void>((resolve) => signal.addEventListener('abort', () => resolve()));
  expect(signal.aborted).toBe(true);
});

test('stageAbortSignal is already aborted when the BullMQ signal is pre-aborted', () => {
  const signal = stageAbortSignal(AbortSignal.abort(), 600_000);
  expect(signal.aborted).toBe(true);
});

test('processor forwards a stage abort signal to runStage (so a wedged subprocess is killable)', async () => {
  const runStage = vi.fn(async () => OK_RESULT);
  const proc = makeStageProcessor({ r2: noopR2(), runStage, publish: {} as PublishDeps, asr: inlineAsr() });

  await proc(
    job({ contentHash: HASH, ownerId: 'u1', stage: 'reframe', source: SOURCE, outputPrefix: `intermediate/${HASH}/reframe` }),
    'tok',
    AbortSignal.timeout(600_000),
  );

  const forwarded = runStage.mock.calls[0]?.[1];
  expect(forwarded).toBeInstanceOf(AbortSignal);
});
