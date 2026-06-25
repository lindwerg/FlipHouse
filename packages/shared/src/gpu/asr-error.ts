/**
 * GigaAM ASR failure-reason classification (TRANS-4).
 *
 * The GPU transcription service tags an HF/pyannote auth-class fault (an expired
 * or terms-unaccepted `HF_TOKEN` rejecting the gated `pyannote/segmentation-3.0`
 * VAD) with a stable, greppable prefix in the failure callback's `error` string.
 * Both the webhook-receiver (live callback) and the worker-node park-sweep (lost
 * callback) route GPU errors, so this single classifier lets EITHER surface a
 * DISTINCT, operator-actionable fail reason instead of an indistinguishable
 * "failed" — an expired token then reads as itself rather than masquerading as a
 * real transcription fault.
 *
 * The prefix MUST stay byte-identical to `GIGAAM_AUTH_ERROR_PREFIX` in
 * `services/gpu-gigaam/fliphouse_gigaam/errors.py`.
 */

/** Stable prefix the GPU service stamps on an HF/pyannote auth-class failure. */
export const GIGAAM_AUTH_ERROR_PREFIX = 'gigaam-auth-error:';

/** Operator-facing reason an auth-class failure is mapped to (diagnosable). */
export const GIGAAM_AUTH_FAIL_REASON =
  'transcription unavailable: GigaAM GPU rejected the gated VAD (check HF_TOKEN — ' +
  'expired or model terms not accepted)';

/** True when a GPU failure `error` string is an HF/pyannote auth-class fault. */
export function isGigaamAuthError(error: string): boolean {
  return error.startsWith(GIGAAM_AUTH_ERROR_PREFIX);
}

/**
 * Map a raw GPU failure `error` into the reason recorded against the job. An
 * auth-class fault becomes the distinct {@link GIGAAM_AUTH_FAIL_REASON} (with the
 * raw provider detail appended for diagnosis); anything else passes through
 * verbatim.
 */
export function classifyAsrFailReason(error: string): string {
  if (!isGigaamAuthError(error)) {
    return error;
  }
  const detail = error.slice(GIGAAM_AUTH_ERROR_PREFIX.length).trim();
  return detail ? `${GIGAAM_AUTH_FAIL_REASON} — ${detail}` : GIGAAM_AUTH_FAIL_REASON;
}
