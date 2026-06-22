import { STAGE_REQUEST_VERSION } from '@fliphouse/shared';
import type { StageRequest, StageResult } from '@fliphouse/shared';
import { DelayedError, UnrecoverableError } from 'bullmq';
import { expect, test, vi } from 'vitest';

import { GpuSubmitError } from '../gpu/gpu-submit.js';

import { executeAsr } from './execute-asr.js';
import type { AsrLaneCtx, AsrLaneDeps } from './execute-asr.js';

const HASH = 'a'.repeat(64);
const PREFIX = `intermediate/${HASH}/asr`;
const PROXY = `intermediate/${HASH}/transcode/proxy.mp4`;
const REQUEST_ID = '11111111-1111-1111-1111-111111111111';

const REQUEST: StageRequest = {
  version: STAGE_REQUEST_VERSION,
  stage: 'asr',
  contentHash: HASH,
  ownerId: 'u1',
  inputs: { source: PROXY },
  outputPrefix: PREFIX,
  params: {},
};

const INLINE_OK: StageResult = { ok: true, outputs: [{ key: 'inline' }], metrics: { ms: 1 } };

function makeCtx(over: Partial<AsrLaneCtx> = {}): AsrLaneCtx {
  return {
    stage: 'asr',
    contentHash: HASH,
    ownerId: 'u1',
    request: REQUEST,
    r2: {
      hasSentinel: vi.fn(async () => false),
      writeSentinel: vi.fn(async () => {}),
      hasFailedMarker: vi.fn(async () => false),
      writeFailedMarker: vi.fn(async () => {}),
    },
    runStage: vi.fn(async () => INLINE_OK),
    token: 'tok',
    job: { id: 'asr-job-1', moveToDelayed: vi.fn(async () => {}) },
    ...over,
  };
}

function makeDeps(over: Partial<AsrLaneDeps> = {}): AsrLaneDeps {
  return {
    gpuParkEnabled: true,
    redis: { set: vi.fn(async () => 'OK' as const), zadd: vi.fn(async () => 1) },
    gpuSubmit: vi.fn(async () => REQUEST_ID),
    presignAudio: vi.fn(async () => 'https://r2/presigned'),
    newRequestId: () => REQUEST_ID,
    nowMs: () => 1_000_000,
    gigaamEndpoint: 'https://gpu.example.com',
    webhookCallbackUrl: 'https://hook.example.com/gpu/callback',
    ...over,
  };
}

// ── flag OFF: delegate to the inline asr stage handler ──────────────────────

test('runs inline (existing executeStage path) when the park lane is disabled', async () => {
  const ctx = makeCtx();
  const deps = makeDeps({ gpuParkEnabled: false });

  const result = await executeAsr(ctx, deps);

  expect(result).toEqual(INLINE_OK);
  expect(ctx.runStage).toHaveBeenCalledOnce();
  expect(deps.gpuSubmit).not.toHaveBeenCalled();
  expect(ctx.r2.writeSentinel).toHaveBeenCalledOnce();
});

// ── re-entry decision 1: _FAILED → throw UnrecoverableError ─────────────────

test('throws UnrecoverableError on re-entry when a _FAILED marker exists', async () => {
  const r2 = {
    hasSentinel: vi.fn(async () => false),
    writeSentinel: vi.fn(async () => {}),
    hasFailedMarker: vi.fn(async () => true),
    writeFailedMarker: vi.fn(async () => {}),
    readFailedError: vi.fn(async () => 'gpu blew up'),
  };
  const ctx = makeCtx({ r2 });
  const deps = makeDeps();

  await expect(executeAsr(ctx, deps)).rejects.toBeInstanceOf(UnrecoverableError);
  expect(deps.gpuSubmit).not.toHaveBeenCalled();
});

test('falls back to a generic error message when the store cannot read the _FAILED text', async () => {
  const ctx = makeCtx({
    r2: {
      hasSentinel: vi.fn(async () => false),
      writeSentinel: vi.fn(async () => {}),
      hasFailedMarker: vi.fn(async () => true),
      writeFailedMarker: vi.fn(async () => {}),
    },
  });

  await expect(executeAsr(ctx, makeDeps())).rejects.toThrow(/unknown/);
});

// ── re-entry decision 2: _COMPLETE → success (skip-if-sentinel) ─────────────

test('returns a cached success on re-entry when the _COMPLETE sentinel exists', async () => {
  const r2 = {
    hasSentinel: vi.fn(async () => true),
    writeSentinel: vi.fn(async () => {}),
    hasFailedMarker: vi.fn(async () => false),
    writeFailedMarker: vi.fn(async () => {}),
  };
  const ctx = makeCtx({ r2 });
  const deps = makeDeps();

  const result = (await executeAsr(ctx, deps)) as StageResult;

  expect(result).toMatchObject({ ok: true, metrics: { cached: 1 } });
  expect(deps.gpuSubmit).not.toHaveBeenCalled();
  expect(ctx.r2.writeSentinel).not.toHaveBeenCalled();
});

test('checks _FAILED before _COMPLETE so a fatal always wins the decision', async () => {
  const r2 = {
    hasSentinel: vi.fn(async () => true),
    writeSentinel: vi.fn(async () => {}),
    hasFailedMarker: vi.fn(async () => true),
    writeFailedMarker: vi.fn(async () => {}),
    readFailedError: vi.fn(async () => 'boom'),
  };
  const ctx = makeCtx({ r2 });

  await expect(executeAsr(ctx, makeDeps())).rejects.toBeInstanceOf(UnrecoverableError);
});

// ── re-entry decision 3: first entry → submit-and-park ──────────────────────

test('first entry presigns, submits, parks, and throws DelayedError to free the worker', async () => {
  const ctx = makeCtx();
  const deps = makeDeps();

  await expect(executeAsr(ctx, deps)).rejects.toBeInstanceOf(DelayedError);

  expect(deps.presignAudio).toHaveBeenCalledWith(PROXY);
  expect(deps.gpuSubmit).toHaveBeenCalledWith(
    {
      endpoint: 'https://gpu.example.com',
      requestId: REQUEST_ID,
      audioUrl: 'https://r2/presigned',
      webhookUrl: 'https://hook.example.com/gpu/callback',
      outputPrefix: PREFIX,
    },
    expect.anything(),
  );
  expect(deps.redis.set).toHaveBeenCalledWith(
    `park:${REQUEST_ID}`,
    JSON.stringify({ jobId: 'asr-job-1', contentHash: HASH, outputPrefix: PREFIX }),
    'EX',
    expect.any(Number),
  );
  expect(ctx.job.moveToDelayed).toHaveBeenCalledWith(1_000_000 + 15 * 60 * 1000, 'tok');
});

test('a submit failure propagates (BullMQ retries the asr lane) and never parks', async () => {
  const ctx = makeCtx();
  const deps = makeDeps({
    gpuSubmit: vi.fn(async () => {
      throw new GpuSubmitError('503');
    }),
  });

  await expect(executeAsr(ctx, deps)).rejects.toBeInstanceOf(GpuSubmitError);
  expect(deps.redis.set).not.toHaveBeenCalled();
  expect(ctx.job.moveToDelayed).not.toHaveBeenCalled();
});

test('throws when the asr request has no source input to presign', async () => {
  const ctx = makeCtx({
    request: { ...REQUEST, inputs: {} },
  });

  await expect(executeAsr(ctx, makeDeps())).rejects.toThrow(/source/i);
});

test('throws when first-entry park is attempted without a token', async () => {
  const ctx = makeCtx({ token: undefined });

  await expect(executeAsr(ctx, makeDeps())).rejects.toThrow(/token/i);
  expect(makeDeps().gpuSubmit).not.toHaveBeenCalled();
});
