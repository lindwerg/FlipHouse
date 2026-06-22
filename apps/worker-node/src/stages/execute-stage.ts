import type { StageResult } from '@fliphouse/shared';

import { stageErrorFrom } from '../errors/classify.js';

import type { StageContext } from './handler-contract.js';

/** Metric flag a stage emits when it short-circuits on an existing sentinel. */
export const CACHED_METRIC = 'cached';

/**
 * Generic stage body shared by every handler: skip-if-the-sentinel-exists
 * (crash-safe artifact reuse), otherwise run the Python stage, throw a
 * correctly-classified BullMQ error on failure (fatal → no retry), and write
 * the completion sentinel LAST on success.
 */
export async function executeStage(ctx: StageContext): Promise<StageResult> {
  const prefix = ctx.request.outputPrefix;
  if (await ctx.r2.hasSentinel(prefix)) {
    return { ok: true, outputs: [], metrics: { [CACHED_METRIC]: 1 } };
  }
  const result = await ctx.runStage(ctx.request, ctx.signal);
  if (!result.ok) {
    throw stageErrorFrom(result);
  }
  await ctx.r2.writeSentinel(prefix, { stage: ctx.stage, contentHash: ctx.contentHash });
  return result;
}
