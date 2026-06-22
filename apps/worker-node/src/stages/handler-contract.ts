import type { Stage, StageRequest, StageResult } from '@fliphouse/shared';

/**
 * R2 artifact store, narrowed to the sentinel operations a stage needs. A stage
 * writes its `_COMPLETE` sentinel LAST (after all artifacts), and skip-if-exists
 * checks ONLY the sentinel — a bare object HEAD can be a truncated/partial file.
 */
export interface ArtifactStore {
  hasSentinel(outputPrefix: string): Promise<boolean>;
  writeSentinel(outputPrefix: string, marker: Record<string, unknown>): Promise<void>;
}

/** Everything a stage handler needs, all injectable for unit testing. */
export interface StageContext {
  readonly stage: Stage;
  readonly contentHash: string;
  readonly ownerId: string;
  readonly request: StageRequest;
  readonly r2: ArtifactStore;
  /**
   * Run the Python stage, aborting it if `signal` fires (per-stage timeout ∪
   * BullMQ's own cancellation). The subprocess is killed (process-group) so a
   * wedged ffmpeg/MediaPipe never holds the worker lock to expiry and double-runs.
   */
  readonly runStage: (request: StageRequest, signal?: AbortSignal) => Promise<StageResult>;
  /** Abort signal forwarded to {@link runStage}; absent in pure unit contexts. */
  readonly signal?: AbortSignal;
}

export type StageHandler = (ctx: StageContext) => Promise<StageResult>;
