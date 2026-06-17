import { UnrecoverableError } from 'bullmq';
import { expect, test, vi } from 'vitest';
import { STAGE_REQUEST_VERSION } from '@fliphouse/shared';
import type { StageRequest, StageResult } from '@fliphouse/shared';

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
}): { ctx: StageContext; runStage: ReturnType<typeof vi.fn> } {
  const runStage = vi.fn(async () => opts.result ?? ({ ok: true, outputs: [], metrics: {} } as StageResult));
  const ctx: StageContext = {
    stage: 'transcode',
    contentHash: REQUEST.contentHash,
    ownerId: REQUEST.ownerId,
    request: REQUEST,
    r2: {
      hasSentinel: async () => opts.hasSentinel,
      writeSentinel: opts.writeSentinel ?? (async () => {}),
    },
    runStage,
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
