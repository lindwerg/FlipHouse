import { gpuCallbackSchema } from './gpu-callback-types.js';

/**
 * GPU-callback orchestration (spec §6.12). Pure control flow with all effects
 * injected, so the full contract is unit-testable without a real provider. Order
 * is the invariant: (1) HMAC-verify the RAW body BEFORE any parse or mutation,
 * (2) parse into the strict {@link gpuCallbackSchema} (fail closed on garbage),
 * (3) ATOMIC dedup by prediction id (`claimPrediction` is a compare-and-delete
 * GETDEL in the real wiring — only the first delivery wins), (4) resume the
 * parked job's state machine. P2: the service is dormant, so `resumeParkedJob`
 * is wired to a noop until the GPU path activates.
 */

/** The provider→job resume result envelope handed to {@link CallbackDeps.resumeParkedJob}. */
export type ResumeResult =
  | { readonly ok: true; readonly output: unknown }
  | { readonly ok: false; readonly kind: 'retryable'; readonly error: string };

export interface CallbackDeps {
  /** Constant-time HMAC verification of the raw body (verify-hmac.ts in real wiring). */
  verifyHmacFn(rawBody: string, signatureHeader: string): boolean;
  /** Atomic dedup: returns true exactly once per predictionId (GETDEL in real wiring). */
  claimPrediction(predictionId: string): Promise<boolean>;
  /** Advance the parked job's state machine (park.ts resumeParkedJob; noop in P2). */
  resumeParkedJob(predictionId: string, result: ResumeResult): Promise<void>;
}

export type CallbackOutcome =
  | { readonly kind: 'hmac-invalid' }
  | { readonly kind: 'duplicate'; readonly predictionId: string }
  | { readonly kind: 'verified-ok'; readonly predictionId: string }
  | { readonly kind: 'verified-failed'; readonly predictionId: string };

/**
 * Verify, parse, dedup, and resume a single GPU callback. Throws (fail closed)
 * only when the body is unparseable or violates the schema AFTER a passing HMAC
 * — a verified-but-malformed callback is a contract breach, not a soft outcome.
 */
export async function handleCallback(
  rawBody: string,
  signatureHeader: string,
  deps: CallbackDeps,
): Promise<CallbackOutcome> {
  if (!deps.verifyHmacFn(rawBody, signatureHeader)) {
    return { kind: 'hmac-invalid' };
  }

  const callback = gpuCallbackSchema.parse(JSON.parse(rawBody));
  const predictionId = callback.id;

  const claimed = await deps.claimPrediction(predictionId);
  if (!claimed) {
    return { kind: 'duplicate', predictionId };
  }

  if (callback.status === 'succeeded') {
    await deps.resumeParkedJob(predictionId, { ok: true, output: callback.output });
    return { kind: 'verified-ok', predictionId };
  }

  await deps.resumeParkedJob(predictionId, {
    ok: false,
    kind: 'retryable',
    error: callback.error ?? callback.status,
  });
  return { kind: 'verified-failed', predictionId };
}
