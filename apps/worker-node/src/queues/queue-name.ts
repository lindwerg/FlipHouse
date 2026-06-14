/**
 * BullMQ queue resolver — the stage → queue contract from docs/01 §5.
 *
 * The Flow-DAG runs stages across six queues; the orchestrator routes each job
 * by stage. Keeping this a pure lookup (no BullMQ import) makes it trivially
 * testable and the single source of truth that P2's flow wiring lifts.
 */

/** Pipeline stages of the render Flow-DAG (docs/01 §5). */
export type Stage =
  | 'transcode'
  | 'asr'
  | 'score'
  | 'reframe'
  | 'caption'
  | 'banner'
  | 'store'
  | 'publish';

/** BullMQ queue names (docs/01 §5). */
export type QueueName = 'transcode' | 'gpu-asr' | 'gpu-score' | 'cpu' | 'publish';

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
