/**
 * Pipeline stages of the render Flow-DAG (docs/01 §5), listed in
 * children-run-first dependency order: `transcode` runs first, `publish` last.
 *
 * `fanout` is a lightweight passthrough node added to legalize the topology —
 * a BullMQ job may have only ONE parent, so the three cosmetic siblings
 * (reframe/caption/banner) cannot share `score` as a common child. They hang
 * off `fanout` instead and read the `score` artifact from R2 at runtime.
 */
export const STAGES = [
  'transcode',
  'asr',
  'score',
  'fanout',
  'reframe',
  'caption',
  'banner',
  'store',
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
