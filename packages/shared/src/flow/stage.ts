/**
 * Pipeline stages of the render Flow-DAG (docs/01 §5), listed in
 * children-run-first dependency order: `transcode` runs first, `publish` last.
 *
 * NOTE ON TOPOLOGY (P2 correction): a BullMQ Flow is a strict TREE — every job
 * has exactly one parent — so the "one predecessor → 3 parallel siblings → join"
 * diamond implied by docs/01 §5 (reframe/caption/banner sharing `score`) is NOT
 * expressible and throws `ParentJobCannotBeReplaced`. In P2 the post-score arms
 * are realized as a legal LINEAR chain (caption/banner are passthrough stubs
 * until P3/P4 render them for real). True parallel fan-out is deferred to P3 as
 * a two-phase flow (score-flow → fan-out-flow). See build-flow-tree.ts.
 */
export const STAGES = [
  'transcode',
  'asr',
  'score',
  'reframe',
  'caption',
  'banner',
  'publish',
] as const;

export type Stage = (typeof STAGES)[number];

/** BullMQ queue names the stages run on (docs/01 §5). */
export const QUEUE_NAMES = ['transcode', 'gpu-asr', 'gpu-score', 'cpu', 'publish'] as const;

export type QueueName = (typeof QUEUE_NAMES)[number];

/** Narrow an arbitrary string to a known {@link Stage}. */
export function isStage(value: string): value is Stage {
  return (STAGES as readonly string[]).includes(value);
}
