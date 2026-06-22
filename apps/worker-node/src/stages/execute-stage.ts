import type { StageResult } from '@fliphouse/shared';
import { z } from 'zod';

import { stageErrorFrom } from '../errors/classify.js';

import type { StageContext } from './handler-contract.js';

/** Metric flag a stage emits when it short-circuits on an existing sentinel. */
export const CACHED_METRIC = 'cached';

/** The transcode stage's billable-quantity metric: source duration in milliseconds. */
const SOURCE_DURATION_MS_METRIC = 'source_duration_ms';

/**
 * Validates the transcode duration metric before it is trusted for billing.
 * The 24h ceiling rejects a corrupted/forged ffprobe value that would otherwise
 * overflow `numeric(20,6)` mid-debit (after the job is 'done' → free clips).
 */
const MAX_SOURCE_DURATION_MS = 24 * 60 * 60 * 1000;
const sourceDurationMsSchema = z.number().nonnegative().max(MAX_SOURCE_DURATION_MS);

/** A successful StageResult — the only shape {@link persistSourceDuration} is called with. */
type StageSuccess = Extract<StageResult, { ok: true }>;

/**
 * On a successful `transcode`, read the validated `source_duration_ms` metric and
 * persist it as whole seconds (ceil — never under-bill a partial second). A
 * cached short-circuit returns BEFORE this, and a missing metric or absent seam
 * is a no-op, so the write only ever happens with a real, validated quantity.
 */
async function persistSourceDuration(ctx: StageContext, result: StageSuccess): Promise<void> {
  if (ctx.stage !== 'transcode' || !ctx.setSourceDuration) {
    return;
  }
  const parsed = sourceDurationMsSchema.safeParse(result.metrics[SOURCE_DURATION_MS_METRIC]);
  if (!parsed.success) {
    return;
  }
  await ctx.setSourceDuration(ctx.contentHash, Math.ceil(parsed.data / 1000));
}

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
  await persistSourceDuration(ctx, result);
  await ctx.r2.writeSentinel(prefix, { stage: ctx.stage, contentHash: ctx.contentHash });
  return result;
}
