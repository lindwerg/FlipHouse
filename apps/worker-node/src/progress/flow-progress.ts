import { STAGES } from '@fliphouse/shared';
import type { Stage } from '@fliphouse/shared';

/**
 * Pure aggregate-progress model over the fixed 7-node DAG. BullMQ has no
 * whole-flow percentage, so the projector feeds the set of completed stages
 * here to derive a 0–100 value for the dashboard. Heavier stages (asr/score)
 * carry more weight so the bar tracks real wall-clock, not node count.
 */
const STAGE_WEIGHT: Readonly<Record<Stage, number>> = {
  transcode: 2,
  asr: 3,
  score: 3,
  reframe: 2,
  caption: 1,
  banner: 1,
  publish: 1,
};

const TOTAL_WEIGHT = STAGES.reduce((sum, stage) => sum + STAGE_WEIGHT[stage], 0);

/**
 * Compute flow progress (0–100, rounded) from the completed stages. Idempotent
 * in its input (duplicates are de-duplicated) and monotonic as stages complete.
 */
export function computeFlowProgress(completed: readonly Stage[]): number {
  const done = new Set(completed);
  let accrued = 0;
  for (const stage of STAGES) {
    if (done.has(stage)) accrued += STAGE_WEIGHT[stage];
  }
  return Math.round((accrued / TOTAL_WEIGHT) * 100);
}
