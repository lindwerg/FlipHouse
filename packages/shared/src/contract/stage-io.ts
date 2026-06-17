import { z } from 'zod';

/**
 * Versioned wire contract between the Node BullMQ worker and the Python stage
 * CLI (`python -m fliphouse_worker.cli <stage>`). The worker writes a
 * {@link StageRequest} as JSON to stdin; the CLI replies with exactly one
 * framed {@link StageResult} on stdout (see `python/spawn.ts`). Bumping the
 * version forces both sides to agree on shape.
 */
export const STAGE_REQUEST_VERSION = 1;

/** A reference to one artifact in R2, produced or consumed by a stage. */
export const artifactRefSchema = z.object({
  key: z.string().min(1),
  bytes: z.number().int().nonnegative().optional(),
  sha256: z.string().optional(),
});

export type ArtifactRef = z.infer<typeof artifactRefSchema>;

export const stageRequestSchema = z.object({
  version: z.literal(STAGE_REQUEST_VERSION),
  stage: z.string().min(1),
  contentHash: z.string().min(1),
  ownerId: z.string().min(1),
  /** Upstream artifacts keyed by logical name (e.g. `source`, `transcript`). */
  inputs: z.record(z.string(), z.string()),
  /** R2 key prefix this stage writes its outputs under. */
  outputPrefix: z.string().min(1),
  /** Stage-specific tuning knobs, opaque to the transport. */
  params: z.record(z.string(), z.unknown()),
});

export type StageRequest = z.infer<typeof stageRequestSchema>;

/** Whether a failed stage should be retried by BullMQ or fail the flow at once. */
export const FAILURE_KINDS = ['fatal', 'retryable'] as const;
export type FailureKind = (typeof FAILURE_KINDS)[number];

const stageSuccessSchema = z.object({
  ok: z.literal(true),
  outputs: z.array(artifactRefSchema),
  metrics: z.record(z.string(), z.number()),
});

const stageFailureSchema = z.object({
  ok: z.literal(false),
  kind: z.enum(FAILURE_KINDS),
  code: z.string().min(1),
  message: z.string(),
});

/** Discriminated result of running one stage. `ok` is the discriminant. */
export const stageResultSchema = z.discriminatedUnion('ok', [stageSuccessSchema, stageFailureSchema]);

export type StageResult = z.infer<typeof stageResultSchema>;
