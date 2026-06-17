/**
 * BullMQ queue resolver — the stage → queue contract from docs/01 §5.
 *
 * The `Stage`/`QueueName` unions are owned by `@fliphouse/shared` (single
 * source of truth, shared with the flow builder and progress model). This
 * module owns only the routing table and keeps it a pure lookup (no BullMQ
 * import) so it stays trivially testable.
 */

import type { QueueName, Stage } from '@fliphouse/shared';

export type { QueueName, Stage } from '@fliphouse/shared';

const STAGE_TO_QUEUE: Readonly<Record<Stage, QueueName>> = {
  transcode: 'transcode',
  asr: 'gpu-asr',
  score: 'gpu-score',
  reframe: 'cpu',
  caption: 'cpu',
  banner: 'cpu',
  store: 'cpu',
  publish: 'publish',
};

/**
 * Resolve the BullMQ queue a stage runs on. Throws on an unknown stage so a
 * mis-routed job fails fast at the boundary instead of silently queueing wrong.
 */
export function resolveQueue(stage: Stage): QueueName {
  const queue = STAGE_TO_QUEUE[stage];
  if (queue === undefined) {
    throw new Error(`resolveQueue: unknown stage "${stage}"`);
  }
  return queue;
}
