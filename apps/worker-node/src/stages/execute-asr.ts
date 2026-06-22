/**
 * ASR lane wrapper (P2 step #1, TRACK C) — the submit-and-park entry point for
 * the `asr` stage. Flag-gated by `GPU_ASR_ENABLED` (via {@link decideParkMode}):
 *
 *   • Park lane OFF → delegate to the generic inline {@link executeStage} body
 *     (preserves the existing CPU asr behavior + tests).
 *
 *   • Park lane ON → a single re-entry decision point keyed off R2 markers under
 *     the stage's `outputPrefix`:
 *       1. `_FAILED` exists  → throw UnrecoverableError (fatal → fail the flow).
 *       2. `_COMPLETE` exists → return the cached success (skip-if-sentinel).
 *       3. neither (first entry) → mint a request id, presign the asr audio,
 *          submit to the GPU, park the job, then throw {@link DelayedError} so
 *          BullMQ frees the worker slot until the webhook/sweep promotes it.
 *
 * Every effect (redis, gpuSubmit, presign, clock, uuid, r2 markers) is injected,
 * so the whole decision machine is unit-tested to 100% with no real I/O.
 */
import type { StageResult } from '@fliphouse/shared';
import { DelayedError, UnrecoverableError } from 'bullmq';

import type { GpuSubmitArgs, GpuSubmitDeps } from '../gpu/gpu-submit.js';
import { decideParkMode, parkJob } from '../state/park.js';
import type { NowMsFn, ParkableJob, RedisParker } from '../state/park.js';

import { executeStage } from './execute-stage.js';
import type { ArtifactStore, StageContext } from './handler-contract.js';

/** The asr marker surface: the base store plus reading the `_FAILED` error text. */
export interface AsrMarkerStore extends ArtifactStore {
  /** Read the error string from the `_FAILED` marker (absent → a generic message). */
  readFailedError?(outputPrefix: string): Promise<string>;
}

/** The stage context the asr lane needs: the generic one plus the BullMQ token + parkable job. */
export interface AsrLaneCtx extends StageContext {
  readonly r2: AsrMarkerStore;
  /** BullMQ lock token, required to park (move the job to delayed) on first entry. */
  readonly token: string | undefined;
  /** The parked job handle (delayed via moveToDelayed). */
  readonly job: ParkableJob;
}

/** Presign an R2 GET for the asr audio input the GPU will fetch. */
export type PresignFn = (key: string) => Promise<string>;

/** Mint a fresh uuid request id (injected so tests are deterministic). */
export type NewRequestIdFn = () => string;

/** Everything the asr lane needs that the generic stage deps do not carry. */
export interface AsrLaneDeps {
  readonly gpuParkEnabled: boolean;
  readonly redis: RedisParker;
  readonly gpuSubmit: (args: GpuSubmitArgs, deps: GpuSubmitDeps) => Promise<string>;
  readonly presignAudio: PresignFn;
  readonly newRequestId: NewRequestIdFn;
  readonly nowMs: NowMsFn;
  readonly gigaamEndpoint: string;
  readonly webhookCallbackUrl: string;
  /** Injected fetch for gpuSubmit; defaults to the global fetch in production. */
  readonly fetchFn?: GpuSubmitDeps['fetchFn'];
}

function asUnrecoverable(error: string): UnrecoverableError {
  return new UnrecoverableError(`asr GPU failed: ${error}`);
}

/**
 * Execute the asr stage. When the park lane is off this is exactly the inline
 * stage body; when on it is the submit-and-park re-entry machine described in the
 * module doc.
 */
export async function executeAsr(ctx: AsrLaneCtx, deps: AsrLaneDeps): Promise<StageResult> {
  const decision = decideParkMode(
    deps.gpuParkEnabled
      ? { gpuParkEnabled: true, providerRequestId: deps.newRequestId() }
      : { gpuParkEnabled: false },
  );
  if (decision.mode === 'inline') {
    return executeStage(ctx);
  }

  const prefix = ctx.request.outputPrefix;

  // Decision 1: a fatal marker is authoritative and beats everything else.
  if (await ctx.r2.hasFailedMarker(prefix)) {
    const error = ctx.r2.readFailedError ? await ctx.r2.readFailedError(prefix) : 'unknown';
    throw asUnrecoverable(error);
  }

  // Decision 2: the finalize CLI wrote `_COMPLETE` last → the artifacts are ready.
  if (await ctx.r2.hasSentinel(prefix)) {
    return { ok: true, outputs: [], metrics: { cached: 1 } };
  }

  // Decision 3: first entry → submit and park.
  if (!ctx.token) {
    throw new Error('execute-asr: BullMQ token missing — cannot park the asr job');
  }
  const audioKey = ctx.request.inputs.source;
  if (!audioKey) {
    throw new Error('execute-asr: asr request has no `source` input to presign');
  }

  const requestId = decision.providerRequestId;
  const audioUrl = await deps.presignAudio(audioKey);
  await deps.gpuSubmit(
    {
      endpoint: deps.gigaamEndpoint,
      requestId,
      audioUrl,
      webhookUrl: deps.webhookCallbackUrl,
      outputPrefix: prefix,
    },
    { fetchFn: deps.fetchFn ?? globalFetch },
  );

  await parkJob({
    providerRequestId: requestId,
    job: ctx.job,
    token: ctx.token,
    redis: deps.redis,
    contentHash: ctx.contentHash,
    outputPrefix: prefix,
    nowMs: deps.nowMs,
  });

  // Hand the slot back to BullMQ. The park deadline (now + MAX_PARK_MS, set in
  // parkJob) is the lost-callback backstop; the happy path is a webhook-driven
  // changeDelay(0) that re-runs this lane to hit the `_COMPLETE` branch.
  throw new DelayedError('asr parked on GPU prediction');
}

/* v8 ignore start -- real global fetch; the injected fetchFn is unit-tested */
const globalFetch: GpuSubmitDeps['fetchFn'] = (url, init) => fetch(url, init);
/* v8 ignore stop */
