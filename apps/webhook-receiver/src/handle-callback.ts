import { z } from 'zod';

import { gpuCallbackSchema } from './gpu-callback-types.js';
import type { AsrPayload } from './gpu-callback-types.js';

/**
 * GigaAM-v3 ASR callback orchestration (P2 step #1, TRACK B). Pure control flow
 * with all effects injected, so the full contract is unit-testable without Redis,
 * R2, or BullMQ. The fail-closed order is the invariant:
 *
 *   1. HMAC-verify `${timestamp}.${rawBody}` over the RAW body (replay-windowed),
 *   2. JSON-parse + validate into the strict {@link gpuCallbackSchema},
 *   3. ATOMIC dedup: `claimPrediction` performs the SINGLE `GETDEL park:<id>` —
 *      it returns the park value once and `null` for every duplicate/late call,
 *   4. act on the won claim — on `succeeded`, persist the raw payload to R2 then
 *      enqueue the `asr-resume` job; on `failed`, fail the parked job.
 *
 * NOTHING else may GETDEL the park key (the worker-node resume path must not), so
 * dedup is authoritative in exactly one place.
 */

/** Prefix of the Redis key mapping an ASR request back to its parked BullMQ job. */
export const PARK_KEY_PREFIX = 'park:';

/** BullMQ queue the resume job is enqueued onto (worker-node consumes it). */
export const QUEUE_ASR_RESUME = 'asr-resume';

/** The Redis key a request id was parked under. */
export function parkKeyFor(requestId: string): string {
  return `${PARK_KEY_PREFIX}${requestId}`;
}

/** R2 key the raw GigaAM payload is persisted to on a winning success claim. */
export function rawPayloadKeyFor(contentHash: string): string {
  return `intermediate/${contentHash}/asr/_raw_gigaam.json`;
}

/**
 * The value stored at `park:<request_id>` by the worker-node park seam, decoded
 * by {@link claimPrediction}. Carries the contentHash/outputPrefix the resume job
 * needs (a bare jobId could not reconstruct them).
 */
export const parkValueSchema = z.object({
  jobId: z.string().min(1),
  contentHash: z.string().min(1),
  outputPrefix: z.string().min(1),
});

export type ParkValue = z.infer<typeof parkValueSchema>;

/** Payload of the `asr-resume` BullMQ job (worker-node MUST match this shape). */
export interface AsrResumeJob {
  readonly jobId: string;
  readonly requestId: string;
  readonly rawPayloadKey: string;
  readonly contentHash: string;
  readonly outputPrefix: string;
}

export interface CallbackDeps {
  /** Constant-time, replay-windowed HMAC over `${timestamp}.${rawBody}`. */
  verifyHmacFn(rawBody: string, signatureHeader: string, timestampHeader: string): boolean;
  /**
   * The SINGLE atomic dedup: a `GETDEL park:<requestId>` that returns the decoded
   * park value exactly once and `null` for duplicate/late callbacks.
   */
  claimPrediction(requestId: string): Promise<ParkValue | null>;
  /** Persist the raw GigaAM payload verbatim to R2 at `rawPayloadKey`. */
  writeRawPayload(rawPayloadKey: string, payload: AsrPayload): Promise<void>;
  /** Enqueue the `asr-resume` job that advances the parked job's state machine. */
  enqueueResume(job: AsrResumeJob): Promise<void>;
  /** Move the parked job to failed with the provider error (never silently drop). */
  failParkedJob(jobId: string, error: string): Promise<void>;
}

export type CallbackOutcome =
  | { readonly kind: 'hmac-invalid' }
  | { readonly kind: 'duplicate'; readonly requestId: string }
  | { readonly kind: 'verified-ok'; readonly requestId: string }
  | { readonly kind: 'verified-failed'; readonly requestId: string };

/**
 * Verify, parse, dedup, and act on a single GigaAM callback. Throws (fail closed)
 * only when the body is unparseable or violates the schema AFTER a passing HMAC —
 * a verified-but-malformed callback is a contract breach, not a soft outcome.
 */
export async function handleCallback(
  rawBody: string,
  signatureHeader: string,
  timestampHeader: string,
  deps: CallbackDeps,
): Promise<CallbackOutcome> {
  if (!deps.verifyHmacFn(rawBody, signatureHeader, timestampHeader)) {
    return { kind: 'hmac-invalid' };
  }

  const callback = gpuCallbackSchema.parse(JSON.parse(rawBody));
  const requestId = callback.request_id;

  const parkValue = await deps.claimPrediction(requestId);
  if (parkValue === null) {
    return { kind: 'duplicate', requestId };
  }

  if (callback.status === 'succeeded') {
    const rawPayloadKey = rawPayloadKeyFor(parkValue.contentHash);
    await deps.writeRawPayload(rawPayloadKey, callback.payload);
    await deps.enqueueResume({
      jobId: parkValue.jobId,
      requestId,
      rawPayloadKey,
      contentHash: parkValue.contentHash,
      outputPrefix: parkValue.outputPrefix,
    });
    return { kind: 'verified-ok', requestId };
  }

  await deps.failParkedJob(parkValue.jobId, callback.error);
  return { kind: 'verified-failed', requestId };
}
