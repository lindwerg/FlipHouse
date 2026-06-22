import type { Stage, StageRequest, StageResult } from '@fliphouse/shared';

/**
 * R2 artifact store, narrowed to the sentinel operations a stage needs. A stage
 * writes its `_COMPLETE` sentinel LAST (after all artifacts), and skip-if-exists
 * checks ONLY the sentinel — a bare object HEAD can be a truncated/partial file.
 *
 * The `_FAILED` marker is the asr-lane fatal sentinel: the `asr-resume` consumer
 * writes it (on an `asr-fail` job) BEFORE promoting the parked job, so re-entry
 * sees it and throws an unrecoverable error rather than re-submitting.
 */
export interface ArtifactStore {
  hasSentinel(outputPrefix: string): Promise<boolean>;
  writeSentinel(outputPrefix: string, marker: Record<string, unknown>): Promise<void>;
  /** True iff a `_FAILED` marker exists under the prefix (the asr fatal sentinel). */
  hasFailedMarker(outputPrefix: string): Promise<boolean>;
  /** Write the `_FAILED` marker carrying the provider error (idempotent, write-once). */
  writeFailedMarker(outputPrefix: string, error: string): Promise<void>;
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
  /**
   * Persist the probed source duration (whole seconds) for billing — invoked
   * after a successful `transcode` when its `source_duration_ms` metric is
   * present. Absent in pure unit contexts (no-op then); wired to the ledger in
   * production. Idempotent (forward-only UPDATE), so a transcode retry is safe.
   */
  readonly setSourceDuration?: (contentHash: string, durationSec: number) => Promise<void>;
}

export type StageHandler = (ctx: StageContext) => Promise<StageResult>;
