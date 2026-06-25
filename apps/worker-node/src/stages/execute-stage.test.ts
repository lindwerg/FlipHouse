import { STAGE_REQUEST_VERSION } from '@fliphouse/shared';
import type { StageRequest, StageResult } from '@fliphouse/shared';
import { UnrecoverableError } from 'bullmq';
import { expect, test, vi } from 'vitest';

import { log } from '../log.js';

import { CACHED_METRIC, executeStage, isAvDegradationAlerting } from './execute-stage.js';
import type { ArtifactStore, StageContext } from './handler-contract.js';

vi.mock('../log.js', () => ({ log: { warn: vi.fn(), info: vi.fn(), error: vi.fn() } }));

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

// ── MMV-3: a regression to all-text finalist coverage is LOUD ─────────────

test('isAvDegradationAlerting flags a majority-text finalist batch', () => {
  // 1 got video, 2 fell back / dropped → 2 > 1 → alert.
  expect(
    isAvDegradationAlerting({ av_succeeded: 1, av_failed_fellback: 1, modalities_dropped: 1 }),
  ).toBe(true);
});

test('isAvDegradationAlerting stays quiet when video coverage holds', () => {
  expect(
    isAvDegradationAlerting({ av_succeeded: 3, av_failed_fellback: 1, modalities_dropped: 0 }),
  ).toBe(false);
});

test('isAvDegradationAlerting ignores an all-budget batch and missing metrics', () => {
  // Nothing attempted video → not a regression.
  expect(
    isAvDegradationAlerting({ av_succeeded: 0, av_failed_fellback: 0, modalities_dropped: 0 }),
  ).toBe(false);
  // Non-score stage / older Python → metrics absent → no alert, no throw.
  expect(isAvDegradationAlerting({ duration_ms: 5 })).toBe(false);
});

test('warns on a successful score stage whose finalists mostly fell back to text', async () => {
  vi.mocked(log.warn).mockClear();
  const { ctx } = makeCtx({
    hasSentinel: false,
    stage: 'score',
    result: {
      ok: true,
      outputs: [{ key: 'out/clips.json' }],
      metrics: { clip_count: 3, av_succeeded: 0, av_failed_fellback: 2, modalities_dropped: 1 },
    },
  });

  await executeStage(ctx);

  expect(log.warn).toHaveBeenCalledOnce();
  expect(vi.mocked(log.warn).mock.calls[0]?.[1]).toMatch(/A\/V degradation/i);
});

test('does not warn when the score stage keeps healthy video coverage', async () => {
  vi.mocked(log.warn).mockClear();
  const { ctx } = makeCtx({
    hasSentinel: false,
    stage: 'score',
    result: {
      ok: true,
      outputs: [],
      metrics: { clip_count: 3, av_succeeded: 3, av_failed_fellback: 0, modalities_dropped: 0 },
    },
  });

  await executeStage(ctx);

  expect(log.warn).not.toHaveBeenCalled();
});

test('does not warn for a non-score stage carrying unrelated metrics', async () => {
  vi.mocked(log.warn).mockClear();
  const { ctx } = makeCtx({
    hasSentinel: false,
    stage: 'transcode',
    result: { ok: true, outputs: [], metrics: { av_succeeded: 0, av_failed_fellback: 5, modalities_dropped: 0 } },
  });

  await executeStage(ctx);

  expect(log.warn).not.toHaveBeenCalled();
});
