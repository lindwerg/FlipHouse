import { STAGE_REQUEST_VERSION } from '@fliphouse/shared';
import type { StageRequest, StageResult } from '@fliphouse/shared';
import { UnrecoverableError } from 'bullmq';
import { expect, test, vi } from 'vitest';

import { CACHED_METRIC, executeStage } from './execute-stage.js';
import type { ArtifactStore, StageContext } from './handler-contract.js';

const REQUEST: StageRequest = {
  version: STAGE_REQUEST_VERSION,
  stage: 'transcode',
  contentHash: 'a'.repeat(64),
  ownerId: 'user_1',
  inputs: { source: 'uploads/a.mp4' },
  outputPrefix: 'intermediate/a/transcode',
  params: {},
};

function makeCtx(opts: {
  hasSentinel: boolean;
  result?: StageResult;
  writeSentinel?: ArtifactStore['writeSentinel'];
  stage?: StageContext['stage'];
  setSourceDuration?: StageContext['setSourceDuration'];
}): { ctx: StageContext; runStage: ReturnType<typeof vi.fn> } {
  const runStage = vi.fn(async () => opts.result ?? ({ ok: true, outputs: [], metrics: {} } as StageResult));
  const ctx: StageContext = {
    stage: opts.stage ?? 'transcode',
    contentHash: REQUEST.contentHash,
    ownerId: REQUEST.ownerId,
    request: REQUEST,
    r2: {
      hasSentinel: async () => opts.hasSentinel,
      writeSentinel: opts.writeSentinel ?? (async () => {}),
      hasFailedMarker: async () => false,
      writeFailedMarker: async () => {},
    },
    runStage,
    ...(opts.setSourceDuration ? { setSourceDuration: opts.setSourceDuration } : {}),
  };
  return { ctx, runStage };
}

test('skips the stage when its completion sentinel already exists', async () => {
  const { ctx, runStage } = makeCtx({ hasSentinel: true });

  const result = await executeStage(ctx);

  expect(result).toEqual({ ok: true, outputs: [], metrics: { [CACHED_METRIC]: 1 } });
  expect(runStage).not.toHaveBeenCalled();
});

test('runs the stage and writes the sentinel last on success', async () => {
  const writeSentinel = vi.fn(async () => {});
  const { ctx, runStage } = makeCtx({
    hasSentinel: false,
    result: { ok: true, outputs: [{ key: 'out/t.json' }], metrics: { ms: 9 } },
    writeSentinel,
  });

  const result = await executeStage(ctx);

  expect(runStage).toHaveBeenCalledOnce();
  expect(writeSentinel).toHaveBeenCalledWith(REQUEST.outputPrefix, {
    stage: 'transcode',
    contentHash: REQUEST.contentHash,
  });
  expect(result).toMatchObject({ ok: true, outputs: [{ key: 'out/t.json' }] });
});

test('throws a non-retryable error on a fatal stage failure and skips the sentinel', async () => {
  const writeSentinel = vi.fn(async () => {});
  const { ctx } = makeCtx({
    hasSentinel: false,
    result: { ok: false, kind: 'fatal', code: 'OPENROUTER_402', message: 'no credits' },
    writeSentinel,
  });

  await expect(executeStage(ctx)).rejects.toBeInstanceOf(UnrecoverableError);
  expect(writeSentinel).not.toHaveBeenCalled();
});

test('throws a retryable error on a retryable stage failure', async () => {
  const { ctx } = makeCtx({
    hasSentinel: false,
    result: { ok: false, kind: 'retryable', code: 'KILLED', message: 'oom' },
  });

  await expect(executeStage(ctx)).rejects.toThrow(/KILLED/);
  await expect(executeStage(ctx)).rejects.not.toBeInstanceOf(UnrecoverableError);
});

test('forwards the abort signal to runStage so a wedged subprocess can be killed', async () => {
  const { ctx, runStage } = makeCtx({ hasSentinel: false });
  const signal = AbortSignal.timeout(600_000);

  await executeStage({ ...ctx, signal });

  expect(runStage).toHaveBeenCalledWith(ctx.request, signal);
});

test('persists the probed source duration (seconds) on a successful transcode', async () => {
  const setSourceDuration = vi.fn(async () => {});
  const { ctx } = makeCtx({
    hasSentinel: false,
    stage: 'transcode',
    result: { ok: true, outputs: [], metrics: { duration_ms: 5, source_duration_ms: 90_500 } },
    setSourceDuration,
  });

  await executeStage(ctx);

  // 90_500 ms → ceil to 91 whole seconds (never under-bill a partial second).
  expect(setSourceDuration).toHaveBeenCalledWith(REQUEST.contentHash, 91);
});

test('does not persist a duration for non-transcode stages', async () => {
  const setSourceDuration = vi.fn(async () => {});
  const { ctx } = makeCtx({
    hasSentinel: false,
    stage: 'score',
    result: { ok: true, outputs: [], metrics: { source_duration_ms: 90_500 } },
    setSourceDuration,
  });

  await executeStage(ctx);

  expect(setSourceDuration).not.toHaveBeenCalled();
});

test('skips the duration write when transcode omits the metric or the seam is absent', async () => {
  // Seam present but metric missing → no call (defensive: never write garbage).
  const setSourceDuration = vi.fn(async () => {});
  const { ctx } = makeCtx({
    hasSentinel: false,
    stage: 'transcode',
    result: { ok: true, outputs: [], metrics: { duration_ms: 5 } },
    setSourceDuration,
  });
  await executeStage(ctx);
  expect(setSourceDuration).not.toHaveBeenCalled();

  // Metric present but seam absent (pure unit ctx) → must not throw.
  const { ctx: ctx2 } = makeCtx({
    hasSentinel: false,
    stage: 'transcode',
    result: { ok: true, outputs: [], metrics: { source_duration_ms: 1000 } },
  });
  await expect(executeStage(ctx2)).resolves.toMatchObject({ ok: true });
});

test('does not write a duration when a cached transcode short-circuits', async () => {
  const setSourceDuration = vi.fn(async () => {});
  const { ctx } = makeCtx({ hasSentinel: true, stage: 'transcode', setSourceDuration });

  await executeStage(ctx);

  expect(setSourceDuration).not.toHaveBeenCalled();
});
