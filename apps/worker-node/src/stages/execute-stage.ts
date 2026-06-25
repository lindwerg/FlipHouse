import { BillingError } from '@fliphouse/db';
import type { StageResult } from '@fliphouse/shared';
import { UnrecoverableError } from 'bullmq';
import { z } from 'zod';

import { stageErrorFrom } from '../errors/classify.js';
import { log } from '../log.js';

import type { StageContext } from './handler-contract.js';

/** Metric flag a stage emits when it short-circuits on an existing sentinel. */
export const CACHED_METRIC = 'cached';

/**
 * Score-stage A/V degradation metrics (mirrors the Python `score_handler` output).
 * `av_succeeded` is the finalists that actually got video; the other two are
 * finalists that ATTEMPTED video but fell back to text. A regression to all-text
 * (Vertex route change, prompt drift) shows normal clip counts and would otherwise
 * be invisible — so this is read and alerted on, loudly (MMV-3).
 */
const AvDegradationSchema = z.object({
  av_succeeded: z.number().nonnegative(),
  av_failed_fellback: z.number().nonnegative(),
  modalities_dropped: z.number().nonnegative(),
});

/**
 * True iff the finalists that ATTEMPTED video mostly failed to get it
 * (`av_failed_fellback + modalities_dropped > av_succeeded`). Returns `false` when
 * nothing attempted video (an all-budget batch is not a regression) or the metrics
 * are absent (non-score stage / older Python). Mirrors the Python summary floor.
 */
export function isAvDegradationAlerting(metrics: Record<string, number>): boolean {
  const parsed = AvDegradationSchema.safeParse(metrics);
  if (!parsed.success) {
    return false;
  }
  const { av_succeeded, av_failed_fellback, modalities_dropped } = parsed.data;
  const attempted = av_succeeded + av_failed_fellback + modalities_dropped;
  if (attempted === 0) {
    return false;
  }
  return av_failed_fellback + modalities_dropped > av_succeeded;
}

/**
 * On a successful `score` stage, read the A/V degradation metrics and emit ONE
 * structured WARNING when finalists mostly scored text-only — the loud, alertable
 * signal a log pipeline can threshold on (MMV-3). Pure no-op for every other stage.
 */
function alertOnAvDegradation(ctx: StageContext, result: StageSuccess): void {
  if (ctx.stage !== 'score' || !isAvDegradationAlerting(result.metrics)) {
    return;
  }
  log.warn(
    {
      stage: 'score',
      contentHash: ctx.contentHash,
      av_succeeded: result.metrics.av_succeeded,
      av_failed_fellback: result.metrics.av_failed_fellback,
      modalities_dropped: result.metrics.modalities_dropped,
    },
    'A/V degradation: finalists mostly scored text-only (video path may have regressed)',
  );
}

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
 * persist it as whole seconds (ceil — never under-bill a partial second), THEN run
 * the pre-scoring affordability gate (BILL-2) with that real duration. A cached
 * short-circuit returns BEFORE this, and a missing metric or absent seam is a
 * no-op, so the write/gate only ever happen with a real, validated quantity.
 *
 * The gate runs at the EARLIEST seam where the true duration is known and BEFORE
 * any scoring GPU/LLM spend: a `BillingError` here is re-thrown as an
 * `UnrecoverableError` so BullMQ fails the flow ONCE (an unaffordable job is a
 * permanent block, never a transient to retry into the same wall). Some transcode
 * GPU is necessarily spent first — duration is unknown until the probe — which is
 * the accepted floor (the spec's probe-seam tradeoff).
 */
async function persistSourceDuration(ctx: StageContext, result: StageSuccess): Promise<void> {
  if (ctx.stage !== 'transcode') {
    return;
  }
  const parsed = sourceDurationMsSchema.safeParse(result.metrics[SOURCE_DURATION_MS_METRIC]);
  if (!parsed.success) {
    return;
  }
  const durationSec = Math.ceil(parsed.data / 1000);
  if (ctx.setSourceDuration) {
    await ctx.setSourceDuration(ctx.contentHash, durationSec);
  }
  if (ctx.assertAffordable) {
    try {
      await ctx.assertAffordable(ctx.ownerId, durationSec);
    } catch (err) {
      if (err instanceof BillingError) {
        // A permanent affordability block → FATAL, never retried into the same wall.
        throw new UnrecoverableError(`BILLING_${err.reason.toUpperCase()}: ${err.message}`);
      }
      throw err;
    }
  }
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
  alertOnAvDegradation(ctx, result);
  await ctx.r2.writeSentinel(prefix, { stage: ctx.stage, contentHash: ctx.contentHash });
  return result;
}
